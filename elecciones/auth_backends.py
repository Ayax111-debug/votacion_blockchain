from django.contrib.auth.backends import BaseBackend
from elecciones.models import Persona

class RutAuthBackend(BaseBackend):
    def authenticate(self, request, rut=None, clave=None):
        try:
            persona = Persona.objects.get(rut=rut)
            if persona.clave == clave:
                return persona
        except Persona.DoesNotExist:
            return None

    def get_user(self, user_id):
        try:
            return Persona.objects.get(pk=user_id)
        except Persona.DoesNotExist:
            return None
