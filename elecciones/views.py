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
from .models import (
    Persona, 
    EventoEleccion, 
    Candidatura, 
    Administrador, 
    ParticipacionEleccion, # <--- ESTE DEBE ESTAR ARRIBA
    Voto
)
from django.utils import timezone
from datetime import datetime
logger = logging.getLogger(__name__)
import os
import logging
from django.views.decorators.csrf import csrf_exempt
from .models import Voto
from django.db import connection

logger = logging.getLogger(__name__)

@requiere_votante_sesion
def votar_evento(request, evento_id):
    # 1. Validar sesión
    votante_id = request.session.get('votante_id')
    if not votante_id:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
             return JsonResponse({'error': 'Sesión expirada'}, status=401)
        messages.error(request, "Tu sesión ha expirado.")
        return redirect('login_votante')
    
    # 2. Seguridad: Verificar lista de invitados
    es_invitado = ParticipacionEleccion.objects.filter(
        evento_id=evento_id, 
        persona_id=votante_id
    ).exists()

    if not es_invitado:
        messages.error(request, f"⛔ No tienes permiso para votar en este evento. Votante ID: {votante_id}, Evento ID: {evento_id}")
        return redirect('panel_usuario')

    # 3. Verificar si ya votó
    ya_voto = Voto.objects.filter(evento_id=evento_id, persona_votante_id=votante_id).exists()
    if ya_voto:
        messages.warning(request, "Ya has votado en este evento.")
        return redirect('panel_usuario')
    
    # 4. Cargar Evento (Lógica anti-errores de driver)
    ev_data = EventoEleccion.objects.filter(id=evento_id).values('id', 'nombre', 'fecha_inicio', 'fecha_termino', 'activo').first()
    if not ev_data:
        from django.http import Http404
        messages.error(request, f"Evento no encontrado. ID: {evento_id}")
        raise Http404("Evento no encontrado")

    # --- NORMALIZACIÓN DE FECHAS ---
    fi = ev_data.get('fecha_inicio')
    ft = ev_data.get('fecha_termino')
    
    # Función auxiliar para limpiar fechas con zona horaria Santiago
    def limpiar_fecha(fecha_sucia):
        if not fecha_sucia: return None
        if isinstance(fecha_sucia, str):
            try: 
                fecha_parsed = datetime.fromisoformat(fecha_sucia)
                if fecha_parsed.tzinfo is None:
                    from zoneinfo import ZoneInfo
                    santiago_tz = ZoneInfo('America/Santiago')
                    fecha_parsed = fecha_parsed.replace(tzinfo=santiago_tz)
                return fecha_parsed
            except:
                try: 
                    fecha_parsed = datetime.strptime(fecha_sucia, '%Y-%m-%d %H:%M:%S')
                    from zoneinfo import ZoneInfo
                    santiago_tz = ZoneInfo('America/Santiago')
                    return fecha_parsed.replace(tzinfo=santiago_tz)
                except: return None
        # Ya es datetime, asegurar zona horaria Santiago
        if fecha_sucia.tzinfo is None:
            from zoneinfo import ZoneInfo
            santiago_tz = ZoneInfo('America/Santiago')
            return fecha_sucia.replace(tzinfo=santiago_tz)
        return fecha_sucia

    start_date = limpiar_fecha(fi)
    end_date = limpiar_fecha(ft)

    # Usar timezone.now() para obtener hora actual con zona horaria de Santiago
    ahora = timezone.now()
    
    # Convertir fechas del evento a la misma zona horaria para comparar
    if start_date and start_date.tzinfo is None:
        from zoneinfo import ZoneInfo
        santiago_tz = ZoneInfo('America/Santiago')
        start_date = start_date.replace(tzinfo=santiago_tz)
    if end_date and end_date.tzinfo is None:
        from zoneinfo import ZoneInfo
        santiago_tz = ZoneInfo('America/Santiago')
        end_date = end_date.replace(tzinfo=santiago_tz)

    # -------------------------------------------------------------------------
    # 🕒 LÓGICA DE TIEMPO: PASADO, FUTURO Y AUTO-CIERRE
    # -------------------------------------------------------------------------
    
    # Caso A: El evento ya terminó (Pasado)
    if end_date and ahora > end_date:
        # 1. Si seguía activo en BD, lo apagamos automáticamente
        if ev_data['activo']:
            EventoEleccion.objects.filter(id=evento_id).update(activo=False)
            logger.info(f"Evento {evento_id} cerrado automáticamente por fecha vencida.")
        
        messages.error(request, "⏳ Este evento ha finalizado. El periodo de votación terminó.")
        return redirect('panel_usuario')

    # Caso B: El evento no ha empezado (Futuro)
    if start_date and ahora < start_date:
        messages.warning(request, f"⏳ Este evento aún no comienza. Vuelve el {start_date}.")
        return redirect('panel_usuario')

    # Caso C: El administrador lo desactivó manualmente, aunque las fechas estén bien
    if not ev_data['activo']:
        messages.error(request, "⛔ Este evento se encuentra desactivado temporalmente.")
        return redirect('panel_usuario')

    # -------------------------------------------------------------------------

    # Preparar objeto para el template
    evento = {
        'id': ev_data['id'],
        'nombre': ev_data['nombre'],
        'fecha_inicio': start_date,
        'fecha_termino': end_date,
    }

    # 5. Cargar Candidatos
    candidatos = []
    try:
        candidaturas_db = Candidatura.objects.filter(evento_id=evento_id).select_related('persona')
        for c in candidaturas_db:
            candidatos.append({
                'persona': {
                    'id': c.persona.id, 
                    'nombre': c.persona.nombre,
                    'foto_display_url': c.persona.foto.url if c.persona.foto else None
                }
            })
    except Exception as e:
        logger.exception(f"Error obteniendo candidatos: {evento_id}")
        candidatos = []

    # 6. Procesar Voto (POST)
    if request.method == "POST":
        candidato_id = request.POST.get("candidato")
        
        # Validar seguridad final antes de guardar
        if not ParticipacionEleccion.objects.filter(evento_id=evento_id, persona_id=votante_id).exists():
             return redirect('panel_usuario')

        # Verificar si ya votó (doble seguridad)
        ya_voto = Voto.objects.filter(evento_id=evento_id, persona_votante_id=votante_id).exists()
        if ya_voto:
            messages.warning(request, "Ya has votado en este evento.")
            return redirect('panel_usuario')

        # PASO 1: Generar commitment
        voter_secret = None
        try:
            votante_obj = Persona.objects.filter(id=votante_id).values('id', 'clave').first()
            if votante_obj: 
                voter_secret = votante_obj.get('clave')
        except Exception as e:
            logger.error(f"Error obteniendo clave del votante: {str(e)}")
            messages.error(request, "Error al procesar tu voto. Intenta nuevamente.")
            return redirect('votar_evento', evento_id=evento_id)

        if not voter_secret:
            messages.error(request, "No se pudo verificar tu identidad. Contacta al administrador.")
            return redirect('panel_usuario')

        commitment = None
        try:
            from .web3_utils import VotingBlockchain
            commitment = VotingBlockchain.generate_commitment(voter_secret, evento_id, candidato_id)
        except Exception as e:
            logger.error(f"Error generando commitment: {str(e)}")
            messages.error(request, "Error al generar el voto. Intenta nuevamente.")
            return redirect('votar_evento', evento_id=evento_id)

        if not commitment:
            messages.error(request, "Error al generar el voto. Intenta nuevamente.")
            return redirect('votar_evento', evento_id=evento_id)

        # PASO 2: Enviar a BLOCKCHAIN PRIMERO (antes de guardar en BD)
        try:
            from .web3_utils import create_voting_blockchain
            blockchain = create_voting_blockchain()
            
            logger.info(f"🔄 Enviando voto a blockchain...")
            result = blockchain.send_commitment_to_chain(commitment, wait_for_receipt=True, timeout=60)
            
            if result.get('status') != 'success':
                logger.error(f"✗ Blockchain rechazó el voto: {result}")
                messages.error(request, "❌ La blockchain rechazó tu voto. Por favor, intenta nuevamente.")
                return redirect('votar_evento', evento_id=evento_id)
            
            logger.info(f"✓ Voto confirmado en blockchain: {result.get('tx_hash')}")
            
            # PASO 3: Solo si blockchain tuvo éxito, guardar en BD
            try:
                from django.db import transaction
                with transaction.atomic():
                    voto = Voto.objects.create(
                        evento_id=evento_id, 
                        persona_candidato_id=candidato_id, 
                        persona_votante_id=votante_id, 
                        commitment=commitment,
                        onchain_status='success',
                        tx_hash=result.get('tx_hash'),
                        block_number=result.get('block_number'),
                        commitment_sender=blockchain.account.address
                    )
                    ParticipacionEleccion.objects.filter(
                        evento_id=evento_id, 
                        persona_id=votante_id
                    ).update(ha_votado=True)
                
                logger.info(f"✓ Voto guardado en BD con éxito")
                messages.success(request, "✅ Tu voto ha sido registrado exitosamente en la blockchain.")
                return redirect('voto_confirmado', evento_id=evento_id)
                
            except Exception as e:
                logger.exception("Error guardando voto en BD después de blockchain exitoso")
                messages.error(request, "⚠️ Tu voto fue registrado en blockchain pero hubo un error en la base de datos. Contacta al administrador.")
                return redirect('panel_usuario')
                
        except Exception as e:
            logger.exception(f"✗ Error enviando voto a blockchain: {str(e)}")
            messages.error(request, f"❌ Error al enviar tu voto a la blockchain: {str(e)}. Por favor, intenta nuevamente.")
            return redirect('votar_evento', evento_id=evento_id)

    return render(request, "votar_evento.html", {
        "evento": evento,
        "candidatos": candidatos
    })

@requiere_votante_sesion
def panel_usuario(request):
    votante_id = request.session.get("votante_id")

    # Obtener datos de la persona
    persona_data = Persona.objects.filter(id=votante_id).values('id', 'nombre', 'foto').first()
    if not persona_data:
        from django.http import Http404
        raise Http404("Persona no encontrada")

    # DEBUG: Información de depuración
    debug_info = {
        'votante_id': votante_id,
        'persona_data': persona_data,
    }

    # -------------------------------------------------------------------------
    # 🔒 CORRECCIÓN PRINCIPAL: FILTRAR POR INVITACIÓN
    # -------------------------------------------------------------------------
    # 1. Buscamos en la tabla 'ParticipacionEleccion' los eventos donde este usuario está invitado.
    eventos_invitados_ids = list(ParticipacionEleccion.objects.filter(
        persona_id=votante_id
    ).values_list('evento_id', flat=True))
    
    debug_info['eventos_invitados_ids'] = eventos_invitados_ids

    # 2. Filtramos la tabla de Eventos usando esos IDs y que estén activos.
    #    (Ya no traemos "todos" los activos, solo los que coinciden)
    eventos_raw = list(EventoEleccion.objects.filter(
        id__in=eventos_invitados_ids, 
        activo=True
    ).values('id', 'nombre', 'fecha_inicio', 'fecha_termino'))
    
    debug_info['eventos_raw_count'] = len(eventos_raw)
    debug_info['eventos_raw'] = eventos_raw
    # -------------------------------------------------------------------------

    from datetime import datetime
    eventos = []
    
    # Normalización de fechas con zona horaria Santiago
    for ev in eventos_raw:
        fi = ev.get('fecha_inicio')
        ft = ev.get('fecha_termino')
        
        # Normalizar fecha_inicio
        if isinstance(fi, str):
            try: fi = datetime.fromisoformat(fi)
            except: 
                try: fi = datetime.strptime(fi, '%Y-%m-%d %H:%M:%S')
                except: fi = None
        if fi and fi.tzinfo is None:
            from zoneinfo import ZoneInfo
            santiago_tz = ZoneInfo('America/Santiago')
            fi = fi.replace(tzinfo=santiago_tz)
            
        # Normalizar fecha_termino
        if isinstance(ft, str):
            try: ft = datetime.fromisoformat(ft)
            except: 
                try: ft = datetime.strptime(ft, '%Y-%m-%d %H:%M:%S')
                except: ft = None
        if ft and ft.tzinfo is None:
            from zoneinfo import ZoneInfo
            santiago_tz = ZoneInfo('America/Santiago')
            ft = ft.replace(tzinfo=santiago_tz)

        eventos.append({
            'id': ev['id'],
            'nombre': ev['nombre'],
            'fecha_inicio': fi,
            'fecha_termino': ft,
        })

    # Filtrar historial vs disponibles
    voted_evento_ids = list(Voto.objects.filter(persona_votante_id=votante_id).values_list('evento_id', flat=True).distinct())
    debug_info['voted_evento_ids'] = voted_evento_ids

    available = [e for e in eventos if e['id'] not in voted_evento_ids]
    history = [e for e in eventos if e['id'] in voted_evento_ids]
    
    debug_info['available_count'] = len(available)
    debug_info['history_count'] = len(history)

    # Agregar información de debug temporalmente
    if request.GET.get('debug') == '1':
        messages.info(request, f"DEBUG INFO: {debug_info}")

    return render(request, "panel_usuario.html", {
        "persona": persona_data,
        "eventos": available,
        "historial": history,
        "debug_info": debug_info if request.GET.get('debug') == '1' else None,
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


def logout_votante(request):
    """Cierra la sesión de votante y redirige a login de votantes"""
    request.session.pop("votante_id", None)
    messages.success(request, "Has cerrado sesión exitosamente.")
    return redirect('login_votante')


class EventoSimple:
    def __init__(self, e_id, nombre, activo, fi, ft):
        self.id = e_id
        self.nombre = nombre
        self.activo = activo
        self.fecha_inicio = fi
        self.fecha_termino = ft

@login_required
@user_passes_test(lambda u: u.is_staff)
def panel_admin(request):
    filtro = request.GET.get('filtro', 'todos')
    
    # 1. Obtener eventos RAW
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT id, nombre, activo, fecha_inicio, fecha_termino 
                FROM elecciones_eventoeleccion 
            """)
            eventos_raw = cursor.fetchall()
    except Exception as e:
        logger.exception("Error SQL")
        eventos_raw = []

    # 2. Preparar fechas y Filtrar
    ahora = timezone.now() # Fecha sistema con zona horaria Santiago
    eventos_filtrados = []

    # Función interna para limpiar fechas con zona horaria Santiago
    def limpiar_fecha(fecha_sucia):
        if not fecha_sucia: return None
        
        if isinstance(fecha_sucia, datetime):
            # Si ya tiene zona horaria, convertir a Santiago
            if fecha_sucia.tzinfo:
                return fecha_sucia.astimezone(timezone.get_current_timezone())
            else:
                # Si no tiene zona horaria, asumir que es Santiago
                from zoneinfo import ZoneInfo
                santiago_tz = ZoneInfo('America/Santiago')
                return fecha_sucia.replace(tzinfo=santiago_tz)
        
        fecha_str = str(fecha_sucia).strip()
        formatos = [
            '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f', 
            '%Y-%m-%d', '%d/%m/%Y %H:%M'
        ]
        for fmt in formatos:
            try: 
                fecha_naive = datetime.strptime(fecha_str, fmt)
                from zoneinfo import ZoneInfo
                santiago_tz = ZoneInfo('America/Santiago')
                return fecha_naive.replace(tzinfo=santiago_tz)
            except ValueError: continue
        try: 
            fecha_naive = datetime.fromisoformat(fecha_str)
            if fecha_naive.tzinfo is None:
                from zoneinfo import ZoneInfo
                santiago_tz = ZoneInfo('America/Santiago')
                return fecha_naive.replace(tzinfo=santiago_tz)
            return fecha_naive
        except: return None

    for row in eventos_raw:
        e_id, nombre, activo, fi_raw, ft_raw = row
        fi = limpiar_fecha(fi_raw)
        ft = limpiar_fecha(ft_raw)
        
        # Instancia del evento simple
        ev = EventoSimple(e_id, nombre, activo, fi, ft)

        # Lógica de Filtrado
        agregar = False
        if not fi or not ft:
            if filtro == 'todos': agregar = True
        else:
            if filtro == 'todos':
                agregar = True
            elif filtro == 'curso':
                if fi <= ahora <= ft: agregar = True
            elif filtro == 'futuro':
                if ahora < fi: agregar = True
            elif filtro == 'terminado':
                if ahora > ft: agregar = True

        if agregar:
            eventos_filtrados.append(ev)

    # 3. Calcular Estadísticas para la lista filtrada
    eventos_con_stats = []
    for evento in eventos_filtrados:
        try:
            participantes_count = ParticipacionEleccion.objects.filter(evento_id=evento.id).count()
            candidatos_count = Candidatura.objects.filter(evento_id=evento.id).count()
            eventos_con_stats.append({
                'evento': evento,
                'participantes_count': participantes_count,
                'candidatos_count': candidatos_count,
                'configuracion_completa': participantes_count > 0 and candidatos_count > 0
            })
        except:
            eventos_con_stats.append({
                'evento': evento, 
                'participantes_count': 0, 
                'candidatos_count': 0, 
                'configuracion_completa': False
            })

    # ==========================================
    # 4. PAGINACIÓN (NUEVO)
    # ==========================================
    # Paginamos la lista final procesada (ej: 10 eventos por página)
    paginator = Paginator(eventos_con_stats, 5) 
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # 5. Stats globales (Contadores de arriba)
    try:
        total_votantes = Persona.objects.filter(es_votante=True).count()
        total_candidatos = Persona.objects.filter(es_candidato=True).count()
        total_candidaturas = Candidatura.objects.count()
    except:
        total_votantes = 0; total_candidatos = 0; total_candidaturas = 0

    return render(request, 'admin_panel.html', {
        # Pasamos el OBJETO PAGINADO en lugar de la lista completa
        'eventos_con_stats': page_obj, 
        'eventos': eventos_filtrados, # Mantenemos esto por si usas el conteo raw en otro lado
        'filtro': filtro,
        'total_votantes': total_votantes,
        'total_candidatos': total_candidatos,
        'total_candidaturas': total_candidaturas,
        'ahora': ahora
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
            try:
                evento = form.save(commit=False)
                # ... (tu lógica de asignar admin sigue igual) ...
                admin = Administrador.objects.first()
                if not admin:
                    # ... creación de admin ...
                    pass 
                
                evento.administrador = admin 
                evento.id_administrador = str(request.user.id)
                evento.save()
                
                messages.success(request, f'Evento "{evento.nombre}" creado exitosamente.')
                return redirect('panel_admin') 
            except Exception as e:
                logger.exception("Error al guardar el evento")
                messages.error(request, f"Error interno al guardar: {e}")
        else:
          
            print("❌ Errores del formulario de evento:", form.errors)
            messages.error(request, "El formulario contiene errores. Por favor, revisa los campos marcados.")
            
           

    else:
        form = EventoEleccionForm()
    
    return render(request, 'crear_evento.html', {'form': form})

@login_required
@user_passes_test(lambda u: u.is_staff)
def asignar_candidatos(request, evento_id):
    # 1. Obtener Evento
    try:
        evento = get_object_or_404(EventoEleccion, id=evento_id)
    except:
        evento = get_object_or_404(EventoEleccion, id=str(evento_id))
    
    # 2. Obtener lista de posibles candidatos (Participantes)
    participantes_ids = ParticipacionEleccion.objects.filter(evento=evento).values_list('persona_id', flat=True)
    
    # --- LÓGICA DE GUARDADO (POST) ---
    if request.method == 'POST':
        # A) INTENTO 1: Buscar string separado por comas (Tu lógica antigua de JS)
        ids_str = request.POST.get('candidatos_globales', '')
        seleccionados = [s for s in ids_str.split(',') if s]
        
        # B) INTENTO 2: Si el anterior falló, buscar checkboxes normales (getlist)
        if not seleccionados:
            seleccionados = request.POST.getlist('candidatos_ids') # <--- Asegúrate que tu input se llame así en HTML
            # O quizás se llama 'persona_ids' en tu template? Probamos ambos:
            if not seleccionados:
                seleccionados = request.POST.getlist('persona_ids')

        print(f"📦 DATOS RECIBIDOS POST: {request.POST}") # MIRA ESTO EN TU CONSOLA
        print(f"✅ CANDIDATOS SELECCIONADOS DETECTADOS: {len(seleccionados)}")

        # C) Guardar en BD
        from django.db import transaction
        try:
            with transaction.atomic():
                # 1. Borrar actuales
                Candidatura.objects.filter(evento=evento).delete()
                
                # 2. Insertar nuevos (solo si son válidos participantes)
                nuevos_objs = []
                # Convertimos IDs de participantes a string para comparar rápido
                participantes_str = [str(uid) for uid in participantes_ids]
                
                for pid in seleccionados:
                    if pid in participantes_str:
                        nuevos_objs.append(Candidatura(evento=evento, persona_id=pid))
                
                Candidatura.objects.bulk_create(nuevos_objs)
                
                # 3. Actualizar flags de Persona (Opcional, según tu lógica de negocio)
                # (Aquí iría tu lógica de es_candidato = True/False si la necesitas)

            messages.success(request, f'Se guardaron {len(nuevos_objs)} candidatos correctamente.')
            
            # 🚨 REDIRECCIÓN EXPLÍCITA
            return redirect('panel_admin')

        except Exception as e:
            logger.exception("Error guardando candidatos")
            messages.error(request, f"Error al guardar: {e}")
            # Si falla, no redirigimos para mostrar el error en la misma página
    
    # --- LÓGICA GET (MOSTRAR PÁGINA) ---
    
    # Candidatos actuales para marcar los checkboxes
    candidatos_actuales = list(Candidatura.objects.filter(evento=evento).values_list('persona_id', flat=True))
    candidatos_actuales = [str(uid) for uid in candidatos_actuales]

    # Lista de votantes disponibles para elegir
    votantes_qs = Persona.objects.filter(
        id__in=participantes_ids,
        es_votante=True
    ).order_by('nombre').values('id', 'nombre', 'email', 'rut')

    # Paginación
    paginator = Paginator(list(votantes_qs), 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

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
        # 1. Obtener datos básicos del evento
        evento_data = EventoEleccion.objects.filter(id=evento_id).values(
            'id', 'nombre', 'fecha_inicio', 'fecha_termino', 'activo'
        ).first()
        
        if not evento_data:
            messages.error(request, "Evento no encontrado")
            return redirect('panel_admin')

        # Calcular estado
        ahora = timezone.now()
        fi = evento_data['fecha_inicio']
        ft = evento_data['fecha_termino']
        
        if fi <= ahora <= ft:
            estado = 'En curso'
        elif ahora < fi:
            estado = 'Futuro'
        else:
            estado = 'Terminado'

        evento = {
            'id': evento_data['id'],
            'nombre': evento_data['nombre'],
            'fecha_inicio': fi,
            'fecha_termino': ft,
            'estado': estado,
            'activo': evento_data['activo']
        }

        # 2. Obtener PARTICIPANTES (SQL Directo)
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT p.id, p.nombre, p.email, p.foto, pe.ha_votado
                    FROM elecciones_persona p
                    INNER JOIN elecciones_participacioneleccion pe ON p.id = pe.persona_id
                    WHERE pe.evento_id = %s
                    ORDER BY p.nombre
                """, [evento_id])
                participantes_raw = cursor.fetchall()
                
            participantes_lista_completa = []
            for part_row in participantes_raw:
                participantes_lista_completa.append({
                    'persona__id': part_row[0],
                    'persona__nombre': part_row[1],
                    'persona__email': part_row[2],
                    'persona__foto_url': part_row[3],
                    'ha_votado': part_row[4]
                })
        except Exception as e:
            participantes_lista_completa = []
            logger.exception(f"Error obteniendo participantes para evento {evento_id}")

        # 3. Obtener CANDIDATOS (SQL Directo)
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT p.id, p.nombre, p.email, p.foto, c.id
                    FROM elecciones_persona p
                    INNER JOIN elecciones_candidatura c ON p.id = c.persona_id
                    WHERE c.evento_id = %s
                    ORDER BY p.nombre
                """, [evento_id])
                candidatos_raw = cursor.fetchall()
                
            candidatos_lista_completa = []
            for candidato_row in candidatos_raw:
                # Contar votos
                try:
                    with connection.cursor() as cursor:
                        cursor.execute("""
                            SELECT COUNT(*) FROM elecciones_voto 
                            WHERE evento_id = %s AND persona_candidato_id = %s
                        """, [evento_id, candidato_row[0]])
                        votos_recibidos = cursor.fetchone()[0]
                except Exception:
                    votos_recibidos = 0

                candidatos_lista_completa.append({
                    'persona': {
                        'id': candidato_row[0],
                        'nombre': candidato_row[1],
                        'email': candidato_row[2],
                        'foto_display_url': candidato_row[3]
                    },
                    'fecha_registro': None,
                    'votos_recibidos': votos_recibidos
                })
        except Exception as e:
            candidatos_lista_completa = []
            logger.exception(f"Error obteniendo candidatos para evento {evento_id}")

        # 4. Calcular estadísticas
        participantes_count = len(participantes_lista_completa)
        candidatos_count = len(candidatos_lista_completa)
        
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM elecciones_voto WHERE evento_id = %s", [evento_id])
                votos_count = cursor.fetchone()[0]
                
                cursor.execute("""
                    SELECT COUNT(*) FROM elecciones_participacioneleccion 
                    WHERE evento_id = %s AND ha_votado = 1
                """, [evento_id])
                participantes_que_votaron = cursor.fetchone()[0]
        except Exception:
            votos_count = 0
            participantes_que_votaron = 0
        
        if participantes_count > 0:
            participacion_porcentaje = (participantes_que_votaron / participantes_count) * 100
        else:
            participacion_porcentaje = 0

        # =========================================================================
        # 5. LÓGICA DE PAGINACIÓN (AQUÍ ESTABA EL ERROR ANTES)
        # =========================================================================
        
        # A. Paginador de Participantes (Usando la lista obtenida por SQL)
        participantes_paginator = Paginator(participantes_lista_completa, 10) # 10 por página
        page_number = request.GET.get('page')
        participantes_page = participantes_paginator.get_page(page_number)
        
        # B. Paginador de Candidatos (Usando la lista obtenida por SQL)
        candidatos_paginator = Paginator(candidatos_lista_completa, 5) # 5 por página
        candidatos_page_number = request.GET.get('candidatos_page')
        candidatos_page = candidatos_paginator.get_page(candidatos_page_number)

        # 6. Renderizar pasando los objetos PAGINADOS ('_page')
        return render(request, 'ver_evento.html', {
            'evento': evento,
            # IMPORTANTE: Pasamos los objetos Page, no las listas completas
            'participantes': participantes_page, 
            'candidatos': candidatos_page,
            
            # Conteos totales
            'participantes_count': participantes_count,
            'candidatos_count': candidatos_count,
            'votos_count': votos_count,
            'participacion_porcentaje': participacion_porcentaje,
        })

    except Exception as e:
        logger.exception(f"Error al mostrar evento {evento_id}")
        messages.error(request, f"Error al cargar evento: {str(e)}")
        return redirect('panel_admin')


@login_required
def resultados_evento(request, evento_id):
    # Validar que la votación haya terminado antes de mostrar resultados
    evento = get_object_or_404(EventoEleccion, id=evento_id)
    ahora = timezone.now()
    
    # Detectar si es admin o votante
    es_admin = request.user.is_staff or Administrador.objects.filter(persona__email=request.user.email).exists()
    
    # Si la votación aún no ha terminado, mostrar alerta y redirigir
    if ahora < evento.fecha_termino:
        messages.warning(request, "Los resultados se mostrarán al terminar la votación.")
        return redirect('panel_admin' if es_admin else 'panel_usuario')
    
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
        'evento': evento,
        'resultados': resultados,
        'es_admin': es_admin
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
    # Usamos get_object_or_404 para asegurarnos que existe
    evento = get_object_or_404(EventoEleccion, id=evento_id)
    
    if request.method == 'POST':
        # 1. Obtener fecha actual y fecha del evento
        ahora = timezone.now()
        
        ft = evento.fecha_termino
        
        # 2. Normalizar fecha del evento a zona horaria Santiago
        if isinstance(ft, str):
            try: ft = datetime.fromisoformat(ft)
            except:
                try: ft = datetime.strptime(ft, '%Y-%m-%d %H:%M:%S')
                except: ft = None
        
        # Asegurar que la fecha tenga zona horaria de Santiago
        if ft and ft.tzinfo is None:
            from zoneinfo import ZoneInfo
            santiago_tz = ZoneInfo('America/Santiago')
            ft = ft.replace(tzinfo=santiago_tz)

        # 3. 🔒 VALIDACIÓN: Si ya pasó la fecha, prohibido activar
        if ft and ahora > ft:
            messages.error(request, f'No se puede activar "{evento.nombre}" porque su fecha de término ya pasó.')
            return redirect('panel_admin')

        # Si todo bien, activar
        evento.activo = True
        evento.save()
        messages.success(request, f'Evento "{evento.nombre}" ha sido activado.')
        return redirect('panel_admin')
        
    return render(request, 'activar_evento.html', {'evento': evento})




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
                
                # Enviar correo con las credenciales
                try:
                    from django.core.mail import send_mail
                    from django.conf import settings
                    
                    asunto = '🔐 Tus Credenciales de Acceso - VotaciónApp'
                    mensaje = f"""
Hola {persona.nombre},

¡Bienvenido/a a VotaciónApp! 🎉

Tu cuenta ha sido creada exitosamente. A continuación, encontrarás tus credenciales de acceso:

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 CREDENCIALES DE ACCESO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🆔 RUT:    {persona.rut}
🔑 Clave:  {clave_generada}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🌐 Para acceder al sistema:
   1. Ingresa a: http://127.0.0.1:8000/login-votante/
   2. Usa tu RUT y la clave proporcionada arriba

⚠️ IMPORTANTE:
   • Guarda esta información en un lugar seguro
   • No compartas tu clave con nadie
   • Tu RUT debe ingresarse sin puntos ni guión

Si tienes algún problema para acceder, contacta al administrador.

¡Gracias por participar!

---
VotaciónApp - Sistema de Votación Segura
                    """
                    
                    email_enviado = send_mail(
                        asunto,
                        mensaje,
                        settings.DEFAULT_FROM_EMAIL if hasattr(settings, 'DEFAULT_FROM_EMAIL') else 'noreply@votacionapp.com',
                        [persona.email],
                        fail_silently=False,
                    )
                    
                    if email_enviado:
                        messages.success(request, f'✅ Usuario "{persona.nombre}" creado exitosamente. Se ha enviado un correo a {persona.email} con las credenciales.')
                    else:
                        messages.warning(request, f'⚠️ Usuario "{persona.nombre}" creado, pero hubo un problema al enviar el correo. Clave generada: {clave_generada}')
                        
                except Exception as e:
                    logger.error(f"Error enviando correo a {persona.email}: {str(e)}")
                    messages.warning(request, f'⚠️ Usuario "{persona.nombre}" creado exitosamente, pero no se pudo enviar el correo. Clave generada: {clave_generada}')
                
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
    """Vista para asignar participantes (votantes) a un evento específico con soporte masivo"""
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
        
    except Exception as e:
        logger.exception(f"Error al obtener evento {evento_id}")
        messages.error(request, f"Error al acceder al evento: {str(e)}")
        return redirect('panel_admin')
    
    # --- LOGICA POST ACTUALIZADA PARA ACCIONES MASIVAS ---
    if request.method == "POST":
        action = request.POST.get("action")
        # Capturamos la lista de IDs (checkboxes)
        persona_ids = request.POST.getlist("persona_ids")
        
        # Compatibilidad: Si viene un ID simple (botón individual), lo convertimos a lista
        if not persona_ids and request.POST.get("persona_id"):
            persona_ids = [request.POST.get("persona_id")]

        if not persona_ids:
            messages.warning(request, "No seleccionaste ningún usuario.")
            return redirect("asignar_participantes", evento_id=evento_id)

        try:
            from django.db import connection
            import uuid
            
            # Limpiar ID del evento para SQL
            evento_id_clean = str(evento_id).replace('-', '')
            
            if action == "add_bulk" or action == "add":
                agregados_count = 0
                
                with connection.cursor() as cursor:
                    for p_id in persona_ids:
                        persona_id_clean = str(p_id).replace('-', '')
                        
                        # 1. Verificar si ya existe la participación
                        cursor.execute("""
                            SELECT COUNT(*) FROM elecciones_participacioneleccion 
                            WHERE evento_id = %s AND persona_id = %s
                        """, [evento_id_clean, persona_id_clean])
                        existe = cursor.fetchone()[0] > 0
                        
                        if not existe:
                            # 2. Agregar participante
                            participacion_id = str(uuid.uuid4()).replace('-', '')
                            cursor.execute("""
                                INSERT INTO elecciones_participacioneleccion (id, evento_id, persona_id, ha_votado)
                                VALUES (%s, %s, %s, 0)
                            """, [participacion_id, evento_id_clean, persona_id_clean])
                            agregados_count += 1
                
                if agregados_count > 0:
                    messages.success(request, f"Se agregaron {agregados_count} participantes correctamente.")
                else:
                    messages.info(request, "Los usuarios seleccionados ya eran participantes.")

            elif action == "remove_bulk" or action == "remove":
                removidos_count = 0
                bloqueados_count = 0
                
                with connection.cursor() as cursor:
                    for p_id in persona_ids:
                        persona_id_clean = str(p_id).replace('-', '')
                        
                        # 1. Verificar si ha votado
                        cursor.execute("""
                            SELECT ha_votado FROM elecciones_participacioneleccion 
                            WHERE evento_id = %s AND persona_id = %s
                        """, [evento_id_clean, persona_id_clean])
                        row = cursor.fetchone()
                        
                        if row:
                            ha_votado = row[0]
                            if not ha_votado:
                                # 2. Eliminar si no ha votado
                                cursor.execute("""
                                    DELETE FROM elecciones_participacioneleccion 
                                    WHERE evento_id = %s AND persona_id = %s
                                """, [evento_id_clean, persona_id_clean])
                                removidos_count += 1
                            else:
                                bloqueados_count += 1
                
                if removidos_count > 0:
                    messages.success(request, f"Se eliminaron {removidos_count} participantes.")
                if bloqueados_count > 0:
                    messages.warning(request, f"{bloqueados_count} participantes no se pudieron eliminar porque ya votaron.")

        except Exception as e:
            logger.exception("Error gestionando participantes masivos")
            messages.error(request, f"Ocurrió un error al procesar la solicitud: {str(e)}")
        
        return redirect("asignar_participantes", evento_id=evento_id)
    
    # --- LOGICA GET (SIN CAMBIOS, SOLO OPTIMIZADA) ---
    try:
        from django.db import connection
        
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
                'persona__foto_url': part_row[4]
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
                'foto_display_url': user_row[3]
            })
            
    except Exception as e:
        participantes_actuales = []
        usuarios_disponibles = []
        logger.exception(f"Error obteniendo participantes para evento {evento_id}")
    
    # Contar candidatos actuales
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
