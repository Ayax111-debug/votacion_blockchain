"""
Script para diagnosticar y arreglar fechas corruptas en EventoEleccion
"""
import os
import sys
import django

# Configurar Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'votacion.settings')
django.setup()

from elecciones.models import EventoEleccion
from django.utils import timezone
from datetime import datetime


def diagnosticar_fechas_eventos():
    """Diagnostica problemas de fechas en eventos"""
    print("DIAGNOSTICO DE FECHAS EN EVENTOS")
    print("=" * 50)
    
    eventos = EventoEleccion.objects.all()
    print(f"Total de eventos: {eventos.count()}")
    
    eventos_con_problemas = []
    
    for evento in eventos:
        problemas = []
        
        # Verificar tipo de fecha_inicio
        if isinstance(evento.fecha_inicio, str):
            problemas.append(f"fecha_inicio es string: '{evento.fecha_inicio}'")
        elif not hasattr(evento.fecha_inicio, 'utcoffset'):
            problemas.append(f"fecha_inicio no es datetime valido: {type(evento.fecha_inicio)}")
            
        # Verificar tipo de fecha_termino
        if isinstance(evento.fecha_termino, str):
            problemas.append(f"fecha_termino es string: '{evento.fecha_termino}'")
        elif not hasattr(evento.fecha_termino, 'utcoffset'):
            problemas.append(f"fecha_termino no es datetime valido: {type(evento.fecha_termino)}")
        
        if problemas:
            eventos_con_problemas.append({
                'evento': evento,
                'problemas': problemas
            })
            print(f"\nEVENTO PROBLEMATICO: {evento.nombre} (ID: {evento.id})")
            for problema in problemas:
                print(f"   - {problema}")
    
    if not eventos_con_problemas:
        print("\nNo se encontraron problemas de fechas")
    else:
        print(f"\nSe encontraron {len(eventos_con_problemas)} eventos con problemas")
        
    return eventos_con_problemas


if __name__ == "__main__":
    diagnosticar_fechas_eventos()


def reparar_fechas_eventos(modo='dry_run'):
    """Intenta reparar fechas corruptas"""
    print(f"\n🔧 REPARACIÓN DE FECHAS (modo: {modo})")
    print("=" * 50)
    
    eventos_problematicos = diagnosticar_fechas_eventos()
    
    if not eventos_problematicos:
        print("✅ No hay eventos que reparar")
        return
    
    for item in eventos_problematicos:
        evento = item['evento']
        print(f"\n🔧 Procesando: {evento.nombre}")
        
        try:
            # Intentar convertir fechas string a datetime
            fecha_inicio_nueva = None
            fecha_termino_nueva = None
            
            if isinstance(evento.fecha_inicio, str):
                # Intentar parsear diferentes formatos
                formatos = [
                    '%Y-%m-%d %H:%M:%S',
                    '%Y-%m-%d %H:%M:%S.%f',
                    '%Y-%m-%d',
                    '%d/%m/%Y %H:%M',
                    '%d/%m/%Y'
                ]
                
                for formato in formatos:
                    try:
                        fecha_inicio_nueva = timezone.make_aware(
                            datetime.strptime(evento.fecha_inicio, formato)
                        )
                        print(f"   ✅ fecha_inicio convertida: {fecha_inicio_nueva}")
                        break
                    except ValueError:
                        continue
            
            if isinstance(evento.fecha_termino, str):
                for formato in formatos:
                    try:
                        fecha_termino_nueva = timezone.make_aware(
                            datetime.strptime(evento.fecha_termino, formato)
                        )
                        print(f"   ✅ fecha_termino convertida: {fecha_termino_nueva}")
                        break
                    except ValueError:
                        continue
            
            # Aplicar cambios si no es dry_run
            if modo == 'fix' and (fecha_inicio_nueva or fecha_termino_nueva):
                if fecha_inicio_nueva:
                    evento.fecha_inicio = fecha_inicio_nueva
                if fecha_termino_nueva:
                    evento.fecha_termino = fecha_termino_nueva
                evento.save()
                print(f"   💾 Evento actualizado")
            elif modo == 'dry_run':
                print(f"   🔍 (Modo dry_run: no se guardaron cambios)")
            
        except Exception as e:
            print(f"   ❌ Error al procesar: {str(e)}")
            if modo == 'delete_problematic':
                print(f"   🗑️  Eliminando evento problemático...")
                if input(f"¿Confirmar eliminación de '{evento.nombre}'? (y/N): ").lower() == 'y':
                    evento.delete()
                    print(f"   ✅ Evento eliminado")


def limpiar_eventos_corruptos():
    """Elimina eventos que no se pueden reparar"""
    eventos_problematicos = diagnosticar_fechas_eventos()
    
    if not eventos_problematicos:
        return
    
    print(f"\n🗑️  LIMPIEZA DE EVENTOS CORRUPTOS")
    print("=" * 50)
    
    for item in eventos_problematicos:
        evento = item['evento']
        print(f"\nEvento: {evento.nombre}")
        print(f"Problemas: {len(item['problemas'])}")
        
        respuesta = input(f"¿Eliminar '{evento.nombre}'? (y/N): ")
        if respuesta.lower() == 'y':
            evento.delete()
            print(f"✅ Eliminado: {evento.nombre}")
        else:
            print(f"⏭️  Saltado: {evento.nombre}")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        modo = sys.argv[1]
        if modo == 'diagnose':
            diagnosticar_fechas_eventos()
        elif modo == 'fix':
            reparar_fechas_eventos('fix')
        elif modo == 'clean':
            limpiar_eventos_corruptos()
        else:
            print("Uso: python fix_fechas_eventos.py [diagnose|fix|clean]")
    else:
        # Por defecto, solo diagnosticar
        diagnosticar_fechas_eventos()
        print("\n💡 Para reparar: python fix_fechas_eventos.py fix")
        print("💡 Para limpiar: python fix_fechas_eventos.py clean")