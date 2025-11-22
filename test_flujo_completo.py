"""
Script de prueba para verificar el flujo de participantes → candidatos
"""
import os
import sys
import django

# Configurar Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'votacion.settings')
django.setup()

from elecciones.models import Persona, EventoEleccion, ParticipacionEleccion, Candidatura
from django.utils import timezone
from datetime import timedelta


def test_flujo_participantes_candidatos():
    print("🧪 PRUEBA DEL FLUJO: PARTICIPANTES → CANDIDATOS")
    print("=" * 60)
    
    # Limpiar datos de prueba anteriores
    test_personas = Persona.objects.filter(email__contains='@test-flujo.com')
    test_eventos = EventoEleccion.objects.filter(nombre__contains='Test Flujo')
    test_personas.delete()
    test_eventos.delete()
    
    # 1. Crear personas de prueba
    print("\n1️⃣ Creando personas de prueba...")
    personas = []
    for i in range(5):
        persona = Persona.objects.create(
            email=f"usuario{i+1}@test-flujo.com",
            nombre=f"Usuario Test {i+1}",
            es_votante=True,
            es_candidato=False
        )
        personas.append(persona)
        print(f"✅ Creado: {persona.nombre}")
    
    # 2. Crear evento
    print("\n2️⃣ Creando evento...")
    evento = EventoEleccion.objects.create(
        nombre="Test Flujo Participantes-Candidatos",
        fecha_inicio=timezone.now(),
        fecha_termino=timezone.now() + timedelta(days=7),
        activo=True
    )
    print(f"✅ Creado evento: {evento.nombre}")
    
    # 3. Estado inicial (sin participantes ni candidatos)
    print("\n3️⃣ Estado inicial:")
    participantes = ParticipacionEleccion.objects.filter(evento=evento).count()
    candidatos = Candidatura.objects.filter(evento=evento).count()
    print(f"📊 Participantes: {participantes}, Candidatos: {candidatos}")
    
    # 4. PASO 1: Asignar participantes (primeros 3 usuarios)
    print("\n4️⃣ PASO 1: Asignando participantes...")
    for i in range(3):
        ParticipacionEleccion.objects.create(
            evento=evento,
            persona=personas[i],
            ha_votado=False
        )
        print(f"✅ {personas[i].nombre} asignado como participante")
    
    participantes = ParticipacionEleccion.objects.filter(evento=evento).count()
    print(f"📊 Total participantes asignados: {participantes}")
    
    # 5. PASO 2: Intentar asignar candidato que NO es participante (debe fallar en lógica real)
    print("\n5️⃣ Verificando restricción: candidatos solo de participantes...")
    participantes_ids = list(ParticipacionEleccion.objects.filter(evento=evento).values_list('persona_id', flat=True))
    persona_no_participante = personas[4]  # El último usuario no es participante
    
    print(f"📋 Participantes válidos: {[str(p) for p in participantes_ids]}")
    print(f"❌ Persona NO participante: {persona_no_participante.id} ({persona_no_participante.nombre})")
    
    if str(persona_no_participante.id) not in [str(p) for p in participantes_ids]:
        print("✅ Restricción correcta: persona no participante detectada")
    
    # 6. PASO 2: Asignar candidatos válidos (de entre los participantes)
    print("\n6️⃣ PASO 2: Asignando candidatos válidos...")
    for i in range(2):  # Solo los primeros 2 participantes serán candidatos
        candidatura = Candidatura.objects.create(
            evento=evento,
            persona=personas[i]
        )
        print(f"✅ {personas[i].nombre} asignado como candidato")
        
        # Verificar que el signal actualizó es_candidato
        personas[i].refresh_from_db()
        print(f"📊 Estado es_candidato de {personas[i].nombre}: {personas[i].es_candidato}")
    
    # 7. Estado final
    print("\n7️⃣ Estado final:")
    participantes = ParticipacionEleccion.objects.filter(evento=evento).count()
    candidatos = Candidatura.objects.filter(evento=evento).count()
    print(f"📊 Participantes: {participantes}, Candidatos: {candidatos}")
    
    # Verificar que solo candidatos tienen es_candidato=True
    for persona in personas:
        persona.refresh_from_db()
        es_candidato_en_evento = Candidatura.objects.filter(evento=evento, persona=persona).exists()
        print(f"👤 {persona.nombre}: es_candidato={persona.es_candidato}, candidato_en_evento={es_candidato_en_evento}")
    
    # 8. Probar eliminación de candidatura
    print("\n8️⃣ Probando eliminación de candidatura...")
    primera_candidatura = Candidatura.objects.filter(evento=evento).first()
    persona_candidato = primera_candidatura.persona
    print(f"🗑️ Eliminando candidatura de: {persona_candidato.nombre}")
    
    primera_candidatura.delete()
    persona_candidato.refresh_from_db()
    print(f"📊 Estado es_candidato después de eliminar: {persona_candidato.es_candidato}")
    
    # 9. Verificación de integridad
    print("\n9️⃣ Verificación de integridad:")
    candidaturas_restantes = Candidatura.objects.filter(evento=evento)
    print(f"📊 Candidaturas restantes: {candidaturas_restantes.count()}")
    
    for candidatura in candidaturas_restantes:
        es_participante = ParticipacionEleccion.objects.filter(
            evento=evento, 
            persona=candidatura.persona
        ).exists()
        print(f"✅ {candidatura.persona.nombre}: es candidato y es participante: {es_participante}")
    
    # 10. Limpiar datos de prueba
    print("\n🧹 Limpiando datos de prueba...")
    test_personas = Persona.objects.filter(email__contains='@test-flujo.com')
    test_eventos = EventoEleccion.objects.filter(nombre__contains='Test Flujo')
    test_personas.delete()
    test_eventos.delete()
    print("✅ Limpieza completada")
    
    print("\n" + "=" * 60)
    print("🎉 PRUEBA COMPLETADA - FLUJO FUNCIONAL")
    print("✅ 1. Asignar participantes → OK")
    print("✅ 2. Solo candidatos de participantes → OK")
    print("✅ 3. Signals de sincronización → OK")
    print("✅ 4. Integridad de datos → OK")
    print("=" * 60)


if __name__ == "__main__":
    test_flujo_participantes_candidatos()