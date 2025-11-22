"""
Signals para mantener sincronizado el campo es_candidato
"""
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import Candidatura, Persona


@receiver(post_save, sender=Candidatura)
def marcar_persona_como_candidato(sender, instance, created, **kwargs):
    """
    Cuando se crea una candidatura, marca a la persona como candidato
    """
    if created:
        instance.persona.es_candidato = True
        instance.persona.save(update_fields=['es_candidato'])


@receiver(post_delete, sender=Candidatura)
def actualizar_estado_candidato_al_eliminar(sender, instance, **kwargs):
    """
    Cuando se elimina una candidatura, verifica si la persona 
    sigue siendo candidato en otros eventos
    """
    persona = instance.persona
    # Verificar si tiene otras candidaturas
    tiene_otras_candidaturas = Candidatura.objects.filter(persona=persona).exists()
    
    if not tiene_otras_candidaturas:
        persona.es_candidato = False
        persona.save(update_fields=['es_candidato'])


def sincronizar_estado_candidatos():
    """
    Función utilitaria para sincronizar todos los estados de candidatos
    Útil para ejecutar como comando de management o en consola
    """
    from django.db import transaction
    
    with transaction.atomic():
        # Obtener todos los IDs de personas que tienen candidaturas activas
        candidatos_activos = set(
            Candidatura.objects.values_list('persona_id', flat=True).distinct()
        )
        
        # Marcar como candidatos a quienes tienen candidaturas
        Persona.objects.filter(id__in=candidatos_activos).update(es_candidato=True)
        
        # Desmarcar como candidatos a quienes NO tienen candidaturas
        Persona.objects.exclude(id__in=candidatos_activos).update(es_candidato=False)
        
        print(f"✅ Sincronización completada:")
        print(f"   - {len(candidatos_activos)} personas marcadas como candidatos")
        print(f"   - {Persona.objects.filter(es_candidato=False).count()} personas desmarcadas como candidatos")


def obtener_estado_candidatos():
    """
    Función para diagnosticar el estado actual de candidatos
    """
    total_personas = Persona.objects.count()
    marcados_candidatos = Persona.objects.filter(es_candidato=True).count()
    candidaturas_activas = Candidatura.objects.values_list('persona_id', flat=True).distinct().count()
    
    # Detectar inconsistencias
    candidatos_sin_candidatura = Persona.objects.filter(
        es_candidato=True
    ).exclude(
        id__in=Candidatura.objects.values_list('persona_id', flat=True)
    )
    
    personas_con_candidatura_sin_marcar = Persona.objects.filter(
        es_candidato=False,
        id__in=Candidatura.objects.values_list('persona_id', flat=True)
    )
    
    print("📊 ESTADO ACTUAL DE CANDIDATOS:")
    print(f"   - Total personas: {total_personas}")
    print(f"   - Marcados como candidatos (es_candidato=True): {marcados_candidatos}")
    print(f"   - Con candidaturas activas: {candidaturas_activas}")
    print()
    
    if candidatos_sin_candidatura.exists():
        print(f"⚠️  INCONSISTENCIA: {candidatos_sin_candidatura.count()} personas marcadas como candidatos sin candidaturas:")
        for persona in candidatos_sin_candidatura[:5]:  # Mostrar solo los primeros 5
            print(f"   - {persona.nombre} ({persona.email})")
        if candidatos_sin_candidatura.count() > 5:
            print(f"   - ... y {candidatos_sin_candidatura.count() - 5} más")
        print()
    
    if personas_con_candidatura_sin_marcar.exists():
        print(f"⚠️  INCONSISTENCIA: {personas_con_candidatura_sin_marcar.count()} personas con candidaturas no marcadas como candidatos:")
        for persona in personas_con_candidatura_sin_marcar[:5]:
            print(f"   - {persona.nombre} ({persona.email})")
        if personas_con_candidatura_sin_marcar.count() > 5:
            print(f"   - ... y {personas_con_candidatura_sin_marcar.count() - 5} más")
        print()
    
    if not candidatos_sin_candidatura.exists() and not personas_con_candidatura_sin_marcar.exists():
        print("✅ No se detectaron inconsistencias")
    
    return {
        'total_personas': total_personas,
        'marcados_candidatos': marcados_candidatos,
        'candidaturas_activas': candidaturas_activas,
        'inconsistencias': {
            'candidatos_sin_candidatura': candidatos_sin_candidatura.count(),
            'candidaturas_sin_marcar': personas_con_candidatura_sin_marcar.count()
        }
    }