from django import forms
from .models import Persona, EventoEleccion
from django.utils import timezone
from django.core.exceptions import ValidationError


class AgregarUsuarioForm(forms.ModelForm):
    """Formulario para agregar nuevos usuarios con foto"""
    foto = forms.ImageField(
        required=False,
        widget=forms.ClearableFileInput(attrs={
            'class': 'form-control',
            'accept': 'image/*',
            'id': 'foto-input'
        }),
        help_text="Selecciona una imagen (JPG, PNG, GIF). Máximo 5MB."
    )
    
    class Meta:
        model = Persona
        fields = ['nombre', 'email', 'rut', 'foto']
        widgets = {
            'nombre': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nombre completo'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'correo@ejemplo.com'
            }),
            'rut': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '12345678-9'
            })
        }
    
    def clean_foto(self):
        foto = self.cleaned_data.get('foto')
        if foto:
            # Validar tamaño del archivo (5MB max)
            if foto.size > 5 * 1024 * 1024:
                raise ValidationError("El archivo es demasiado grande. Máximo 5MB.")
            
            # Validar tipo de archivo
            allowed_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif']
            if foto.content_type not in allowed_types:
                raise ValidationError("Tipo de archivo no válido. Use JPG, PNG o GIF.")
        
        return foto


class EditarUsuarioForm(forms.ModelForm):
    """Formulario para editar usuarios existentes"""
    foto = forms.ImageField(
        required=False,
        widget=forms.ClearableFileInput(attrs={
            'class': 'form-control',
            'accept': 'image/*'
        }),
        help_text="Selecciona una nueva imagen para reemplazar la actual"
    )
    
    class Meta:
        model = Persona
        fields = ['nombre', 'email', 'rut', 'es_votante', 'es_candidato', 'foto']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'rut': forms.TextInput(attrs={'class': 'form-control'}),
            'es_votante': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'es_candidato': forms.CheckboxInput(attrs={'class': 'form-check-input'})
        }
    
    def clean_foto(self):
        foto = self.cleaned_data.get('foto')
        if foto:
            if foto.size > 5 * 1024 * 1024:
                raise ValidationError("El archivo es demasiado grande. Máximo 5MB.")
            
            allowed_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif']
            if foto.content_type not in allowed_types:
                raise ValidationError("Tipo de archivo no válido. Use JPG, PNG o GIF.")
        
        return foto


class CandidatoForm(forms.Form):
    persona_id = forms.ChoiceField(
        label="Seleccionar votante como candidato",
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        votantes = Persona.objects.filter(es_votante=True, es_candidato=False)
        self.fields['persona_id'].choices = [
            (str(p.id), p.nombre) for p in votantes
        ]
        if not votantes.exists():
            self.fields['persona_id'].choices = [('', 'No hay votantes disponibles')]
            self.fields['persona_id'].disabled = True


class EditarPersonaForm(forms.ModelForm):
    class Meta:
        model = Persona
        fields = ['nombre', 'es_votante', 'es_candidato']


class LoginForm(forms.Form):
    username = forms.CharField(widget=forms.TextInput(attrs={
        'class': 'form-control',
        'placeholder': 'Admin'
    }))
    password = forms.CharField(widget=forms.PasswordInput(attrs={
        'class': 'form-control',
        'placeholder': '********'
    }))



# elecciones/forms.py
class EventoEleccionForm(forms.ModelForm):
    class Meta:
        model = EventoEleccion
        fields = ['nombre', 'fecha_inicio', 'fecha_termino']
        widgets = {
            'fecha_inicio': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'fecha_termino': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }

    def clean_fecha_inicio(self):
        fecha_inicio = self.cleaned_data.get('fecha_inicio')
        if fecha_inicio:
            # Si la fecha viene sin zona horaria del datetime-local, 
            # la tratamos como hora local de Santiago explícitamente
            if fecha_inicio.tzinfo is None:
                from zoneinfo import ZoneInfo
                santiago_tz = ZoneInfo('America/Santiago')
                fecha_inicio = fecha_inicio.replace(tzinfo=santiago_tz)
        return fecha_inicio
    
    def clean_fecha_termino(self):
        fecha_termino = self.cleaned_data.get('fecha_termino')
        if fecha_termino:
            # Si la fecha viene sin zona horaria del datetime-local,
            # la tratamos como hora local de Santiago explícitamente
            if fecha_termino.tzinfo is None:
                from zoneinfo import ZoneInfo
                santiago_tz = ZoneInfo('America/Santiago')
                fecha_termino = fecha_termino.replace(tzinfo=santiago_tz)
        return fecha_termino

    def clean(self):
        cleaned_data = super().clean()
        inicio = cleaned_data.get('fecha_inicio')
        termino = cleaned_data.get('fecha_termino')

        if inicio and termino:
            if termino <= inicio:
                raise forms.ValidationError("La fecha de término debe ser posterior a la de inicio.")
            
            # Permitir crear eventos hasta 5 minutos en el pasado
            from datetime import timedelta
            
            ahora = timezone.now()  # Ahora usará América/Santiago
            
            # Las fechas ya fueron normalizadas en clean_fecha_inicio/termino
            diferencia_segundos = (ahora - inicio).total_seconds()
            diferencia_minutos = diferencia_segundos / 60
            
            # Permitir hasta 5 minutos en el pasado (con tolerancia de 30 segundos)
            limite_minutos = 5.5  # 5 minutos y 30 segundos
            
            if diferencia_minutos > limite_minutos:
                raise forms.ValidationError(
                    f"La fecha de inicio no puede estar más de 5 minutos en el pasado. "
                    f"Diferencia: {diferencia_minutos:.1f} minutos. "
                    f"Hora actual: {ahora.strftime('%d/%m/%Y %H:%M')}, "
                    f"Hora ingresada: {inicio.strftime('%d/%m/%Y %H:%M')}"
                )
        
        return cleaned_data
   

class LoginForm_votante(forms.Form):
    rut = forms.CharField(
        label="RUT",
        max_length=12,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ej: 12345678-9'
        })
    )
    clave = forms.CharField(
        label="Clave",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': '********'
        })
    )
