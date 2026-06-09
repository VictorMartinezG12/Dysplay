from django.db import models
from django.conf import settings  # 1. IMPORTANTE: Cambiamos la importación aquí

class Nivel(models.Model):
    numero = models.IntegerField(unique=True)
    titulo = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True)
    puntos_recompensa = models.IntegerField(default=50)

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