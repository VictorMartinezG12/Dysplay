from django.conf import settings
from django.db import models


class TipoInsignia(models.Model):
    """Define un tipo de insignia (logro) que los usuarios pueden desbloquear."""

    CRITERIO_CHOICES = [
        ('primer_nivel', 'Completar el primer nivel'),
        ('racha_7', 'Mantener una racha de 7 días'),
        ('racha_30', 'Mantener una racha de 30 días'),
        ('palabras_100', 'Acumular 100 puntos'),
        ('historias_10', 'Completar 10 historias'),
        ('nivel_5', 'Alcanzar el nivel 5'),
        ('nivel_10', 'Alcanzar el nivel 10'),
        ('desafio_diario', 'Completar un desafío diario'),
    ]

    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True)
    imagen = models.ImageField(upload_to='recompensas/insignias/', blank=True, null=True)
    criterio = models.CharField(max_length=30, choices=CRITERIO_CHOICES)
    valor_umbral = models.IntegerField(default=0)

    def __str__(self):
        return self.nombre


class Insignia(models.Model):
    """Registro de una insignia obtenida por un usuario."""

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='insignias')
    tipo_insignia = models.ForeignKey(TipoInsignia, on_delete=models.CASCADE)
    fecha_obtenida = models.DateTimeField(auto_now_add=True)
    mostrada = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.usuario} - {self.tipo_insignia.nombre}"


class Mascota(models.Model):
    """Mascota virtual disponible para ser adoptada por los usuarios."""

    ESPECIE_CHOICES = [
        ('dragon', 'Dragón'),
        ('perro', 'Perro'),
        ('gato', 'Gato'),
        ('robot', 'Robot'),
        ('unicornio', 'Unicornio'),
    ]

    nombre = models.CharField(max_length=100)
    especie = models.CharField(max_length=20, choices=ESPECIE_CHOICES)
    imagen_base = models.ImageField(upload_to='recompensas/mascotas/', blank=True, null=True)
    imagen_feliz = models.ImageField(upload_to='recompensas/mascotas/', blank=True, null=True)
    imagen_triste = models.ImageField(upload_to='recompensas/mascotas/', blank=True, null=True)
    precio_monedas = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.nombre} ({self.get_especie_display()})"


class MascotaUsuario(models.Model):
    """Relación entre un usuario y la mascota que ha adoptado."""

    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='mascota_usuario')
    mascota = models.ForeignKey(Mascota, on_delete=models.CASCADE)
    fecha_adopcion = models.DateTimeField(auto_now_add=True)
    nivel_afecto = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.usuario} - {self.mascota.nombre}"


class Coleccionable(models.Model):
    """Elemento coleccionable que los usuarios pueden obtener."""

    TIPO_CHOICES = [
        ('animal', 'Animal'),
        ('carta', 'Carta'),
        ('personaje', 'Personaje'),
        ('objeto_magico', 'Objeto Mágico'),
    ]

    nombre = models.CharField(max_length=100)
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    imagen = models.ImageField(upload_to='recompensas/coleccionables/', blank=True, null=True)
    descripcion = models.TextField(blank=True)
    precio_monedas = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.nombre} ({self.get_tipo_display()})"


class ColeccionableUsuario(models.Model):
    """Registro de un coleccionable obtenido por un usuario."""

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='coleccionables')
    coleccionable = models.ForeignKey(Coleccionable, on_delete=models.CASCADE)
    fecha_obtencion = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('usuario', 'coleccionable')

    def __str__(self):
        return f"{self.usuario} - {self.coleccionable.nombre}"


class EventoEspecial(models.Model):
    """Evento de temporada que puede cambiar la apariencia o reglas del juego."""

    TIPO_CHOICES = [
        ('navidad', 'Navidad'),
        ('halloween', 'Halloween'),
        ('vacaciones', 'Vacaciones'),
    ]

    nombre = models.CharField(max_length=100)
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()
    activo = models.BooleanField(default=False)
    fondo_especial = models.ImageField(upload_to='recompensas/eventos/', blank=True, null=True)

    def __str__(self):
        return f"{self.nombre} ({self.get_tipo_display()})"
