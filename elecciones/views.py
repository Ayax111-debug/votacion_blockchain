from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from .models import Persona, EventoEleccion, Candidatura, Administrador
from .forms import LoginForm, CandidatoForm, EditarPersonaForm, EventoEleccionForm,LoginForm_votante
import uuid
from django.utils import timezone
from django.core.paginator import Paginator
from django.db.models.signals import pre_save
from django.dispatch import receiver
from .utils import requiere_votante_sesion
from uuid import UUID

def votar_evento(request, evento_id):
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
        # Aquí registrarías el voto en tu modelo Voto
        messages.success(request, "¡Tu voto ha sido registrado!")
        return redirect("panel_usuario")

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

    return render(request, "panel_usuario.html", {
        "persona": persona_data,
        "eventos": eventos,
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
