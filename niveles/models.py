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
    orden_en_zona = models.PositiveSmallIntegerField(default=1)
    narrativa_intro = models.TextField(blank=True, default='')

    def __str__(self):
        return f"Nivel {self.numero}: {self.titulo}"

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