from django.db import models
from django.utils import timezone
import uuid


class Persona(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nombre = models.CharField(max_length=255)
    email = models.EmailField(unique=True, null=True, blank=True)
    rut = models.CharField(max_length=20, unique=True, null=True, blank=True)
    password_hash = models.CharField(max_length=255, null=True, blank=True)
    clave = models.CharField(max_length=50, null=True, blank=True)
    es_votante = models.BooleanField(default=False)
    es_candidato = models.BooleanField(default=False)
    foto_url = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.nombre} <{self.email}>"

    @staticmethod
    def generar_clave_robusta(longitud=12):
        import secrets, string
        caracteres = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
        return ''.join(secrets.choice(caracteres) for _ in range(longitud))


class Administrador(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    persona = models.OneToOneField(Persona, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Administrador: {self.persona.nombre}"


class EventoEleccion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nombre = models.CharField(max_length=255)
    fecha_inicio = models.DateTimeField()
    fecha_termino = models.DateTimeField()
    administrador = models.ForeignKey(Administrador, on_delete=models.CASCADE, null=True, blank=True)
    id_administrador = models.CharField(max_length=36, null=True, blank=True)
    activo = models.BooleanField(default=True)
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
        return self.nombre


class ParticipacionEleccion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    evento = models.ForeignKey(EventoEleccion, on_delete=models.CASCADE)
    persona = models.ForeignKey(Persona, on_delete=models.CASCADE)
    ha_votado = models.BooleanField(default=False)

    class Meta:
        unique_together = (('evento', 'persona'),)

    def __str__(self):
        return f"{self.persona.nombre} en {self.evento.nombre}"


class Candidatura(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    evento = models.ForeignKey(EventoEleccion, on_delete=models.CASCADE)
    persona = models.ForeignKey(Persona, on_delete=models.CASCADE)
    propuesta = models.TextField(null=True, blank=True)
    fecha_registro = models.DateTimeField(auto_now_add=True, null=True)

    class Meta:
        unique_together = (('evento', 'persona'),)

    def __str__(self):
        return f"Candidatura: {self.persona.nombre} en {self.evento.nombre}"


class Voto(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    evento = models.ForeignKey(EventoEleccion, on_delete=models.CASCADE)
    persona_candidato = models.ForeignKey(Persona, on_delete=models.CASCADE, related_name='votos_recibidos')
    time_stamp = models.DateTimeField(auto_now_add=True)
    
    # Blockchain fields
    commitment = models.CharField(max_length=66, null=True, blank=True, help_text="Keccak256 hash commitment of the vote")
    tx_hash = models.CharField(max_length=66, null=True, blank=True, help_text="Transaction hash on blockchain")
    block_number = models.BigIntegerField(null=True, blank=True, help_text="Block number where commitment was stored")
    onchain_status = models.CharField(
        max_length=20,
        default='pending',
        choices=[('pending', 'Pending'), ('sent', 'Sent'), ('confirmed', 'Confirmed'), ('failed', 'Failed')],
        help_text="Status of blockchain submission"
    )

    def __str__(self):
        return f"Voto {self.id} -> {self.persona_candidato.nombre}"


class Resultado(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    evento = models.ForeignKey(EventoEleccion, on_delete=models.CASCADE)
    persona_candidato = models.ForeignKey(Persona, on_delete=models.CASCADE)
    conteo_votos = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (('evento', 'persona_candidato'),)

    def __str__(self):
        return f"Resultado: {self.persona_candidato.nombre} ({self.conteo_votos})"
