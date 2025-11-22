from django.apps import AppConfig


class EleccionesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'elecciones'

    def ready(self):
        # Registrar signals cuando la app esté lista
        import elecciones.signals
