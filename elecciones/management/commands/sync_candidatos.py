"""
Comando para sincronizar y diagnosticar el estado de candidatos
"""
from django.core.management.base import BaseCommand
from elecciones.signals import sincronizar_estado_candidatos, obtener_estado_candidatos


class Command(BaseCommand):
    help = 'Sincroniza el campo es_candidato con las candidaturas activas'

    def add_arguments(self, parser):
        parser.add_argument(
            '--check',
            action='store_true',
            help='Solo mostrar el estado actual sin hacer cambios',
        )
        parser.add_argument(
            '--sync',
            action='store_true',
            help='Sincronizar el estado de candidatos',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('=== GESTIÓN DE ESTADO DE CANDIDATOS ===\n'))

        if options['check'] or (not options['sync'] and not options['check']):
            # Mostrar estado actual (por defecto si no se especifica nada)
            obtener_estado_candidatos()

        if options['sync']:
            self.stdout.write('\n🔄 Iniciando sincronización...\n')
            sincronizar_estado_candidatos()
            self.stdout.write(self.style.SUCCESS('\n✅ Sincronización completada!\n'))
            
            # Mostrar estado después de sincronizar
            self.stdout.write('📊 Estado después de la sincronización:\n')
            obtener_estado_candidatos()

        if not options['sync'] and not options['check']:
            self.stdout.write('\n💡 Comandos disponibles:')
            self.stdout.write('   python manage.py sync_candidatos --check    # Solo revisar estado')
            self.stdout.write('   python manage.py sync_candidatos --sync     # Sincronizar')
            self.stdout.write('   python manage.py sync_candidatos --check --sync  # Revisar y sincronizar')