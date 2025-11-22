"""
GUÍA RÁPIDA: Manejo de Candidatos en Sistema de Votación

CÓMO FUNCIONA:
==============

1. ASIGNACIÓN DE CANDIDATOS:
   - Ve a Panel de Admin → "Asignar Candidatos" de un evento
   - Selecciona personas que serán candidatos para ese evento específico
   - Al guardar: se crean registros en tabla 'Candidatura' y se marca es_candidato=True

2. MODELOS INVOLUCRADOS:
   - Persona.es_candidato: Campo booleano global (True si es candidato en cualquier evento)
   - Candidatura: Relación específica evento-persona (candidato en evento específico)

3. SINCRONIZACIÓN AUTOMÁTICA:
   - Signals automáticos mantienen es_candidato sincronizado
   - Al crear Candidatura → es_candidato = True
   - Al eliminar Candidatura → verifica si sigue siendo candidato en otros eventos

4. COMANDOS ÚTILES:
   # Verificar estado actual
   python manage.py sync_candidatos --check
   
   # Sincronizar todo
   python manage.py sync_candidatos --sync
   
   # Desde shell de Django:
   from elecciones.signals import obtener_estado_candidatos, sincronizar_estado_candidatos
   obtener_estado_candidatos()      # Diagnóstico
   sincronizar_estado_candidatos()  # Reparar inconsistencias

5. FLUJO TÍPICO:
   Persona (es_votante=True) → Asignar como candidato → Candidatura creada → es_candidato=True
   
6. FEATURES VISUALES:
   - Panel de admin muestra contadores de votantes/candidatos/candidaturas
   - Template muestra badge "Candidato" junto al nombre
   - Páginas de asignación muestran estado actual

DEBUGGING:
==========
Si hay inconsistencias entre es_candidato y candidaturas:
1. Ejecutar: python manage.py sync_candidatos --check
2. Si hay problemas: python manage.py sync_candidatos --sync
3. Los signals evitan problemas futuros automáticamente

NOTA IMPORTANTE:
===============
- es_candidato: Campo GLOBAL (True si es candidato en cualquier evento activo)
- Candidatura: Relación ESPECÍFICA (candidato en evento particular)
- Una persona puede ser candidato en múltiples eventos simultáneamente
"""

print("📖 Consulta este archivo para entender el manejo de candidatos")
print("📁 Ubicación: test_candidatos_guide.py")