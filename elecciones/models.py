from django.db import models
from django.utils import timezone
import secrets
import string
import uuid
def rut_temporal():
    """Genera un RUT temporal único para registros antiguos"""
    return str(uuid.uuid4())[:12]  # 12 caracteres únicos

def generar_clave_robusta(longitud=12):
    """Genera una clave robusta con letras, números y símbolos"""
    caracteres = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
    return ''.join(secrets.choice(caracteres) for _ in range(longitud))
                   
class Persona(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nombre = models.CharField(max_length=100)
    rut = models.CharField(max_length=12, unique=True, null=True, blank=True)
    clave = models.CharField(max_length=50, null=True, blank=True)
    es_votante = models.BooleanField(default=False)
    es_candidato = models.BooleanField(default=False)   # <-- nuevo campo
    foto_url = models.URLField(blank=True, null=True)   # <-- nuevo campo
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)  

    def __str__(self):
        return f"{self.nombre} ({self.rut})"

    @staticmethod
    def generar_clave_robusta(longitud=12):
        """Genera una clave robusta con letras, números y símbolos"""
        caracteres = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
        return ''.join(secrets.choice(caracteres) for _ in range(longitud))
    
# elecciones/models.py
class EventoEleccion(models.Model):
    id = models.CharField(primary_key=True, max_length=36, editable=False)
    nombre = models.CharField(max_length=255)
    fecha_inicio = models.DateTimeField()
    fecha_termino = models.DateTimeField()
    id_administrador = models.CharField(max_length=36)
    activo = models.BooleanField(default=True)  # ← nuevo campo
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def estado(self):
        ahora = timezone.now()
        if self.fecha_inicio <= ahora <= self.fecha_termino:
            return "En curso"
        elif ahora < self.fecha_inicio:
            return "Futuro"
        else:
            return "Terminado"
    
    def __str__(self):
        return self
    

class CandidatoEvento(models.Model):
    id = models.CharField(primary_key=True, max_length=36, editable=False)
    persona = models.ForeignKey(Persona, on_delete=models.CASCADE)
    evento = models.ForeignKey(EventoEleccion, on_delete=models.CASCADE)
    fecha_registro = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.persona.nombre} en {self.evento.nombre}"
