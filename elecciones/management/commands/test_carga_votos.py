import time
import random
import threading
from concurrent.futures import ThreadPoolExecutor
from django.core.management.base import BaseCommand
from django.test import Client
from django.db import connection
# Asegúrate de importar tus modelos correctamente
from elecciones.models import Persona, EventoEleccion, ParticipacionEleccion, Candidatura, Voto

class Command(BaseCommand):
    help = 'Ejecuta una prueba de carga de 100 votos simultáneos (Reset + Ataque)'

    def add_arguments(self, parser):
        parser.add_argument('evento_id', type=str, help='22e35c822ff64609bdf6bb2cd2012a9c')

    def handle(self, *args, **options):
        evento_id = options['evento_id']
        
        # 1. Validar Evento
        try:
            evento = EventoEleccion.objects.get(id=evento_id)
            self.stdout.write(self.style.SUCCESS(f"🎯 Objetivo: Evento '{evento.nombre}' (ID: {evento_id}) using MySQL"))
        except EventoEleccion.DoesNotExist:
            self.stdout.write(self.style.ERROR("Evento no encontrado"))
            return

        # 2. Obtener Candidatos
        candidatos_ids = list(Candidatura.objects.filter(evento=evento).values_list('persona__id', flat=True))
        if not candidatos_ids:
            self.stdout.write(self.style.ERROR("No hay candidatos en este evento."))
            return

        # 3. PREPARACIÓN: GENERAR Y RESETEAR BOTS (Limpieza de estado)
        self.stdout.write("🧹 Limpiando historial de los bots y preparando terreno...")
        votantes = []
        
        # Usamos 100 bots
        for i in range(100):
            nombre_bot = f"Bot LoadTest {i+1}"
            rut_bot = f"BOT-{i+1}"
            
            # Crear o recuperar bot
            p, created = Persona.objects.get_or_create(
                rut=rut_bot,
                defaults={
                    'nombre': nombre_bot,
                    'email': f"bot{i}@test.com",
                    'es_votante': True,
                    'clave': '123'
                }
            )
            
            # --- ZONA DE RESETEO (CRUCIAL) ---
            # 1. Eliminar voto previo si existe
            Voto.objects.filter(persona_votante=p, evento=evento).delete()
            
            # 2. Resetear/Crear participación
            participacion, _ = ParticipacionEleccion.objects.get_or_create(evento=evento, persona=p)
            if participacion.ha_votado:
                participacion.ha_votado = False
                participacion.save()
            # ---------------------------------

            votantes.append(p)

        self.stdout.write(self.style.SUCCESS(f"✅ 100 Bots listos, invitados y reseteados."))

        # 4. DEFINIR EL ATAQUE
        resultados = {'exito': 0, 'error': 0, 'tiempos': []}
        lock = threading.Lock()

        def disparar_voto(votante):
            # Cada hilo tiene su propio cliente
            c = Client()
            start_time = time.time()
            
            try:
                # A) Simular Login (inyectando sesión)
                session = c.session
                session['votante_id'] = str(votante.id)
                session.save()

                # B) Elegir candidato random
                candidato_elegido = random.choice(candidatos_ids)

                # C) POST (Con la URL corregida con GUION MEDIO)
                url = f'/votar-evento/{evento_id}/'
                response = c.post(url, {'candidato': str(candidato_elegido)})

                duration = time.time() - start_time

                with lock:
                    resultados['tiempos'].append(duration)
                    
                    # Detectar URL de destino en caso de redirección
                    if hasattr(response, 'url'):
                        target_url = response.url
                    else:
                        target_url = response.headers.get('Location', '')

                    # Lógica de éxito: Redirección a voto_confirmado
                    if response.status_code == 302 and 'voto-confirmado' in str(target_url):
                        resultados['exito'] += 1
                        # Opcional: imprimir solo cada 10 éxitos para no saturar consola
                        # print(f"✅ Bot {votante.rut}: OK") 
                    else:
                        resultados['error'] += 1
                        print(f"❌ Bot {votante.rut}: FALLÓ ({response.status_code}) -> {target_url}")

            except Exception as e:
                with lock:
                    resultados['error'] += 1
                print(f"💀 Error Script Bot {votante.rut}: {e}")
            finally:
                # Cerrar conexión de DB de este hilo para evitar saturación en MySQL
                connection.close()

        # 5. EJECUTAR ATAQUE (Concurrencia Alta)
        self.stdout.write(self.style.WARNING("\n🚀 INICIANDO ATAQUE SIMULTÁNEO (MySQL Ready)..."))
        start_global = time.time()

        # Con MySQL podemos ser más agresivos. Probamos con 50 hilos simultáneos.
        # Si tu PC se traba, baja a 20.
        with ThreadPoolExecutor(max_workers=50) as executor:
            executor.map(disparar_voto, votantes)

        end_global = time.time()
        total_time = end_global - start_global

        # 6. REPORTE
        self.stdout.write("\n" + "="*40)
        self.stdout.write("📊 REPORTE FINAL (MySQL)")
        self.stdout.write("="*40)
        self.stdout.write(f"Tiempo Total: {total_time:.2f} segundos")
        
        tasa = 100 / total_time if total_time > 0 else 0
        self.stdout.write(f"Velocidad: {tasa:.2f} votos/segundo")
        
        self.stdout.write(self.style.SUCCESS(f"Votos Exitosos: {resultados['exito']}"))
        if resultados['error'] > 0:
            self.stdout.write(self.style.ERROR(f"Votos Fallidos: {resultados['error']}"))
        
        if resultados['tiempos']:
            avg = sum(resultados['tiempos']) / len(resultados['tiempos'])
            self.stdout.write(f"Latencia promedio: {avg:.2f} segundos")