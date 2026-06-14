from django.db import models


class FraseTemplate(models.Model):
    """Frase de práctica asociada a un objeto que la Cámara Inteligente puede reconocer."""

    NIVEL_DIFICULTAD_CHOICES = [(nivel, str(nivel)) for nivel in range(1, 6)]

    objeto_keyword = models.CharField(
        max_length=50,
        help_text='Palabra en español que identifica al objeto (debe coincidir con '
                   'TRADUCCION_OBJETOS en camara_inteligente/services.py).',
    )
    frase_plantilla = models.TextField(help_text='Frase completa que el estudiante leerá en voz alta.')
    nivel_dificultad = models.PositiveSmallIntegerField(choices=NIVEL_DIFICULTAD_CHOICES, default=1)
    recompensa_monedas = models.PositiveIntegerField(
        default=5,
        help_text='Monedas otorgadas al pronunciar correctamente esta frase.',
    )

    class Meta:
        verbose_name = 'Frase de cámara inteligente'
        verbose_name_plural = 'Frases de cámara inteligente'
        ordering = ['objeto_keyword', 'nivel_dificultad']

    def __str__(self):
        return f'{self.objeto_keyword} (nivel {self.nivel_dificultad})'
