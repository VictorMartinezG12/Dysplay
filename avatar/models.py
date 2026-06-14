from django.db import models
from django.conf import settings

class Item(models.Model):
    CATEGORIA_CHOICES = [
        ('cabello', 'Cabello'),
        ('ropa_superior', 'Ropa Superior'),
        ('ropa_inferior', 'Ropa Inferior'),
        ('calzado', 'Calzado'),
        ('accesorio', 'Accesorio'),
        ('mascota', 'Mascota'),
        ('mueble', 'Mueble'),
        ('decoracion', 'Decoración'),
        ('trofeo', 'Trofeo'),
        ('habitacion', 'Habitación'),
        ('fondo', 'Fondo'),
    ]

    nombre = models.CharField(max_length=100)
    categoria = models.CharField(max_length=20, choices=CATEGORIA_CHOICES)
    imagen = models.ImageField(upload_to='avatar/items/', blank=True, null=True)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)
    # Precio en monedas para comprar el ítem en la tienda (Módulo C.3).
    precio_monedas = models.IntegerField(default=0)
    # Evento especial al que pertenece este ítem, si es exclusivo de temporada.
    evento_especial = models.ForeignKey(
        'recompensas.EventoEspecial',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='items_avatar'
    )

    def __str__(self):
        return f"[{self.get_categoria_display()}] {self.nombre}"

    @property
    def imagen_url_segura(self):
        if self.imagen:
            try:
                return self.imagen.url
            except ValueError:
                pass
        
        # Fallback a placeholders estáticos según categoría
        if self.categoria == 'cabello':
            return '/static/avatar/cabello/estandar.svg'
        if self.categoria in ['ropa', 'ropa_superior', 'ropa_inferior']:
            return '/static/avatar/ropa/estandar.svg'
        if self.categoria == 'calzado':
            return '/static/avatar/accesorios/calzado_estandar.svg' # Placeholder futuro
        
        return '/static/avatar/cuerpo/neutral.svg'

class Avatar(models.Model):
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='avatar_perfil'
    )
    nombre_avatar = models.CharField(max_length=50, default="Mi Amigo")
    nivel_visual = models.IntegerField(default=1)
    
    ESTADO_CHOICES = [
        ('neutral', 'Neutral'),
        ('feliz', 'Feliz'),
        ('triste', 'Triste'),
        ('celebrando', 'Celebrando'),
        ('pensando', 'Pensando'),
        ('sorprendido', 'Sorprendido'),
        ('preocupado', 'Preocupado'),
        ('analizando', 'Analizando'),
        ('explicando', 'Explicando'),
    ]
    estado_actual = models.CharField(
        max_length=20,
        choices=ESTADO_CHOICES,
        default='neutral'
    )

    # Frase personalizada que el avatar usa como saludo (Módulo C.1).
    frase_bienvenida = models.CharField(max_length=150, blank=True)

    PERSONALIDAD_CHOICES = [
        ('animado', 'Animado'),
        ('tranquilo', 'Tranquilo'),
        ('gracioso', 'Gracioso'),
    ]
    personalidad = models.CharField(
        max_length=20,
        choices=PERSONALIDAD_CHOICES,
        default='animado'
    )

    def __str__(self):
        return f"Avatar de {self.usuario.username}"

class InventarioAvatar(models.Model):
    avatar = models.ForeignKey(Avatar, on_delete=models.CASCADE, related_name='inventario')
    item = models.ForeignKey(Item, on_delete=models.CASCADE)
    desbloqueado = models.BooleanField(default=True)
    equipado = models.BooleanField(default=False)

    class Meta:
        unique_together = ('avatar', 'item')

    def __str__(self):
        return f"{self.avatar.usuario.username} - {self.item.nombre} ({'Equipado' if self.equipado else 'Guardado'})"

class ReaccionAvatar(models.Model):
    TIPO_EVENTO_CHOICES = [
        ('PRONUNCIACION_CORRECTA', 'Pronunciación Correcta'),
        ('PRONUNCIACION_INCORRECTA', 'Pronunciación Incorrecta'),
        ('OBJETO_RECONOCIDO', 'Objeto Reconocido'),
        ('OBJETO_NO_RECONOCIDO', 'Objeto No Reconocido'),
        ('HISTORIA_COMPLETADA', 'Historia Completada'),
        ('NIVEL_COMPLETADO', 'Nivel Completado'),
        ('LOGRO_DESBLOQUEADO', 'Logro Desbloqueado'),
        ('ERROR_CONEXION', 'Error de Conexión'),
        ('ERROR_CARGA', 'Error de Carga'),
        ('RECOMPENSA_GANADA', 'Recompensa Ganada'),
    ]

    EMOCION_CHOICES = [
        ('neutral', 'Neutral'),
        ('feliz', 'Feliz'),
        ('triste', 'Triste'),
        ('celebrando', 'Celebrando'),
        ('pensando', 'Pensando'),
        ('sorprendido', 'Sorprendido'),
        ('preocupado', 'Preocupado'),
        ('analizando', 'Analizando'),
        ('explicando', 'Explicando'),
    ]

    tipo_evento = models.CharField(max_length=50, choices=TIPO_EVENTO_CHOICES, unique=True)
    emocion = models.CharField(max_length=20, choices=EMOCION_CHOICES, default='feliz')
    mensaje = models.TextField(help_text="Mensaje que dirá el avatar ante este evento.")
    activo = models.BooleanField(default=True)

    def __str__(self):
        return f"Reacción: {self.tipo_evento}"


class CasaAvatar(models.Model):
    """Representa la habitación/casa personalizable del avatar de un usuario."""

    avatar = models.OneToOneField(
        Avatar,
        on_delete=models.CASCADE,
        related_name='casa'
    )
    cama = models.ForeignKey(
        Item,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='casas_con_cama'
    )
    cuadro = models.ForeignKey(
        Item,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='casas_con_cuadro'
    )
    alfombra = models.ForeignKey(
        Item,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='casas_con_alfombra'
    )
    lampara = models.ForeignKey(
        Item,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='casas_con_lampara'
    )

    def __str__(self):
        return f"Casa de {self.avatar.usuario.username}"
