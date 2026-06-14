"""
Modelos del módulo de Desafío Diario (Módulo E del Master Plan).

Define la configuración global de la narrativa del desafío, el desafío
diario en sí (con sus ejercicios obligatorios y opcionales) y el progreso de
cada estudiante sobre dicho desafío.
"""

from django.conf import settings
from django.db import models

from niveles.models import MisionVocabulario, Nivel
from recompensas.models import Coleccionable


class ConfiguracionDesafio(models.Model):
    """
    Configuración global (singleton) del desafío diario.

    Solo existe un registro (pk=1). Define la zona/arco narrativo activo y
    los parámetros base usados al generar el desafío de cada día.
    """

    texto_narrativa_actual = models.TextField(
        blank=True,
        default='',
        help_text='Texto narrativo del día. Si se deja vacío, se calcula '
                   'automáticamente según la zona activa.',
    )
    zona_activa = models.CharField(
        max_length=20, choices=Nivel.ZONA_CHOICES, default=Nivel.ZONA_BOSQUE,
    )
    palabras_meta_hoy = models.PositiveSmallIntegerField(default=5)
    recompensa_monedas_base = models.PositiveIntegerField(default=10)

    class Meta:
        verbose_name = 'Configuración del desafío diario'
        verbose_name_plural = 'Configuración del desafío diario'

    def __str__(self):
        return 'Configuración del Desafío Diario'

    def save(self, *args, **kwargs):
        # Singleton: siempre se guarda con pk=1, sin depender de django-solo.
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def obtener_configuracion(cls):
        """Devuelve el único registro de configuración, creándolo si no existe."""
        configuracion, _creada = cls.objects.get_or_create(pk=1)
        return configuracion


class DesafioDiario(models.Model):
    """Desafío de un día concreto, con sus ejercicios obligatorios y opcionales."""

    fecha = models.DateField(unique=True)
    ejercicios_obligatorios = models.ManyToManyField(
        MisionVocabulario, related_name='desafios_obligatorios', blank=True,
    )
    ejercicios_opcionales = models.ManyToManyField(
        MisionVocabulario, related_name='desafios_opcionales', blank=True,
    )
    recompensa_monedas = models.PositiveIntegerField(default=10)
    recompensa_coleccionable = models.ForeignKey(
        Coleccionable,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='desafios_diarios',
        help_text='Coleccionable a otorgar al completar este desafío. Si se '
                   'deja vacío, se elige uno al azar entre los que el '
                   'usuario aún no tenga.',
    )

    class Meta:
        verbose_name = 'Desafío diario'
        verbose_name_plural = 'Desafíos diarios'
        ordering = ['-fecha']

    def __str__(self):
        return f'Desafío del {self.fecha}'


class ProgresoDesafio(models.Model):
    """Progreso de un usuario sobre un `DesafioDiario` concreto."""

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='progresos_desafio',
    )
    desafio = models.ForeignKey(
        DesafioDiario, on_delete=models.CASCADE, related_name='progresos',
    )
    completado = models.BooleanField(default=False)
    fecha_completado = models.DateTimeField(null=True, blank=True)
    ejercicios_completados = models.ManyToManyField(
        MisionVocabulario, related_name='progresos_desafio', blank=True,
    )
    monedas_ganadas = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Progreso de desafío diario'
        verbose_name_plural = 'Progresos de desafío diario'
        unique_together = ('usuario', 'desafio')

    def __str__(self):
        return f'{self.usuario} - {self.desafio.fecha}'
