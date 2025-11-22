"""
Script de prueba para verificar el manejo de candidatos
"""
import os
import sys
import django

# Configurar Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'votacion.settings')
django.setup()

from elecciones.models import Persona, Candidatura, EventoEleccion
from elecciones.signals import obtener_estado_candidatos, sincronizar_estado_candidatos


def test_manejo_candidatos():
    print("🧪 PRUEBA DEL SISTEMA DE CANDIDATOS")
    print("=" * 50)
    
    # 1. Estado inicial
    print("\n1️⃣ Estado inicial:")
    obtener_estado_candidatos()
    
    # 2. Crear personas de prueba si no existen
    print("\n2️⃣ Verificando personas de prueba...")
    persona1, created1 = Persona.objects.get_or_create(
        email="candidato1@test.com",
        defaults={
            'nombre': 'Candidato Prueba 1',
            'es_votante': True,
            'es_candidato': False
        }
    )
    
    persona2, created2 = Persona.objects.get_or_create(
        email="candidato2@test.com",
        defaults={
            'nombre': 'Candidato Prueba 2',
            'es_votante': True,
            'es_candidato': False
        }
    )
    
    if created1:
        print(f"✅ Creada persona1: {persona1.nombre}")
    else:
        print(f"📋 Ya existe persona1: {persona1.nombre}")
        
    if created2:
        print(f"✅ Creada persona2: {persona2.nombre}")
    else:
        print(f"📋 Ya existe persona2: {persona2.nombre}")
    
    # 3. Crear evento de prueba si no existe
    print("\n3️⃣ Verificando evento de prueba...")
    from django.utils import timezone
    from datetime import timedelta
    
    evento, created = EventoEleccion.objects.get_or_create(
        nombre="Evento Test Candidatos",
        defaults={
            'fecha_inicio': timezone.now(),
            'fecha_termino': timezone.now() + timedelta(days=7),
            'activo': True
        }
    )
    
    if created:
        print(f"✅ Creado evento: {evento.nombre}")
    else:
        print(f"📋 Ya existe evento: {evento.nombre}")
    
    # 4. Probar asignación de candidatos
    print("\n4️⃣ Probando asignación de candidatos...")
    
    # Limpiar candidaturas anteriores del evento
    Candidatura.objects.filter(evento=evento).delete()
    
    # Asignar persona1 como candidato
    candidatura1 = Candidatura.objects.create(evento=evento, persona=persona1)
    print(f"✅ Asignado {persona1.nombre} como candidato al evento")
    
    # Verificar que el signal funcionó
    persona1.refresh_from_db()
    print(f"📊 Estado es_candidato de {persona1.nombre}: {persona1.es_candidato}")
    
    # 5. Asignar segunda persona
    print("\n5️⃣ Asignando segundo candidato...")
    candidatura2 = Candidatura.objects.create(evento=evento, persona=persona2)
    persona2.refresh_from_db()
    print(f"✅ Asignado {persona2.nombre} como candidato")
    print(f"📊 Estado es_candidato de {persona2.nombre}: {persona2.es_candidato}")
    
    # 6. Estado después de asignaciones
    print("\n6️⃣ Estado después de asignaciones:")
    obtener_estado_candidatos()
    
    # 7. Probar eliminación
    print("\n7️⃣ Probando eliminación de candidatura...")
    candidatura1.delete()
    persona1.refresh_from_db()
    print(f"✅ Eliminada candidatura de {persona1.nombre}")
    print(f"📊 Estado es_candidato de {persona1.nombre}: {persona1.es_candidato}")
    
    # 8. Estado final
    print("\n8️⃣ Estado final:")
    obtener_estado_candidatos()
    
    # 9. Limpiar datos de prueba
    print("\n9️⃣ Limpiando datos de prueba...")
    candidatura2.delete()
    persona1.delete() if created1 else None
    persona2.delete() if created2 else None
    evento.delete() if created else None
    print("🧹 Limpieza completada")
    
    print("\n✅ PRUEBA COMPLETADA")
    print("=" * 50)


if __name__ == "__main__":
    test_manejo_candidatos()