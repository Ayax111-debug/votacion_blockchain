from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.http import JsonResponse
from .models import Persona, EventoEleccion, Candidatura, Administrador, ParticipacionEleccion, Voto
from .forms import LoginForm, CandidatoForm, EditarPersonaForm, EventoEleccionForm,LoginForm_votante
import uuid
from django.utils import timezone
from django.core.paginator import Paginator
from django.db.models.signals import pre_save
from django.dispatch import receiver
from .utils import requiere_votante_sesion
from uuid import UUID
from django.db.models import Count
import os
import logging

logger = logging.getLogger(__name__)

@requiere_votante_sesion
def votar_evento(request, evento_id):
    # Get votante_id to check if already voted
    votante_id = request.session.get('votante_id')
    
    # Check if user has already voted in this event (redirect to panel if true)
    if votante_id:
        from .models import Voto
        existing_vote = Voto.objects.filter(evento_id=evento_id, persona_votante_id=votante_id).first()
        if existing_vote:
            messages.warning(request, "Ya has votado en este evento.")
            return redirect('panel_usuario')
    
    # Avoid instantiating the full EventoEleccion model to prevent
    # DB-driver datetime->string conversion issues that break Django's
    # timezone utilities. Load only needed fields and normalize datetimes.
    ev = EventoEleccion.objects.filter(id=evento_id).values('id', 'nombre', 'fecha_inicio', 'fecha_termino').first()
    if not ev:
        from django.http import Http404
        raise Http404("Evento no encontrado")

    from datetime import datetime
    fi = ev.get('fecha_inicio')
    ft = ev.get('fecha_termino')
    if isinstance(fi, str):
        try:
            fi = datetime.fromisoformat(fi)
        except Exception:
            try:
                fi = datetime.strptime(fi, '%Y-%m-%d %H:%M:%S')
            except Exception:
                fi = None
    if isinstance(ft, str):
        try:
            ft = datetime.fromisoformat(ft)
        except Exception:
            try:
                ft = datetime.strptime(ft, '%Y-%m-%d %H:%M:%S')
            except Exception:
                ft = None

    evento = {
        'id': ev['id'],
        'nombre': ev['nombre'],
        'fecha_inicio': fi,
        'fecha_termino': ft,
    }

    # Avoid instantiating Candidatura model objects (which include datetime
    # fields) — fetch only persona info needed for the template to prevent
    # DB-driver datetime->string conversion issues.
    candidatos_qs = Candidatura.objects.filter(evento_id=evento_id).values('persona__id', 'persona__nombre', 'persona__foto_url')
    candidatos = []
    for c in candidatos_qs:
        candidatos.append({
            'persona': {
                'id': c.get('persona__id'),
                'nombre': c.get('persona__nombre'),
                'foto_url': c.get('persona__foto_url'),
            }
        })

    if request.method == "POST":
        candidato_id = request.POST.get("candidato")
        from .models import Voto, ParticipacionEleccion, Persona
        
        # Get votante_id first (required for all subsequent operations)
        votante_id = request.session.get('votante_id')
        if not votante_id:
            logger.error("No votante_id in session")
            return JsonResponse({"success": False, "error": "Session expired. Please login again."}, status=401)
        
        # Check if user has already voted in this event
        existing_vote = Voto.objects.filter(evento_id=evento_id, persona_votante_id=votante_id).first()
        if existing_vote:
            logger.warning(f"User {votante_id} attempted to vote again in event {evento_id}")
            return JsonResponse({
                "success": False, 
                "error": "Ya has votado en este evento. No puedes votar más de una vez."
            }, status=400)
        
        # Compute commitment using voter secret (if available)
        voter_secret = None
        try:
            votante = Persona.objects.filter(id=votante_id).values('id', 'clave').first()
            if votante:
                voter_secret = votante.get('clave')
        except Exception as e:
            logger.exception(f"Error fetching voter data: {e}")
            voter_secret = None

        commitment = None
        try:
            if voter_secret:
                # Local import to avoid failing app import if web3 not installed
                from .web3_utils import VotingBlockchain
                commitment = VotingBlockchain.generate_commitment(voter_secret, evento_id, candidato_id)
                logger.info(f"Generated commitment: {commitment[:10]}... for voter {votante_id}")
        except Exception as e:
            logger.exception(f"Failed to generate commitment: {str(e)}")
            return JsonResponse({"success": False, "error": "Error generating vote commitment."}, status=400)

        # Try to send vote to blockchain first; only create DB record if on-chain submission succeeds
        try:
            from django.db import transaction
            from .web3_utils import create_voting_blockchain

            # Initialize blockchain connection (may raise ValueError if not configured)
            blockchain = create_voting_blockchain()

            # Ensure we have a commitment to work with
            if not commitment:
                logger.warning("No commitment generated for voter; aborting vote")
                return JsonResponse({"success": False, "error": "No commitment available."}, status=400)

            try:
                # First, check if the commitment already exists on-chain to avoid revert
                exists, existing_block = blockchain.verify_commitment_onchain(commitment)
                if exists:
                    # Record the vote as already-onchain (avoid sending tx)
                    from django.db import transaction
                    # attempt to fetch sender address if available
                    try:
                        sender_addr = blockchain.contract.functions.getCommitmentSender(commitment).call()
                    except Exception:
                        sender_addr = None

                    with transaction.atomic():
                        voto = Voto.objects.create(
                            evento_id=evento_id,
                            persona_candidato_id=candidato_id,
                            persona_votante_id=votante_id,
                            commitment=commitment,
                            onchain_status='exists',
                            tx_hash=None,
                            commitment_sender=sender_addr,
                            block_number=existing_block
                        )

                    logger.info(f"Commitment already on-chain (block {existing_block}); created Voto {voto.id} with status 'exists'. sender={sender_addr}")
                    return JsonResponse({"success": True, "vote_id": voto.id, "onchain_status": "exists", "commitment_sender": sender_addr})

                # Not on-chain yet: send commitment to chain and wait for receipt
                result = blockchain.send_commitment_to_chain(commitment, wait_for_receipt=True)

                # If transaction indicates failure, check again if commitment appeared (race) else report error
                if result.get('status') != 'success':
                    logger.error(f"On-chain transaction failed: status={result.get('status')}, tx_hash={result.get('tx_hash')}, block_number={result.get('block_number')}")

                    # Re-check on-chain in case the transaction reverted because commitment already exists
                    exists_after, block_after = blockchain.verify_commitment_onchain(commitment)
                    if exists_after:
                        try:
                            sender_addr = blockchain.contract.functions.getCommitmentSender(commitment).call()
                        except Exception:
                            sender_addr = None

                        with transaction.atomic():
                            voto = Voto.objects.create(
                                evento_id=evento_id,
                                persona_candidato_id=candidato_id,
                                persona_votante_id=votante_id,
                                commitment=commitment,
                                onchain_status='exists',
                                tx_hash=result.get('tx_hash'),
                                commitment_sender=sender_addr,
                                block_number=block_after
                            )
                        logger.info(f"Commitment appeared on-chain after failed tx; created Voto {voto.id} with status 'exists'. sender={sender_addr}")
                        return JsonResponse({"success": True, "vote_id": voto.id, "onchain_status": "exists", "commitment_sender": sender_addr})

                    # Otherwise, create DB record with 'failed' status
                    with transaction.atomic():
                        voto = Voto.objects.create(
                            evento_id=evento_id,
                            persona_candidato_id=candidato_id,
                            persona_votante_id=votante_id,
                            commitment=commitment,
                            onchain_status='failed',
                            tx_hash=result.get('tx_hash'),
                            commitment_sender=None,
                            block_number=result.get('block_number')
                        )
                    logger.error(f"Failed to send commitment to blockchain: {result}. Created Voto {voto.id} with status 'failed'")
                    return JsonResponse({"success": False, "error": "On-chain transaction failed.", "vote_id": voto.id}, status=500)

                # Persist the vote only after successful on-chain inclusion
                # Get the sender address from the blockchain
                try:
                    sender_addr = blockchain.contract.functions.getCommitmentSender(commitment).call()
                except Exception as e:
                    logger.warning(f"Could not retrieve commitment sender: {e}")
                    sender_addr = blockchain.get_account_address()
                
                from django.db import transaction
                with transaction.atomic():
                    voto = Voto.objects.create(
                        evento_id=evento_id,
                        persona_candidato_id=candidato_id,
                        persona_votante_id=votante_id,
                        commitment=commitment,
                        onchain_status='success',
                        tx_hash=result.get('tx_hash'),
                        commitment_sender=sender_addr,
                        block_number=result.get('block_number')
                    )

            except Exception as e:
                logger.exception(f"Failed to send commitment to blockchain: {str(e)}")
                return JsonResponse({"success": False, "error": "Error sending vote to blockchain."}, status=500)

            logger.info(f"Vote {voto.id} created after successful on-chain tx {result.get('tx_hash')}")
            return JsonResponse({"success": True, "vote_id": voto.id, "onchain_status": voto.onchain_status})

        except ValueError as e:
            # Blockchain not configured: fall back to simulated behavior and still record vote
            try:
                from django.db import transaction
                import uuid

                with transaction.atomic():
                    voto = Voto.objects.create(
                        evento_id=evento_id,
                        persona_candidato_id=candidato_id,
                        persona_votante_id=votante_id,
                        commitment=commitment,
                        onchain_status='simulated',
                        tx_hash=f"0x{uuid.uuid4().hex[:32]}",
                        block_number=999999
                    )

                logger.info(f"Vote {voto.id} recorded in simulated mode (blockchain not configured)")
                return JsonResponse({"success": True, "vote_id": voto.id, "simulated": True})

            except Exception as ex:
                logger.exception("Failed to create simulated vote record")
                return JsonResponse({"success": False, "error": "Error creating vote in simulated mode."}, status=500)

        except Exception as e:
            logger.exception("Failed to send commitment to blockchain; vote not recorded")
            return JsonResponse({"success": False, "error": "Error sending vote to blockchain."}, status=500)

    return render(request, "votar_evento.html", {
        "evento": evento,
        "candidatos": candidatos
    })

@requiere_votante_sesion
def panel_usuario(request):
    votante_id = request.session.get("votante_id")

    # Retrieve only the fields we need for the persona to avoid instantiating
    # a full model which may trigger datetime conversions from the DB driver.
    persona_data = Persona.objects.filter(id=votante_id).values('id', 'nombre', 'foto_url').first()
    if not persona_data:
        # Keep the same behavior as get_object_or_404 when persona not found
        from django.http import Http404
        raise Http404("Persona no encontrada")

    # Load eventos but be defensive: some DB drivers may return DATETIME as
    # strings. Normalize to Python datetimes so template date filters work.
    eventos_raw = list(EventoEleccion.objects.filter(activo=True).values('id', 'nombre', 'fecha_inicio', 'fecha_termino'))
    from datetime import datetime

    eventos = []
    for ev in eventos_raw:
        fi = ev.get('fecha_inicio')
        ft = ev.get('fecha_termino')
        # If the driver returned strings, parse them to datetimes
        if isinstance(fi, str):
            try:
                fi = datetime.fromisoformat(fi)
            except Exception:
                try:
                    fi = datetime.strptime(fi, '%Y-%m-%d %H:%M:%S')
                except Exception:
                    fi = None
        if isinstance(ft, str):
            try:
                ft = datetime.fromisoformat(ft)
            except Exception:
                try:
                    ft = datetime.strptime(ft, '%Y-%m-%d %H:%M:%S')
                except Exception:
                    ft = None

        eventos.append({
            'id': ev['id'],
            'nombre': ev['nombre'],
            'fecha_inicio': fi,
            'fecha_termino': ft,
        })

    # Determine which events the persona has already voted in by checking Voto records
    voted_evento_ids = list(Voto.objects.filter(persona_votante_id=votante_id).values_list('evento_id', flat=True).distinct())

    # Build available events (not voted) and history (voted)
    available = [e for e in eventos if e['id'] not in voted_evento_ids]
    history = [e for e in eventos if e['id'] in voted_evento_ids]

    return render(request, "panel_usuario.html", {
        "persona": persona_data,
        "eventos": available,
        "historial": history,
    })



@receiver(pre_save, sender=Persona)
def asignar_clave(sender, instance, **kwargs):
    if instance.es_votante and not instance.clave:
        instance.clave = Persona.generar_clave_robusta()

def login_votante(request):
    form = LoginForm_votante(request.POST or None)
    error = None

    if request.method == "POST" and form.is_valid():
        rut = form.cleaned_data["rut"]
        clave = form.cleaned_data["clave"]

        # Use values() to avoid instantiating full model objects (and
        # therefore avoid converting DateTime fields which some DB drivers
        # may return as strings and cause timezone.make_aware errors).
        persona_data = Persona.objects.filter(rut=rut, clave=clave, es_votante=True).values('id', 'nombre').first()

        if persona_data:
            request.session["votante_id"] = str(persona_data['id'])
            messages.success(request, "Ingreso exitoso.")
            return redirect("panel_usuario")
        else:
            error = "RUT o clave incorrectos"

    return render(request, "login_votante.html", {"form": form, "error": error})


def logout_view(request):
    # cierra sesión Django (para admin)
    from django.contrib.auth import logout
    logout(request)
    # limpia sesión de votante
    request.session.pop("votante_id", None)
    return redirect('login_votante')


def panel_admin(request):
    filtro = request.GET.get('filtro', 'todos')
    ahora = timezone.now()

    if filtro == 'curso':
        eventos = EventoEleccion.objects.filter(activo=True, fecha_inicio__lte=ahora, fecha_termino__gte=ahora)
    elif filtro == 'futuro':
        eventos = EventoEleccion.objects.filter(activo=True, fecha_inicio__gt=ahora)
    elif filtro == 'terminado':
        eventos = EventoEleccion.objects.filter(activo=True, fecha_termino__lt=ahora)
    else:  # filtro == 'todos'
        eventos = EventoEleccion.objects.all()  # ← incluye activos e inactivos

    return render(request, 'admin_panel.html', {'eventos': eventos, 'filtro': filtro})



def login_admin(request):
    if request.user.is_authenticated:
        if request.user.is_staff:
            return redirect('panel_admin')
        else:
            return redirect('panel_usuario')  # 👉 si es votante, mándalo a su panel

    error = None
    form = LoginForm(request.POST or None)

    if request.method == 'POST' and form.is_valid():
        username = form.cleaned_data['username']
        password = form.cleaned_data['password']
        user = authenticate(request, username=username, password=password)

        if user is not None and user.is_staff:
            login(request, user)
            return redirect('panel_admin')
        else:
            error = 'Credenciales inválidas o usuario no autorizado.'

    return render(request, 'login.html', {'form': form, 'error': error})


@login_required
@user_passes_test(lambda u: u.is_staff)
def crear_candidato(request):
    if request.method == 'POST':
        form = CandidatoForm(request.POST)
        if form.is_valid():
            persona_id = form.cleaned_data['persona_id']
            print("🧪 ID recibido:", persona_id)

            # Buscar directamente como string
            persona = Persona.objects.filter(id=persona_id).first()
            if not persona:
                print("❌ No se encontró el votante en la base de datos.")
                messages.error(request, 'El votante seleccionado no existe o ya no está disponible.')
                return render(request, 'crear_candidato.html', {'form': form})

            if not persona.es_votante or persona.es_candidato:
                print("⚠️ El votante ya no está disponible para ser candidato.")
                messages.error(request, 'El votante ya no está disponible para ser candidato.')
                return render(request, 'crear_candidato.html', {'form': form})

            persona.es_candidato = True
            persona.save()
            print("✅ Votante actualizado como candidato:", persona.nombre)
            messages.success(request, f'{persona.nombre} ahora es candidato.')
            return redirect('panel_admin')
        else:
            print("❌ Formulario inválido:", form.errors)
            messages.error(request, 'Hubo un error al procesar el formulario.')
    else:
        form = CandidatoForm()

    return render(request, 'crear_candidato.html', {'form': form})


@login_required
@user_passes_test(lambda u: u.is_staff)
def editar_candidato(request, persona_id):
    persona = get_object_or_404(Persona, id=persona_id)
    if request.method == 'POST':
        form = EditarPersonaForm(request.POST, instance=persona)
        if form.is_valid():
            form.save()
            messages.success(request, f'{persona.nombre} actualizado correctamente.')
            return redirect('panel_admin')
    else:
        form = EditarPersonaForm(instance=persona)
    return render(request, 'editar_candidato.html', {'form': form, 'persona': persona})


@login_required
@user_passes_test(lambda u: u.is_staff)
def desactivar_candidato(request, persona_id):
    persona = get_object_or_404(Persona, id=persona_id)
    if request.method == 'POST':
        persona.es_candidato = False
        persona.save()
        messages.success(request, f'{persona.nombre} ha sido desactivado como candidato.')
        return redirect('panel_admin')
    return render(request, 'desactivar_candidato.html', {'persona': persona})


@login_required
@user_passes_test(lambda u: u.is_staff)
def crear_evento(request):
    if request.method == 'POST':
        form = EventoEleccionForm(request.POST)
        if form.is_valid():
            evento = form.save(commit=False)
            # Ensure there is an Administrador instance; if none, create one from the current user
            admin = Administrador.objects.first()
            if not admin:
                persona_admin = Persona.objects.create(
                    nombre=(request.user.get_full_name() or request.user.username),
                    email=(getattr(request.user, 'email', f'user{request.user.id}@local')),
                    rut=str(request.user.id),
                    password_hash=''
                )
                admin = Administrador.objects.create(persona=persona_admin)

            evento.administrador = admin
            evento.id_administrador = str(request.user.id)
            evento.save()
            messages.success(request, f'Evento "{evento.nombre}" creado exitosamente.')
            return redirect('panel_admin')
    else:
        form = EventoEleccionForm()
    return render(request, 'crear_evento.html', {'form': form})

@login_required
@user_passes_test(lambda u: u.is_staff)
def asignar_candidatos(request, evento_id):
    try:
        evento = get_object_or_404(EventoEleccion, id=evento_id)
    except:
        evento = get_object_or_404(EventoEleccion, id=str(evento_id))
    # Only select the fields we need to avoid forcing conversion of datetime
    # fields at the DB driver level (which may return strings in some setups).
    votantes_qs = Persona.objects.filter(es_votante=True).order_by('nombre').values('id', 'nombre', 'email', 'es_candidato')

    paginator = Paginator(list(votantes_qs), 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    if request.method == 'POST':
        ids_str = request.POST.get('candidatos_globales', '')
        seleccionados = [s for s in ids_str.split(',') if s] if ids_str else []

        Candidatura.objects.filter(evento=evento).delete()

        for persona_id in seleccionados:
            Candidatura.objects.create(
                evento=evento,
                persona_id=persona_id
            )

        messages.success(request, 'Candidatos actualizados correctamente.')
        return redirect('panel_admin')

    candidatos_actuales = list(Candidatura.objects.filter(evento=evento).values_list('persona_id', flat=True))

    return render(request, 'asignar_candidatos.html', {
        'evento': evento,
        'page_obj': page_obj,
        'candidatos_actuales': candidatos_actuales
    })

@login_required
@user_passes_test(lambda u: u.is_staff)
def ver_evento(request, evento_id):
    # Load only needed event fields and normalize datetimes to avoid
    # DB-driver datetime->string conversion issues.
    ev = EventoEleccion.objects.filter(id=evento_id).values('id', 'nombre', 'fecha_inicio', 'fecha_termino').first()
    if not ev:
        from django.http import Http404
        raise Http404('Evento no encontrado')

    from datetime import datetime
    fi = ev.get('fecha_inicio')
    ft = ev.get('fecha_termino')
    if isinstance(fi, str):
        try:
            fi = datetime.fromisoformat(fi)
        except Exception:
            try:
                fi = datetime.strptime(fi, '%Y-%m-%d %H:%M:%S')
            except Exception:
                fi = None
    if isinstance(ft, str):
        try:
            ft = datetime.fromisoformat(ft)
        except Exception:
            try:
                ft = datetime.strptime(ft, '%Y-%m-%d %H:%M:%S')
            except Exception:
                ft = None

    # compute estado similar to EventoEleccion.estado property
    ahora = timezone.now()
    estado = 'Desconocido'
    try:
        if fi is not None and ft is not None:
            if fi <= ahora <= ft:
                estado = 'En curso'
            elif ahora < fi:
                estado = 'Futuro'
            else:
                estado = 'Terminado'
    except Exception:
        estado = 'Desconocido'

    evento = {
        'id': ev['id'],
        'nombre': ev['nombre'],
        'fecha_inicio': fi,
        'fecha_termino': ft,
        'estado': estado,
    }

    # Build candidatos as lightweight dicts including fecha_registro
    candidatos_qs = Candidatura.objects.filter(evento_id=evento_id).values('persona__id', 'persona__nombre', 'persona__foto_url', 'fecha_registro')
    candidatos = []
    for c in candidatos_qs:
        fr = c.get('fecha_registro')
        if isinstance(fr, str):
            try:
                fr = datetime.fromisoformat(fr)
            except Exception:
                try:
                    fr = datetime.strptime(fr, '%Y-%m-%d %H:%M:%S')
                except Exception:
                    fr = None
        candidatos.append({
            'persona': {
                'id': c.get('persona__id'),
                'nombre': c.get('persona__nombre'),
                'foto_url': c.get('persona__foto_url'),
            },
            'fecha_registro': fr,
        })

    return render(request, 'ver_evento.html', {
        'evento': evento,
        'candidatos': candidatos
    })


@requiere_votante_sesion
def resultados_evento(request, evento_id):
    # Aggregate votes per candidate for the given event
    from .models import Voto, Persona
    qs = Voto.objects.filter(evento_id=evento_id).values('persona_candidato__id', 'persona_candidato__nombre').annotate(votos=Count('id')).order_by('-votos')

    resultados = []
    for r in qs:
        resultados.append({
            'persona_id': r.get('persona_candidato__id'),
            'nombre': r.get('persona_candidato__nombre'),
            'votos': r.get('votos')
        })

    return render(request, 'resultados_evento.html', {
        'evento_id': evento_id,
        'resultados': resultados
    })


@requiere_votante_sesion
def voto_confirmado(request, evento_id):
    # Simple confirmation page after voting
    return render(request, 'voto_confirmado.html', {
        'evento_id': evento_id,
    })


@requiere_votante_sesion
def voto_status(request, evento_id):
    """API endpoint: retorna el estado del último voto del votante para el evento.
    Devuelve JSON: { status, tx_hash, block_number }
    """
    from .models import Voto

    votante_id = request.session.get('votante_id')
    if not votante_id:
        return JsonResponse({'error': 'no_votante_session'}, status=400)

    voto = Voto.objects.filter(evento_id=evento_id, persona_votante_id=votante_id).order_by('-time_stamp').first()
    if not voto:
        return JsonResponse({'status': 'not_found'})

    return JsonResponse({
        'status': voto.onchain_status or 'pending',
        'tx_hash': voto.tx_hash or None,
        'block_number': voto.block_number or None,
        'commitment_sender': getattr(voto, 'commitment_sender', None)
    })

@login_required
@user_passes_test(lambda u: u.is_staff)
def desactivar_evento(request, evento_id):
    evento = get_object_or_404(EventoEleccion, id=evento_id)
    if request.method == 'POST':
        evento.activo = False
        evento.save()
        messages.success(request, f'Evento "{evento.nombre}" ha sido desactivado.')
        return redirect('panel_admin')
    return render(request, 'desactivar_evento.html', {'evento': evento})


@login_required
@user_passes_test(lambda u: u.is_staff)
def activar_evento(request, evento_id):
    evento = get_object_or_404(EventoEleccion, id=evento_id)
    if request.method == 'POST':
        evento.activo = True
        evento.save()
        messages.success(request, f'Evento "{evento.nombre}" ha sido activado.')
        return redirect('panel_admin')
    return render(request, 'activar_evento.html', {'evento': evento})


from django.views.decorators.csrf import csrf_exempt
from .models import Voto

@csrf_exempt
def check_vote_status(request, vote_id):
    try:
        voto = Voto.objects.get(id=vote_id)
        return JsonResponse({"status": voto.onchain_status})
    except Voto.DoesNotExist:
        return JsonResponse({"error": "Vote not found"}, status=404)
