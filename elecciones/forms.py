from django import forms
from .models import Persona, EventoEleccion
from django.utils import timezone


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
        fields = ['nombre', 'foto_url', 'es_votante', 'es_candidato']


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

    def clean(self):
        cleaned_data = super().clean()
        inicio = cleaned_data.get('fecha_inicio')
        termino = cleaned_data.get('fecha_termino')

        if inicio and termino:
            if termino <= inicio:
                raise forms.ValidationError("La fecha de término debe ser posterior a la de inicio.")
            if inicio < timezone.now():
                raise forms.ValidationError("La fecha de inicio no puede estar en el pasado.")
   

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
