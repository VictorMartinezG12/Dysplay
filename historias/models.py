from django.conf import settings
from django.db import models


class Historia(models.Model):
    """Historia interactiva ramificada disponible en el módulo de cuentos."""

    DIFICULTAD_CHOICES = [
        ('facil', 'Fácil'),
        ('medio', 'Media'),
        ('dificil', 'Difícil'),
    ]

    titulo = models.CharField(max_length=100)
    portada = models.ImageField(upload_to='historias/portadas/', blank=True, null=True)
    descripcion_corta = models.CharField(max_length=255, blank=True)
    nivel_dificultad = models.CharField(max_length=10, choices=DIFICULTAD_CHOICES, default='facil')
    duracion_estimada_minutos = models.PositiveSmallIntegerField(default=5)
    recompensa_monedas = models.PositiveIntegerField(
        default=15,
        help_text='Monedas otorgadas al completar esta historia.',
    )
    activa = models.BooleanField(default=True)
    orden = models.PositiveSmallIntegerField(
        default=0,
        help_text='Orden del carrusel. Determina también el desbloqueo secuencial: '
                   'una historia se desbloquea al completar la anterior en este orden.',
    )

    class Meta:
        verbose_name = 'Historia'
        verbose_name_plural = 'Historias'
        ordering = ['orden', 'id']

    def __str__(self):
        return self.titulo


class FragmentoHistoria(models.Model):
    """Fragmento (página) de una `Historia`, con su narración y pregunta interactiva opcional."""

    TIPO_RESPUESTA_CHOICES = [
        ('', 'Sin pregunta (solo narración)'),
        ('pronunciar', 'Pronunciar'),
        ('escribir', 'Escribir'),
        ('elegir', 'Elegir opción'),
    ]

    historia = models.ForeignKey(Historia, on_delete=models.CASCADE, related_name='fragmentos')
    orden = models.PositiveSmallIntegerField()
    texto_narracion = models.TextField()
    audio_narracion = models.FileField(upload_to='historias/audios/', blank=True, null=True)
    pregunta_interactiva = models.TextField(blank=True)
    tipo_respuesta = models.CharField(
        max_length=10, choices=TIPO_RESPUESTA_CHOICES, blank=True, default='',
    )

    class Meta:
        verbose_name = 'Fragmento de historia'
        verbose_name_plural = 'Fragmentos de historia'
        ordering = ['historia', 'orden']
        unique_together = ('historia', 'orden')

    def __str__(self):
        return f'{self.historia.titulo} - Fragmento {self.orden}'


class OpcionRespuesta(models.Model):
    """Opción de respuesta para la pregunta interactiva de un `FragmentoHistoria`."""

    fragmento = models.ForeignKey(FragmentoHistoria, on_delete=models.CASCADE, related_name='opciones')
    texto = models.CharField(max_length=255)
    es_correcta = models.BooleanField(default=False)
    fragmento_siguiente = models.ForeignKey(
        FragmentoHistoria,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='opciones_que_llevan_aqui',
        help_text='Si se define, responder esta opción lleva a este fragmento '
                   '(ramificación). Si se deja vacío, se avanza al siguiente '
                   'fragmento por orden.',
    )

    class Meta:
        verbose_name = 'Opción de respuesta'
        verbose_name_plural = 'Opciones de respuesta'

    def __str__(self):
        return f'{self.fragmento} - {self.texto}'


class ProgresoHistoria(models.Model):
    """Progreso de un usuario sobre una `Historia` concreta."""

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='progresos_historia',
    )
    historia = models.ForeignKey(Historia, on_delete=models.CASCADE, related_name='progresos')
    fragmento_actual = models.ForeignKey(
        FragmentoHistoria, on_delete=models.SET_NULL, null=True, blank=True,
    )
    completada = models.BooleanField(default=False)
    fecha_inicio = models.DateTimeField(auto_now_add=True)
    fecha_fin = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Progreso de historia'
        verbose_name_plural = 'Progresos de historia'
        unique_together = ('usuario', 'historia')

    def __str__(self):
        return f'{self.usuario} - {self.historia.titulo}'
