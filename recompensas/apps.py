from django.apps import AppConfig


class RecompensasConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'recompensas'

    def ready(self):
        """Registra las señales del módulo de recompensas al iniciar la app."""
        import recompensas.signals  # noqa: F401
