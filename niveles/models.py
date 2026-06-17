from django.core.exceptions import ValidationError
from django.db import models
from django.conf import settings  # 1. IMPORTANTE: Cambiamos la importación aquí

class Nivel(models.Model):
    # Claves de zona del Mapa de Aventura (Módulo D del Master Plan).
    ZONA_BOSQUE = 'bosque_encantado'
    ZONA_MONTANA = 'montana_letras'
    ZONA_VALLE = 'valle_silabas'
    ZONA_CASTILLO = 'castillo_palabras'
    ZONA_REINO = 'reino_lectura'

    ZONA_CHOICES = [
        (ZONA_BOSQUE, 'Bosque Encantado'),
        (ZONA_MONTANA, 'Montaña de las Letras'),
        (ZONA_VALLE, 'Valle de las Sílabas'),
        (ZONA_CASTILLO, 'Castillo de las Palabras'),
        (ZONA_REINO, 'Reino de la Lectura'),
    ]

    numero = models.IntegerField(unique=True)
    titulo = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True)
    puntos_recompensa = models.IntegerField(default=50)
    zona = models.CharField(max_length=20, choices=ZONA_CHOICES, default=ZONA_BOSQUE)
    orden_en_zona = models.PositiveSmallIntegerField(null=True, blank=True)
    narrativa_intro = models.TextField(blank=True, default='')

    def clean(self):
        """
        Bloquea la creación (nunca la edición) de un nivel nuevo en una zona
        marcada como `cerrada` en el modelo `Zona`. Si la zona aún no tiene
        una fila en `Zona` (por ejemplo, en tests que no la crean), no se
        bloquea nada — `cerrada` es una restricción opcional, no obligatoria.
        """
        super().clean()
        if self.pk is None:
            zona_obj = Zona.objects.filter(clave=self.zona).first()
            if zona_obj and zona_obj.cerrada:
                raise ValidationError({
                    'zona': f"La zona '{zona_obj.nombre}' está cerrada. No se pueden agregar niveles nuevos aquí.",
                })

    def save(self, *args, **kwargs):
        # Se llama explícitamente (no full_clean) para no revalidar de más
        # otros campos y mantener este chequeo activo también fuera del
        # admin (shell, scripts, servicios) — no solo en formularios.
        self.clean()
        if self.orden_en_zona is None:
            ultimo = Nivel.objects.filter(zona=self.zona).order_by('-orden_en_zona').first()
            self.orden_en_zona = (ultimo.orden_en_zona + 1) if ultimo else 1
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Nivel {self.numero}: {self.titulo}"


class Zona(models.Model):
    """
    Estado administrativo de cada zona del Mapa de Aventura — independiente
    de `Nivel.zona` (que sigue siendo el mismo CharField de siempre, para no
    afectar a `desafio`/`estadisticas`, que ya dependen de que sea un string
    plano). `clave` usa las mismas 5 claves de `Nivel.ZONA_CHOICES`.

    Cuando `cerrada=True`, `Nivel.clean()` impide crear niveles nuevos en
    esa zona (la protección real); el admin además oculta esa opción en el
    formulario de creación (solo una ayuda de usabilidad).
    """
    clave = models.CharField(max_length=20, unique=True, choices=Nivel.ZONA_CHOICES)
    nombre = models.CharField(max_length=100)
    orden = models.PositiveSmallIntegerField(default=0)
    cerrada = models.BooleanField(
        default=False,
        help_text="Si está marcada, no se pueden agregar niveles nuevos a esta zona.",
    )
    descripcion = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['orden']
        verbose_name = 'Zona'
        verbose_name_plural = 'Zonas'

    def __str__(self):
        return self.nombre

class MisionVocabulario(models.Model):
    TIPO_CHOICES = [
        ('VOZ', 'Evaluación Fonética'),
        ('VISION', 'Reconocimiento de Objetos'),
    ]
    nivel = models.ForeignKey(Nivel, on_delete=models.CASCADE, related_name='misiones')
    palabra_objetivo = models.CharField(max_length=50)
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES, default='VOZ')
    frase_historia = models.TextField()

    def __str__(self):
        return f"[{self.tipo}] {self.palabra_objetivo} (Nivel {self.nivel.numero})"

class ProgresoEstudiante(models.Model):
    # 2. SOLUCIÓN: Apuntamos dinámicamente al usuario del proyecto usando settings.AUTH_USER_MODEL
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    nivel_actual = models.ForeignKey(Nivel, on_delete=models.SET_NULL, null=True, blank=True)
    puntos_acumulados = models.IntegerField(default=0)

    def __str__(self):
        return f"Progreso de {self.usuario}"

class ProgresoNivel(models.Model):
    """
    Mejor resultado histórico (en estrellas, 1 a 3) de un estudiante en un
    nivel ya superado. Se usa solo para mostrar las estrellas en el mapa de
    aventura (B.2) — es independiente de las monedas, que ya se calculan en
    services.calcular_recompensas() sin depender de este modelo.
    """
    progreso = models.ForeignKey(ProgresoEstudiante, on_delete=models.CASCADE, related_name='progresos_nivel')
    nivel = models.ForeignKey(Nivel, on_delete=models.CASCADE)
    mejores_estrellas = models.PositiveSmallIntegerField(default=0)

    class Meta:
        unique_together = ('progreso', 'nivel')

    def __str__(self):
        return f"{self.progreso.usuario} - Nivel {self.nivel.numero}: {self.mejores_estrellas}⭐"