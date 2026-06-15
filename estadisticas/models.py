from django.conf import settings
from django.db import models

from niveles.models import Nivel


class RegistroActividadManager(models.Manager):
    """Manager de `RegistroActividad` con un helper para registrar evaluaciones exitosas."""

    def registrar(self, usuario, tipo_actividad, score, zona=''):
        """Crea un `RegistroActividad` para una evaluación de pronunciación exitosa.

        Args:
            usuario: instancia de `UsuarioCustom` (estudiante autenticado).
            tipo_actividad (str): uno de `RegistroActividad.TIPO_CHOICES`.
            score (float): `score_global` devuelto por Azure Speech.
            zona (str, optional): clave de `Nivel.ZONA_CHOICES` asociada a la
                actividad, si corresponde a una zona del Mapa de Aventura.

        Returns:
            RegistroActividad: el registro creado.
        """
        return self.create(usuario=usuario, tipo_actividad=tipo_actividad, score=score, zona=zona)


class RegistroActividad(models.Model):
    """Registro de una evaluación de pronunciación exitosa (Azure Speech).

    Cada vez que un estudiante completa con éxito una evaluación de
    pronunciación (en el mapa de niveles, una historia, el desafío diario o
    la cámara inteligente) se crea un registro con la fecha, el tipo de
    actividad, la zona del Mapa de Aventura asociada (si aplica) y el
    puntaje obtenido. Es la fuente de datos real del panel de Estadísticas
    (Módulo H del Master Plan): gráfico de actividad semanal, calendario de
    progreso y áreas de mejora por zona.
    """

    TIPO_NIVEL = 'nivel'
    TIPO_HISTORIA = 'historia'
    TIPO_DESAFIO = 'desafio'
    TIPO_CAMARA = 'camara'

    TIPO_CHOICES = [
        (TIPO_NIVEL, 'Mapa de niveles'),
        (TIPO_HISTORIA, 'Historia interactiva'),
        (TIPO_DESAFIO, 'Desafío diario'),
        (TIPO_CAMARA, 'Cámara inteligente'),
    ]

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='registros_actividad',
    )
    fecha = models.DateField(auto_now_add=True)
    tipo_actividad = models.CharField(max_length=10, choices=TIPO_CHOICES)
    zona = models.CharField(max_length=20, choices=Nivel.ZONA_CHOICES, blank=True, default='')
    score = models.FloatField()

    objects = RegistroActividadManager()

    class Meta:
        verbose_name = 'Registro de actividad'
        verbose_name_plural = 'Registros de actividad'
        ordering = ['-fecha', '-id']

    def __str__(self):
        return f'{self.usuario} - {self.get_tipo_actividad_display()} ({self.fecha})'
