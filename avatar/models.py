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

    # Subcategoría exclusiva de accesorios (sombrero/gafas/reloj/otro). Existe
    # para permitir que el avatar tenga varios accesorios equipados a la vez
    # sin que se pisen entre sí: la regla de exclusividad de equipado pasa a
    # ser por (categoria='accesorio', subcategoria=X) en vez de por categoria
    # sola, así sombrero+gafas+reloj pueden coexistir pero dos sombreros no.
    SUBCATEGORIA_ACCESORIO_CHOICES = [
        ('sombrero', 'Sombrero'),
        ('gafas', 'Gafas'),
        ('reloj', 'Reloj'),
        ('otro', 'Otro'),
    ]

    nombre = models.CharField(max_length=100)
    categoria = models.CharField(max_length=20, choices=CATEGORIA_CHOICES)
    subcategoria = models.CharField(
        max_length=20,
        blank=True,
        choices=SUBCATEGORIA_ACCESORIO_CHOICES,
        default='',
    )
    imagen = models.ImageField(upload_to='avatar/items/', blank=True, null=True)
    # Piezas de manga independientes (solo aplican a categoria='ropa_superior' con manga larga).
    # Se superponen sobre el brazo/antebrazo del esqueleto del avatar para que se
    # muevan junto con la animación del brazo en vez de quedar fijas sobre el torso.
    manga_sup_izq = models.ImageField(upload_to='avatar/items/mangas/', blank=True, null=True)
    manga_inf_izq = models.ImageField(upload_to='avatar/items/mangas/', blank=True, null=True)
    manga_sup_der = models.ImageField(upload_to='avatar/items/mangas/', blank=True, null=True)
    manga_inf_der = models.ImageField(upload_to='avatar/items/mangas/', blank=True, null=True)
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

    @property
    def mangas_urls(self):
        """Devuelve un dict {slot: url} solo con las piezas de manga que el ítem
        realmente tiene cargadas, para que el avatar las monte sobre el brazo."""
        slots = {
            'sup_izq': self.manga_sup_izq,
            'inf_izq': self.manga_inf_izq,
            'sup_der': self.manga_sup_der,
            'inf_der': self.manga_inf_der,
        }
        urls = {}
        for slot, campo in slots.items():
            if campo:
                try:
                    urls[slot] = campo.url
                except ValueError:
                    continue
        return urls

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

class CaraAvatar(models.Model):
    """Cara del avatar para una emoción concreta (una fila por estado).

    Reemplaza los `<img>` hardcodeados a `feliz_1.svg` en
    `_svg_personaje.html`: el template consulta este modelo (vía el
    templatetag `avatar_tags.caras_avatar`) y muestra la imagen que
    corresponda al estado actual, con `neutral` como respaldo si una
    emoción todavía no tiene fila propia.

    `imagen_parpadeo` es el espacio dejado listo para el parpadeo (pedido
    explícito del usuario, 2026-06-21): mientras esté vacío, el avatar no
    parpadea para ese estado; en cuanto se suba, `avatar_events.js` puede
    alternar entre `imagen` e `imagen_parpadeo` con un `setInterval`.
    """

    estado = models.CharField(max_length=20, choices=Avatar.ESTADO_CHOICES, unique=True)
    imagen = models.ImageField(upload_to='avatar/caras/')
    imagen_parpadeo = models.ImageField(upload_to='avatar/caras/', blank=True, null=True)

    class Meta:
        verbose_name = 'Cara del avatar'
        verbose_name_plural = 'Caras del avatar'
        ordering = ['estado']

    def __str__(self):
        return f"Cara: {self.get_estado_display()}"


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
    """Representa la habitación/casa personalizable del avatar de un usuario.

    Los ítems colocados (cama, cuadro, alfombra, lámpara, mesa, estante,
    silla, etc.) viven en el modelo `ItemColocado`, no como campos directos
    de esta clase: así se puede agregar nuevos slots de mueble sin migrar
    el modelo `CasaAvatar` cada vez.
    """

    avatar = models.OneToOneField(
        Avatar,
        on_delete=models.CASCADE,
        related_name='casa'
    )

    def __str__(self):
        return f"Casa de {self.avatar.usuario.username}"


class ItemColocado(models.Model):
    """Ítem de mueble/decoración colocado en un slot concreto de la casa.

    Reemplaza los antiguos campos fijos `cama`/`cuadro`/`alfombra`/`lampara`
    de `CasaAvatar`, permitiendo agregar nuevos slots (mesa, estante, silla)
    sin tocar el esquema de `CasaAvatar`. El slot `armario` no vive aquí:
    no coloca un ítem, abre el editor de personaje (se maneja en la vista).
    """

    SLOT_CHOICES = [
        ('mesa', 'Mesa'),
        ('estante', 'Estante de libros'),
        ('cama', 'Cama'),
        ('silla', 'Silla'),
        ('cuadro', 'Cuadro'),
        ('lampara', 'Lámpara'),
        ('alfombra', 'Alfombra'),
    ]

    casa = models.ForeignKey(
        'CasaAvatar', on_delete=models.CASCADE, related_name='items_colocados'
    )
    slot = models.CharField(max_length=20, choices=SLOT_CHOICES)
    item = models.ForeignKey('Item', on_delete=models.CASCADE)

    class Meta:
        unique_together = ('casa', 'slot')

    def __str__(self):
        return f"{self.casa} - {self.slot}: {self.item.nombre}"
