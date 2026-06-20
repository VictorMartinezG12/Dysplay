from django.db import models


class FraseTemplate(models.Model):
    """Frase de práctica asociada a un objeto que la Cámara Inteligente puede reconocer."""

    NIVEL_DIFICULTAD_CHOICES = [(nivel, str(nivel)) for nivel in range(1, 6)]

    objeto_keyword = models.CharField(
        max_length=50,
        help_text='Palabra en español que identifica al objeto. Puede haber varias frases '
                   'para el mismo objeto (se elige una al azar); se usan como respaldo si '
                   'Azure OpenAI falla, o siempre que el "modo económico" esté activo (ver '
                   'ConfiguracionCamara) para evitar llamadas al LLM.',
    )
    frase_plantilla = models.TextField(
        help_text='Frase que el estudiante leerá en voz alta.',
    )
    nivel_dificultad = models.PositiveSmallIntegerField(choices=NIVEL_DIFICULTAD_CHOICES, default=1)
    recompensa_monedas = models.PositiveIntegerField(
        default=5,
        help_text='Monedas otorgadas al pronunciar correctamente esta frase.',
    )
    creada_automaticamente = models.BooleanField(
        default=False,
        help_text='True si esta fila fue guardada automáticamente a partir de una frase '
                   'generada con éxito por el LLM (ver _guardar_frase_template_automatica en '
                   'camara_inteligente/services.py), en vez de haber sido escrita a mano por '
                   'el equipo docente.',
    )

    class Meta:
        verbose_name = 'Frase de cámara inteligente'
        verbose_name_plural = 'Frases de cámara inteligente'
        ordering = ['objeto_keyword', 'nivel_dificultad']

    def __str__(self):
        return f'{self.objeto_keyword} (nivel {self.nivel_dificultad})'


class ConfiguracionCamara(models.Model):
    """
    Configuración global (un único registro) del módulo Cámara Inteligente,
    editable desde el admin.

    No está ligada a `ConfiguracionGlobal` (que es por estudiante) porque
    `modo_economico` es una decisión de costos a nivel de toda la plataforma,
    normalmente activada por el equipo docente/administrador.
    """

    modo_economico = models.BooleanField(
        default=False,
        help_text='Si está activo, la Cámara Inteligente deja de llamar a Azure OpenAI por '
                   'completo: traduce el objeto solo con el diccionario fijo, y usa '
                   'únicamente frases ya guardadas (FraseTemplate) o, si no hay ninguna '
                   'guardada para ese objeto, una frase mínima que solo pronuncia su nombre. '
                   'Útil para cortar costos de IA sin apagar el módulo.',
    )

    class Meta:
        verbose_name = 'Configuración de cámara inteligente'
        verbose_name_plural = 'Configuración de cámara inteligente'

    def __str__(self):
        return 'Modo económico activado' if self.modo_economico else 'Modo económico desactivado'

    @classmethod
    def obtener(cls):
        """Devuelve el único registro de configuración, creándolo con valores por defecto si no existe."""
        configuracion, _ = cls.objects.get_or_create(pk=1)
        return configuracion

    def save(self, *args, **kwargs):
        """Fuerza siempre `pk=1` para garantizar que exista un único registro (patrón singleton)."""
        self.pk = 1
        super().save(*args, **kwargs)
