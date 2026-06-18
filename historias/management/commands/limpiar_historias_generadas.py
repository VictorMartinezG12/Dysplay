"""
Comando de gestión para la limpieza de historias generadas por IA expiradas
(Módulo F).
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from historias.models import HistoriaGenerada


class Command(BaseCommand):
    """
    Borra las `HistoriaGenerada` cuya `fecha_expiracion` ya pasó.

    El borrado en cascada (`on_delete=models.CASCADE` en `FragmentoGenerado`
    y `OpcionGenerada`) se encarga de eliminar también sus fragmentos y
    opciones asociadas.

    Pensado para ejecutarse periódicamente (ej. cada hora) mediante un cron
    externo. Este comando NO se ejecuta automáticamente desde la
    aplicación: debe ser invocado manualmente o programado externamente con
    `python manage.py limpiar_historias_generadas`.
    """

    help = (
        'Borra las historias generadas por IA (HistoriaGenerada) ya expiradas, '
        'junto con sus fragmentos y opciones. Pensado para ejecutarse vía cron externo.'
    )

    def handle(self, *args, **options):
        """Elimina las historias generadas cuya fecha de expiración ya pasó."""
        historias_expiradas = HistoriaGenerada.objects.filter(fecha_expiracion__lt=timezone.now())
        cantidad_historias = historias_expiradas.count()
        _total_borrado, _detalle = historias_expiradas.delete()

        self.stdout.write(
            f'Historias generadas eliminadas: {cantidad_historias} '
            '(incluye fragmentos y opciones asociadas por cascada).'
        )
