"""
🎯 GUÍA COMPLETA: SISTEMA DE VOTACIÓN CON FLUJO PARTICIPANTES → CANDIDATOS
=========================================================================

📋 CÓMO FUNCIONA AHORA:
======================

1. **PANEL DE ADMINISTRACIÓN MEJORADO**
   - Cada evento muestra estadísticas de participantes y candidatos
   - Botones organizados en orden lógico: 1º Participantes, 2º Candidatos
   - Indicadores visuales de configuración completa/incompleta
   - El botón de candidatos se deshabilita si no hay participantes

2. **PROCESO PASO A PASO**

   🔸 **PASO 1: ASIGNAR PARTICIPANTES**
   - Ve a Panel Admin → "1. Asignar Participantes" de un evento
   - Selecciona qué usuarios (votantes) pueden participar en ESE evento específico
   - Se crean registros en tabla 'ParticipacionEleccion'
   - Solo estos usuarios podrán votar en el evento

   🔸 **PASO 2: ELEGIR CANDIDATOS**  
   - Ve a Panel Admin → "2. Elegir Candidatos" de un evento
   - SOLO se muestran los participantes ya asignados al evento
   - Selecciona cuáles de esos participantes serán candidatos
   - Se crean registros en tabla 'Candidatura' y se marca es_candidato=True

3. **LÓGICA DE RESTRICCIONES**
   ✅ Solo participantes del evento pueden ser candidatos
   ✅ Si intentas asignar candidatos sin participantes → te redirige automáticamente
   ✅ Los signals mantienen sincronizado es_candidato automáticamente
   ✅ Una persona puede ser candidato en múltiples eventos

4. **INTERFAZ MEJORADA**
   - Badges visuales que muestran quién es candidato
   - Estadísticas en tiempo real de participantes/candidatos por evento
   - Navegación clara entre pasos
   - Alertas informativas que explican el proceso

🛠 COMANDOS ÚTILES:
==================

# Verificar estado de candidatos
python manage.py sync_candidatos --check

# Reparar inconsistencias (si las hubiera)
python manage.py sync_candidatos --sync

# Probar todo el flujo
python test_flujo_completo.py

📊 ESTRUCTURA DE DATOS:
=======================

EventoEleccion
    ↓ (1:N)
ParticipacionEleccion ← Solo estos usuarios pueden votar
    ↓ (subset)
Candidatura ← Solo participantes pueden ser candidatos
    ↓ (actualiza automáticamente)
Persona.es_candidato = True

🎯 BENEFICIOS DEL NUEVO SISTEMA:
===============================

1. **Control granular**: Cada evento tiene sus propios participantes y candidatos
2. **Integridad garantizada**: Imposible tener candidatos que no sean participantes
3. **UI intuitiva**: Proceso guiado paso a paso con indicadores visuales
4. **Sincronización automática**: Los signals mantienen todo consistente
5. **Escalabilidad**: Una persona puede participar en múltiples eventos

🔍 PARA DESARROLLADORES:
=======================

**Modelos clave:**
- EventoEleccion: Eventos de votación
- ParticipacionEleccion: Quien puede votar en cada evento (unique_together evento+persona)
- Candidatura: Quien es candidato en cada evento (unique_together evento+persona)  
- Persona.es_candidato: Campo global (True si es candidato en cualquier evento)

**Views principales:**
- asignar_participantes: Gestiona quién puede votar
- asignar_candidatos: Gestiona quién puede ser elegido (solo de participantes)

**Signals automáticos:**
- post_save Candidatura → es_candidato = True
- post_delete Candidatura → verifica otros eventos antes de es_candidato = False

**Templates mejorados:**
- admin_panel.html: Muestra estadísticas y flujo ordenado
- asignar_participantes.html: Gestión de participantes con navegación
- asignar_candidatos.html: Solo muestra participantes del evento

Este sistema garantiza integridad de datos y ofrece una experiencia de usuario clara y ordenada.
"""

print("📖 Consulta esta guía para entender el sistema completo")
print("📁 Ubicación: flujo_participantes_candidatos_guide.py")