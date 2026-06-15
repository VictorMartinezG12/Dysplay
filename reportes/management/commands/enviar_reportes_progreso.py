"""
Comando de gestión para el envío en lote de reportes de progreso (Módulo J).
"""

from django.core.management.base import BaseCommand

from reportes import services
from reportes.models import ReporteEnviado
from usuarios.models import UsuarioCustom


class Command(BaseCommand):
    """
    Envía el reporte de progreso a todos los usuarios que tienen configurado
    un `correo_tutor`.

    Pensado para ejecutarse periódicamente (ej. semanalmente) mediante un
    cron externo. Este comando NO se ejecuta automáticamente desde la
    aplicación: debe ser invocado manualmente o programado externamente con
    `python manage.py enviar_reportes_progreso`.
    """

    help = (
        'Envía el reporte de progreso semanal por correo a los tutores '
        'configurados (correo_tutor). Pensado para ejecutarse vía cron externo.'
    )

    def handle(self, *args, **options):
        """Itera sobre los usuarios con correo de tutor configurado y envía el reporte."""
        usuarios = UsuarioCustom.objects.exclude(correo_tutor__isnull=True).exclude(correo_tutor__exact='')

        enviados = 0
        fallidos = 0
        sin_correo = 0

        for usuario in usuarios:
            resultado = services.enviar_reporte_progreso(usuario, ReporteEnviado.TIPO_AUTOMATICO)
            if resultado['status'] == 'success':
                enviados += 1
            elif resultado['status'] == 'error':
                fallidos += 1
            else:
                sin_correo += 1

        self.stdout.write(
            f"Reportes de progreso: {enviados} enviados, {fallidos} fallidos, "
            f"{sin_correo} sin correo de tutor configurado."
        )
