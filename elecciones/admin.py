from django.contrib import admin
from .models import Persona

@admin.register(Persona)
class PersonaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'es_votante', 'es_candidato', 'created_at')
    list_filter = ('es_votante', 'es_candidato')
    search_fields = ('nombre',)