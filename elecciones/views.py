from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.http import JsonResponse
from .models import Persona, EventoEleccion, Candidatura, Administrador, ParticipacionEleccion, Voto
from .forms import LoginForm, CandidatoForm, EditarPersonaForm, EventoEleccionForm, LoginForm_votante, AgregarUsuarioForm, EditarUsuarioForm
import uuid
import logging
from django.utils import timezone
from django.core.paginator import Paginator
from django.db.models.signals import pre_save
from django.dispatch import receiver
from .utils import requiere_votante_sesion
from uuid import UUID
from django.db.models import Count

logger = logging.getLogger(__name__)
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

    # Obtener candidatos usando consulta SQL directa para evitar problemas datetime
    try:
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT p.id, p.nombre, p.foto
                FROM elecciones_persona p
                INNER JOIN elecciones_candidatura c ON p.id = c.persona_id
                WHERE c.evento_id = %s
                ORDER BY p.nombre
            """, [evento_id])
            candidatos_raw = cursor.fetchall()
            
        candidatos = []
        for candidato_row in candidatos_raw:
            candidatos.append({
                'persona': {
                    'id': candidato_row[0],
                    'nombre': candidato_row[1],
                    'foto_display_url': candidato_row[2] if candidato_row[2] else None
                }
            })
    except Exception as e:
        candidatos = []
        logger.exception(f"Error obteniendo candidatos para votación en evento {evento_id}")

    if request.method == "POST":
        candidato_id = request.POST.get("candidato")
        from .models import Voto, ParticipacionEleccion, Persona
        
        # Get votante_id first (required for all subsequent operations)
        votante_id = request.session.get('votante_id')
        if not votante_id:
            logger.error("No votante_id in session")
            messages.error(request, "Tu sesión ha expirado. Por favor, inicia sesión nuevamente.")
            return redirect('login_votante')
        
        # Check if user has already voted in this event
        existing_vote = Voto.objects.filter(evento_id=evento_id, persona_votante_id=votante_id).first()
        if existing_vote:
            logger.warning(f"User {votante_id} attempted to vote again in event {evento_id}")
            messages.warning(request, "Ya has votado en este evento. No puedes votar más de una vez.")
            return redirect('panel_usuario')
        
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
            messages.error(request, "Error al generar el compromiso del voto. Por favor, intenta nuevamente.")
            return redirect('panel_usuario')

        # Try to send vote to blockchain first; only create DB record if on-chain submission succeeds
        try:
            from django.db import transaction
            from .web3_utils import create_voting_blockchain

            # Initialize blockchain connection (may raise ValueError if not configured)
            blockchain = create_voting_blockchain()

            # Ensure we have a commitment to work with
            if not commitment:
                logger.warning("No commitment generated for voter; aborting vote")
                messages.error(request, "No se pudo generar el compromiso del voto.")
                return redirect('panel_usuario')

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
                    return redirect('voto_confirmado', evento_id=evento_id)

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
                        return redirect('voto_confirmado', evento_id=evento_id)

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
                    return redirect('voto_confirmado', evento_id=evento_id)

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
                messages.error(request, "Error al enviar el voto al blockchain.")
                return redirect('panel_usuario')

            logger.info(f"Vote {voto.id} created after successful on-chain tx {result.get('tx_hash')}")
            return redirect('voto_confirmado', evento_id=evento_id)

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
                return redirect('voto_confirmado', evento_id=evento_id)

            except Exception as ex:
                logger.exception("Failed to create simulated vote record")
                messages.error(request, "Error al crear el registro del voto en modo simulado.")
                return redirect('panel_usuario')

        except Exception as e:
            logger.exception("Failed to send commitment to blockchain; vote not recorded")
            messages.error(request, "Error al enviar el voto al blockchain.")
            return redirect('panel_usuario')

    return render(request, "votar_evento.html", {
        "evento": evento,
        "candidatos": candidatos
    })

@requiere_votante_sesion
def panel_usuario(request):
    votante_id = request.session.get("votante_id")

    # Retrieve only the fields we need for the persona to avoid instantiating
    # a full model which may trigger datetime conversions from the DB driver.
    persona_data = Persona.objects.filter(id=votante_id).values('id', 'nombre', 'foto').first()
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
    
    # Simplificar para evitar problemas datetime - mostrar todos los eventos por ahora
    # TODO: Implementar filtros cuando se resuelvan los problemas datetime
    try:
        # Obtener eventos con consulta SQL directa para evitar conversión datetime
        from django.db import connection
        
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT id, nombre, activo, fecha_inicio, fecha_termino 
                FROM elecciones_eventoeleccion 
                ORDER BY nombre
            """)
            eventos_raw = cursor.fetchall()
            
        # Crear objetos evento simplificados
        eventos = []
        for evento_row in eventos_raw:
            class EventoSimple:
                def __init__(self, evento_id, nombre, activo, fecha_inicio, fecha_termino):
                    self.id = evento_id
                    self.nombre = nombre
                    self.activo = activo
                    self.fecha_inicio = fecha_inicio
                    self.fecha_termino = fecha_termino
            
            eventos.append(EventoSimple(evento_row[0], evento_row[1], evento_row[2], evento_row[3], evento_row[4]))

        # Agregar estadísticas para cada evento
        eventos_con_stats = []
        for evento in eventos:
            participantes_count = ParticipacionEleccion.objects.filter(evento_id=evento.id).count()
            candidatos_count = Candidatura.objects.filter(evento_id=evento.id).count()
            eventos_con_stats.append({
                'evento': evento,
                'participantes_count': participantes_count,
                'candidatos_count': candidatos_count,
                'configuracion_completa': participantes_count > 0 and candidatos_count > 0
            })

    except Exception as e:
        # Fallback en caso de error
        eventos = []
        eventos_con_stats = []

    # Estadísticas básicas
    try:
        total_votantes = Persona.objects.filter(es_votante=True).count()
        total_candidatos = Persona.objects.filter(es_candidato=True).count()
        total_candidaturas = Candidatura.objects.count()
    except Exception:
        total_votantes = 0
        total_candidatos = 0
        total_candidaturas = 0

    return render(request, 'admin_panel.html', {
        'eventos': eventos, 
        'eventos_con_stats': eventos_con_stats,
        'filtro': filtro,
        'total_votantes': total_votantes,
        'total_candidatos': total_candidatos,
        'total_candidaturas': total_candidaturas
    })



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
    
    # NUEVA LÓGICA: Solo mostrar participantes del evento, no todos los votantes
    participantes_ids = ParticipacionEleccion.objects.filter(evento=evento).values_list('persona_id', flat=True)
    
    if not participantes_ids.exists():
        messages.warning(request, f'Este evento no tiene participantes asignados. Primero debe asignar participantes.')
        return redirect('asignar_participantes', evento_id=evento_id)
    
    # Solo seleccionar participantes del evento
    votantes_qs = Persona.objects.filter(
        id__in=participantes_ids,
        es_votante=True
    ).order_by('nombre').values('id', 'nombre', 'email', 'es_candidato')

    paginator = Paginator(list(votantes_qs), 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    if request.method == 'POST':
        ids_str = request.POST.get('candidatos_globales', '')
        seleccionados = [s for s in ids_str.split(',') if s] if ids_str else []

        # Validar que todos los candidatos seleccionados sean participantes del evento
        participantes_ids = set(ParticipacionEleccion.objects.filter(evento=evento).values_list('persona_id', flat=True))
        candidatos_invalidos = [c for c in seleccionados if c not in [str(p) for p in participantes_ids]]
        
        if candidatos_invalidos:
            messages.error(request, 'Solo se pueden asignar como candidatos a personas que ya son participantes del evento.')
            return redirect('asignar_candidatos', evento_id=evento_id)
        
        # Obtener candidatos anteriores para actualizar su estado
        candidatos_anteriores = list(Candidatura.objects.filter(evento=evento).values_list('persona_id', flat=True))
        
        # Eliminar candidaturas anteriores
        Candidatura.objects.filter(evento=evento).delete()

        # Crear nuevas candidaturas
        for persona_id in seleccionados:
            Candidatura.objects.create(
                evento=evento,
                persona_id=persona_id
            )

        # Actualizar estado es_candidato de personas
        # Remover estado de candidato de personas que ya no son candidatos en ningún evento
        personas_a_desmarcar = set(candidatos_anteriores) - set(seleccionados)
        for persona_id in personas_a_desmarcar:
            # Verificar si la persona sigue siendo candidato en otros eventos
            tiene_otras_candidaturas = Candidatura.objects.filter(persona_id=persona_id).exists()
            if not tiene_otras_candidaturas:
                Persona.objects.filter(id=persona_id).update(es_candidato=False)

        # Marcar como candidato a las nuevas personas seleccionadas
        if seleccionados:
            Persona.objects.filter(id__in=seleccionados).update(es_candidato=True)

        messages.success(request, f'Candidatos actualizados correctamente. {len(seleccionados)} candidatos asignados.')
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
    """Vista completa para ver detalles del evento con participantes, candidatos y estadísticas"""
    try:
        # Obtener evento usando valores específicos para evitar problemas datetime
        evento_data = EventoEleccion.objects.filter(id=evento_id).values(
            'id', 'nombre', 'fecha_inicio', 'fecha_termino', 'activo'
        ).first()
        
        if not evento_data:
            messages.error(request, "Evento no encontrado")
            return redirect('panel_admin')

        # Calcular estado del evento
        ahora = timezone.now()
        fi = evento_data['fecha_inicio']
        ft = evento_data['fecha_termino']
        
        if fi <= ahora <= ft:
            estado = 'En curso'
        elif ahora < fi:
            estado = 'Futuro'
        else:
            estado = 'Terminado'

        # Crear objeto evento para el template
        evento = {
            'id': evento_data['id'],
            'nombre': evento_data['nombre'],
            'fecha_inicio': fi,
            'fecha_termino': ft,
            'estado': estado,
            'activo': evento_data['activo']
        }

        # Obtener participantes del evento usando consulta SQL directa
        try:
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT p.id, p.nombre, p.email, p.foto, pe.ha_votado
                    FROM elecciones_persona p
                    INNER JOIN elecciones_participacioneleccion pe ON p.id = pe.persona_id
                    WHERE pe.evento_id = %s
                    ORDER BY p.nombre
                """, [evento_id])
                participantes_raw = cursor.fetchall()
                
            participantes = []
            for part_row in participantes_raw:
                participantes.append({
                    'persona__id': part_row[0],
                    'persona__nombre': part_row[1],
                    'persona__email': part_row[2],
                    'persona__foto_url': part_row[3],  # Ahora directamente el campo foto
                    'ha_votado': part_row[4]
                })
        except Exception as e:
            participantes = []
            logger.exception(f"Error obteniendo participantes para evento {evento_id}")

        # Obtener candidatos del evento con información extendida usando consulta SQL directa
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT p.id, p.nombre, p.email, p.foto
                    FROM elecciones_persona p
                    INNER JOIN elecciones_candidatura c ON p.id = c.persona_id
                    WHERE c.evento_id = %s
                    ORDER BY p.nombre
                """, [evento_id])
                candidatos_raw = cursor.fetchall()
                
            candidatos = []
            for candidato_row in candidatos_raw:
                # Contar votos recibidos por este candidato en este evento usando SQL directo
                try:
                    with connection.cursor() as cursor:
                        cursor.execute("""
                            SELECT COUNT(*) FROM elecciones_voto 
                            WHERE evento_id = %s AND persona_candidato_id = %s
                        """, [evento_id, candidato_row[0]])
                        votos_recibidos = cursor.fetchone()[0]
                except Exception:
                    votos_recibidos = 0

                candidatos.append({
                    'persona': {
                        'id': candidato_row[0],
                        'nombre': candidato_row[1],
                        'email': candidato_row[2],
                        'foto_display_url': candidato_row[3]  # Directamente el campo foto
                    },
                    'fecha_registro': None,  # No mostrar fecha por problemas datetime
                    'votos_recibidos': votos_recibidos
                })
        except Exception as e:
            candidatos = []
            logger.exception(f"Error obteniendo candidatos para evento {evento_id}")

        # Calcular estadísticas usando SQL directo
        participantes_count = len(list(participantes))
        candidatos_count = len(candidatos)
        
        # Contar votos y participantes que votaron usando SQL directo
        try:
            with connection.cursor() as cursor:
                # Contar votos totales
                cursor.execute("""
                    SELECT COUNT(*) FROM elecciones_voto WHERE evento_id = %s
                """, [evento_id])
                votos_count = cursor.fetchone()[0]
                
                # Contar participantes que ya votaron
                cursor.execute("""
                    SELECT COUNT(*) FROM elecciones_participacioneleccion 
                    WHERE evento_id = %s AND ha_votado = 1
                """, [evento_id])
                participantes_que_votaron = cursor.fetchone()[0]
        except Exception as e:
            votos_count = 0
            participantes_que_votaron = 0
            logger.exception(f"Error obteniendo estadísticas para evento {evento_id}")
        
        # Calcular porcentaje de participación
        if participantes_count > 0:
            participacion_porcentaje = (participantes_que_votaron / participantes_count) * 100
        else:
            participacion_porcentaje = 0

        return render(request, 'ver_evento.html', {
            'evento': evento,
            'participantes': participantes,
            'candidatos': candidatos,
            'participantes_count': participantes_count,
            'candidatos_count': candidatos_count,
            'votos_count': votos_count,
            'participacion_porcentaje': participacion_porcentaje,
        })

    except Exception as e:
        logger.exception(f"Error al mostrar evento {evento_id}")
        messages.error(request, f"Error al cargar evento: {str(e)}")
        return redirect('panel_admin')


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


@login_required
@user_passes_test(lambda u: getattr(u, 'is_superuser', False) or Administrador.objects.filter(persona__email=u.email).exists())
def agregar_usuario(request):
    """Vista para agregar nuevos usuarios desde el panel de admin"""
    if request.method == "POST":
        form = AgregarUsuarioForm(request.POST, request.FILES)
        
        if form.is_valid():
            # Generar clave automáticamente (3 letras + 3 números combinados)
            import random, string
            def generar_clave_personalizada():
                """Genera clave de 6 caracteres: 3 letras y 3 números combinados aleatoriamente"""
                letras = [random.choice(string.ascii_lowercase) for _ in range(3)]
                numeros = [random.choice(string.digits) for _ in range(3)]
                caracteres = letras + numeros
                random.shuffle(caracteres)  # Mezclar letras y números
                return ''.join(caracteres)
            
            clave_generada = generar_clave_personalizada()
            
            # Crear persona
            try:
                persona = form.save(commit=False)
                persona.clave = clave_generada
                # Asignar automáticamente como votante
                persona.es_votante = True
                persona.es_candidato = False
                persona.save()
                
                messages.success(request, f'Usuario "{persona.nombre}" creado exitosamente como votante. Clave generada: {clave_generada}')
                return redirect('panel_admin')
                
            except Exception as e:
                messages.error(request, f"Error al crear usuario: {str(e)}")
        else:
            # Mostrar errores del formulario
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
    else:
        form = AgregarUsuarioForm()
    
    return render(request, "agregar_usuario.html", {"form": form})


@login_required
@user_passes_test(lambda u: getattr(u, 'is_superuser', False) or Administrador.objects.filter(persona__email=u.email).exists())
def editar_usuario(request, persona_id):
    """Vista para editar usuarios existentes desde el panel de admin"""
    persona = get_object_or_404(Persona, id=persona_id)
    
    if request.method == "POST":
        form = EditarUsuarioForm(request.POST, request.FILES, instance=persona)
        
        if form.is_valid():
            try:
                persona_actualizada = form.save()
                messages.success(request, f'Usuario "{persona_actualizada.nombre}" actualizado exitosamente.')
                return redirect('panel_admin')
                
            except Exception as e:
                messages.error(request, f"Error al actualizar usuario: {str(e)}")
        else:
            # Mostrar errores del formulario
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
    else:
        form = EditarUsuarioForm(instance=persona)
    
    return render(request, "editar_usuario.html", {"form": form, "persona": persona})


@login_required
@user_passes_test(lambda u: getattr(u, 'is_superuser', False) or Administrador.objects.filter(persona__email=u.email).exists())
def asignar_participantes(request, evento_id):
    """Vista para asignar participantes (votantes) a un evento específico"""
    try:
        # Obtener evento usando valores específicos para evitar problemas de conversión datetime
        evento_data = EventoEleccion.objects.filter(id=evento_id).values(
            'id', 'nombre', 'fecha_inicio', 'fecha_termino', 'activo'
        ).first()
        
        if not evento_data:
            messages.error(request, "Evento no encontrado")
            return redirect('panel_admin')
        
        # Crear objeto evento simplificado para el template
        class EventoSimple:
            def __init__(self, data):
                self.id = data['id']
                self.nombre = data['nombre']
                self.fecha_inicio = data['fecha_inicio']
                self.fecha_termino = data['fecha_termino']
                self.activo = data['activo']
        
        evento = EventoSimple(evento_data)
        # evento_obj no es necesario para operaciones SQL directas
        
    except Exception as e:
        logger.exception(f"Error al obtener evento {evento_id}")
        messages.error(request, f"Error al acceder al evento: {str(e)}")
        return redirect('panel_admin')
    
    if request.method == "POST":
        persona_id = request.POST.get("persona_id")
        action = request.POST.get("action")
        
        try:
            # Verificar que la persona existe y es votante usando SQL directo
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT id, nombre, es_votante 
                    FROM elecciones_persona 
                    WHERE id = %s AND es_votante = 1
                """, [persona_id])
                persona_data = cursor.fetchone()
                
            if not persona_data:
                messages.error(request, "Persona no encontrada o no es votante.")
                return redirect("asignar_participantes", evento_id=evento_id)
            
            persona_id = persona_data[0]
            persona_nombre = persona_data[1]
            
            if action == "add":
                # Convertir UUIDs al formato correcto (sin guiones)
                evento_id_clean = str(evento_id).replace('-', '')
                persona_id_clean = str(persona_id).replace('-', '')
                
                # Verificar si ya existe la participación
                with connection.cursor() as cursor:
                    cursor.execute("""
                        SELECT COUNT(*) FROM elecciones_participacioneleccion 
                        WHERE evento_id = %s AND persona_id = %s
                    """, [evento_id_clean, persona_id_clean])
                    existe = cursor.fetchone()[0] > 0
                
                if not existe:
                    # Agregar participante usando SQL directo
                    import uuid
                    participacion_id = str(uuid.uuid4()).replace('-', '')
                    with connection.cursor() as cursor:
                        cursor.execute("""
                            INSERT INTO elecciones_participacioneleccion (id, evento_id, persona_id, ha_votado)
                            VALUES (%s, %s, %s, 0)
                        """, [participacion_id, evento_id_clean, persona_id_clean])
                    messages.success(request, f"'{persona_nombre}' agregado como participante.")
                else:
                    messages.info(request, f"'{persona_nombre}' ya era participante de este evento.")
                    
            elif action == "remove":
                # Convertir UUIDs al formato correcto (sin guiones)
                evento_id_clean = str(evento_id).replace('-', '')
                persona_id_clean = str(persona_id).replace('-', '')
                
                # Verificar si ha votado antes de remover
                with connection.cursor() as cursor:
                    cursor.execute("""
                        SELECT ha_votado FROM elecciones_participacioneleccion 
                        WHERE evento_id = %s AND persona_id = %s
                    """, [evento_id_clean, persona_id_clean])
                    participacion_data = cursor.fetchone()
                
                if participacion_data:
                    ha_votado = participacion_data[0]
                    if not ha_votado:
                        # Remover participante
                        with connection.cursor() as cursor:
                            cursor.execute("""
                                DELETE FROM elecciones_participacioneleccion 
                                WHERE evento_id = %s AND persona_id = %s
                            """, [evento_id_clean, persona_id_clean])
                        messages.success(request, f"'{persona_nombre}' removido de los participantes.")
                    else:
                        messages.warning(request, f"No se puede remover a '{persona_nombre}' porque ya votó.")
                else:
                    messages.info(request, f"'{persona_nombre}' no era participante de este evento.")
                    
        except Exception as e:
            logger.exception("Error managing participants")
            messages.error(request, f"Error al gestionar participante: {str(e)}")
        
        return redirect("asignar_participantes", evento_id=evento_id)
    
    # GET request - mostrar la página
    # Obtener participantes actuales usando consulta SQL directa
    try:
        from django.db import connection
        
        # Convertir evento_id al formato correcto (sin guiones)
        evento_id_clean = str(evento_id).replace('-', '')
        
        with connection.cursor() as cursor:
            # Obtener participantes del evento
            cursor.execute("""
                SELECT p.id, p.nombre, p.email, pe.ha_votado, p.foto
                FROM elecciones_persona p
                INNER JOIN elecciones_participacioneleccion pe ON p.id = pe.persona_id
                WHERE pe.evento_id = %s
                ORDER BY p.nombre
            """, [evento_id_clean])
            participantes_raw = cursor.fetchall()
            
        participantes_actuales = []
        participantes_ids = []
        
        for part_row in participantes_raw:
            participantes_ids.append(part_row[0])
            participantes_actuales.append({
                'persona__id': part_row[0],
                'persona__nombre': part_row[1],
                'persona__email': part_row[2],
                'ha_votado': part_row[3],
                'persona__foto_url': part_row[4]  # Directamente el campo foto
            })
        
        # Obtener usuarios disponibles (votantes que no son participantes aún)
        with connection.cursor() as cursor:
            if participantes_ids:
                placeholders = ','.join(['%s'] * len(participantes_ids))
                cursor.execute(f"""
                    SELECT id, nombre, email, foto
                    FROM elecciones_persona 
                    WHERE es_votante = 1 AND id NOT IN ({placeholders})
                    ORDER BY nombre
                """, participantes_ids)
            else:
                cursor.execute("""
                    SELECT id, nombre, email, foto
                    FROM elecciones_persona 
                    WHERE es_votante = 1
                    ORDER BY nombre
                """)
            usuarios_raw = cursor.fetchall()
            
        usuarios_disponibles = []
        for user_row in usuarios_raw:
            usuarios_disponibles.append({
                'id': user_row[0],
                'nombre': user_row[1],
                'email': user_row[2],
                'foto_display_url': user_row[3]  # Directamente el campo foto
            })
            
    except Exception as e:
        # Fallback en caso de error
        participantes_actuales = []
        usuarios_disponibles = []
        logger.exception(f"Error obteniendo participantes para evento {evento_id}")
    
    # Contar candidatos actuales del evento usando SQL directo
    try:
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*) FROM elecciones_candidatura 
                WHERE evento_id = %s
            """, [evento_id])
            candidatos_count = cursor.fetchone()[0]
    except Exception:
        candidatos_count = 0
    
    return render(request, "asignar_participantes.html", {
        "evento": evento,
        "participantes_actuales": participantes_actuales,
        "usuarios_disponibles": usuarios_disponibles,
        "candidatos_count": candidatos_count,
    })
