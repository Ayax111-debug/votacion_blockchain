"""
Test simple para verificar la funcionalidad de asignar participantes
"""
import os
import sys

# Configurar Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'votacion.settings')

import django
django.setup()

from elecciones.models import EventoEleccion, ParticipacionEleccion
from django.utils import timezone

print("🧪 TEST DE FUNCIONALIDAD - ASIGNAR PARTICIPANTES")
print("=" * 60)

# Obtener primer evento disponible
eventos = EventoEleccion.objects.all()
print(f"📊 Total de eventos disponibles: {eventos.count()}")

if eventos.exists():
    evento = eventos.first()
    print(f"✅ Usando evento: {evento.nombre} (ID: {evento.id})")
    
    # Probar query que usa la vista
    print("\n🔍 Probando query de participantes actuales...")
    try:
        participantes_actuales = ParticipacionEleccion.objects.filter(
            evento=evento
        ).select_related('persona').values(
            'persona__id', 'persona__nombre', 'persona__email', 
            'ha_votado', 'persona__foto'
        )
        
        print(f"✅ Query exitosa. Participantes encontrados: {len(list(participantes_actuales))}")
        
        for p in participantes_actuales[:3]:  # Solo mostrar primeros 3
            print(f"   - {p['persona__nombre']} ({p['persona__email']})")
            
    except Exception as e:
        print(f"❌ Error en query: {str(e)}")
        
    # Probar acceso a fechas del evento
    print("\n🔍 Probando acceso a fechas del evento...")
    try:
        print(f"✅ Fecha inicio: {evento.fecha_inicio}")
        print(f"✅ Fecha término: {evento.fecha_termino}")
        print(f"✅ Tipo fecha_inicio: {type(evento.fecha_inicio)}")
        print(f"✅ Tipo fecha_término: {type(evento.fecha_termino)}")
        
        # Probar si se puede usar en template
        has_utcoffset = hasattr(evento.fecha_inicio, 'utcoffset')
        print(f"✅ fecha_inicio tiene utcoffset: {has_utcoffset}")
        
    except Exception as e:
        print(f"❌ Error con fechas: {str(e)}")
        
    # Probar la clase EventoSimple
    print("\n🔍 Probando EventoSimple...")
    try:
        evento_data = EventoEleccion.objects.filter(id=evento.id).values(
            'id', 'nombre', 'fecha_inicio', 'fecha_termino', 'activo'
        ).first()
        
        class EventoSimple:
            def __init__(self, data):
                self.id = data['id']
                self.nombre = data['nombre']
                self.fecha_inicio = data['fecha_inicio']
                self.fecha_termino = data['fecha_termino']
                self.activo = data['activo']
        
        evento_simple = EventoSimple(evento_data)
        print(f"✅ EventoSimple creado: {evento_simple.nombre}")
        print(f"✅ Fecha inicio simple: {evento_simple.fecha_inicio}")
        
    except Exception as e:
        print(f"❌ Error con EventoSimple: {str(e)}")
        
else:
    print("⚠️  No hay eventos disponibles para probar")

print("\n" + "=" * 60)
print("✅ Test completado")