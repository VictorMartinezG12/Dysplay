"""
Modelos del módulo `reportes` (Módulo J del Master Plan).

Registra el historial de envíos de reportes de progreso al correo del
tutor configurado en `UsuarioCustom.correo_tutor`.
"""

from django.conf import settings
from django.db import models


class ReporteEnviado(models.Model):
    """
    Representa un envío (exitoso o fallido) de un reporte de progreso
    al correo del tutor de un estudiante.
    """

    TIPO_MANUAL = 'manual'
    TIPO_AUTOMATICO = 'automatico'
    TIPO_CHOICES = [
        (TIPO_MANUAL, 'Manual'),
        (TIPO_AUTOMATICO, 'Automático'),
    ]

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='reportes_enviados',
        on_delete=models.CASCADE,
    )
    correo_destino = models.EmailField()
    tipo_envio = models.CharField(max_length=20, choices=TIPO_CHOICES)
    exitoso = models.BooleanField(default=True)
    fecha_envio = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha_envio']

    def __str__(self):
        estado = 'exitoso' if self.exitoso else 'fallido'
        return f"Reporte {self.tipo_envio} a {self.correo_destino} ({estado}) - {self.fecha_envio:%d/%m/%Y %H:%M}"
