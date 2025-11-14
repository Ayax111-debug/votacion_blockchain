from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from .models import Persona, EventoEleccion, CandidatoEvento
from .forms import LoginForm, CandidatoForm, EditarPersonaForm, EventoEleccionForm,LoginForm_votante
import uuid
from django.utils import timezone
from django.core.paginator import Paginator
from django.db.models.signals import pre_save
from django.dispatch import receiver
from .utils import requiere_votante_sesion
from django.shortcuts import render, get_object_or_404
from .models import Persona
from uuid import UUID

def votar_evento(request, evento_id):
    evento = get_object_or_404(EventoEleccion, id=evento_id)
    candidatos = CandidatoEvento.objects.filter(evento=evento)

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
    persona = get_object_or_404(Persona, id=votante_id)

    eventos = EventoEleccion.objects.filter(activo=True)

    return render(request, "panel_usuario.html", {
        "persona": persona,
        "eventos": eventos,
        # "votos": []  # aún no implementado
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

        try:
            persona = Persona.objects.get(rut=rut, clave=clave, es_votante=True)
            # Guardamos el ID en sesión
            request.session["votante_id"] = str(persona.id)
            messages.success(request, "Ingreso exitoso.")
            return redirect("panel_usuario")
        except Persona.DoesNotExist:
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
            evento.id = str(uuid.uuid4())
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
    evento = get_object_or_404(EventoEleccion, id=evento_id)
    votantes = Persona.objects.filter(es_votante=True).order_by('nombre')

    paginator = Paginator(votantes, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    if request.method == 'POST':
        ids_str = request.POST.get('candidatos_globales', '')
        seleccionados = [s for s in ids_str.split(',') if s] if ids_str else []

        CandidatoEvento.objects.filter(evento=evento).delete()

        for persona_id in seleccionados:
            CandidatoEvento.objects.create(
                id=str(uuid.uuid4()),
                evento=evento,
                persona_id=persona_id
            )

        messages.success(request, 'Candidatos actualizados correctamente.')
        return redirect('panel_admin')

    candidatos_actuales = list(
    CandidatoEvento.objects.filter(evento=evento).values_list('persona_id', flat=True)
)

    return render(request, 'asignar_candidatos.html', {
        'evento': evento,
        'page_obj': page_obj,
        'candidatos_actuales': candidatos_actuales
    })

@login_required
@user_passes_test(lambda u: u.is_staff)
def ver_evento(request, evento_id):
    evento = get_object_or_404(EventoEleccion, id=evento_id)
    candidatos = CandidatoEvento.objects.filter(evento=evento).select_related('persona').order_by('fecha_registro')

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
