from django.contrib import admin
from .models import (
    Avatar, CaraAvatar, Item, InventarioAvatar, ReaccionAvatar, CasaAvatar,
    ItemColocado,
)

@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'categoria', 'subcategoria', 'precio_monedas', 'evento_especial', 'activo')
    list_filter = ('categoria', 'subcategoria', 'activo')
    search_fields = ('nombre',)

@admin.register(CaraAvatar)
class CaraAvatarAdmin(admin.ModelAdmin):
    # La gestión normal de esto es el panel propio (/panel/caras-avatar/, con
    # previsualización en vivo) — esto queda como respaldo/consulta rápida.
    list_display = ('estado', 'imagen', 'imagen_parpadeo')

@admin.register(Avatar)
class AvatarAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'nombre_avatar', 'nivel_visual', 'estado_actual', 'personalidad')
    search_fields = ('usuario__username', 'nombre_avatar')

@admin.register(CasaAvatar)
class CasaAvatarAdmin(admin.ModelAdmin):
    list_display = ('avatar',)
    search_fields = ('avatar__usuario__username',)

@admin.register(ItemColocado)
class ItemColocadoAdmin(admin.ModelAdmin):
    list_display = ('casa', 'slot', 'item')
    list_filter = ('slot',)
    search_fields = ('casa__avatar__usuario__username', 'item__nombre')

@admin.register(InventarioAvatar)
class InventarioAvatarAdmin(admin.ModelAdmin):
    list_display = ('avatar', 'item', 'desbloqueado', 'equipado')
    list_filter = ('desbloqueado', 'equipado', 'item__categoria')
    search_fields = ('avatar__usuario__username', 'item__nombre')

@admin.register(ReaccionAvatar)
class ReaccionAvatarAdmin(admin.ModelAdmin):
    list_display = ('tipo_evento', 'emocion', 'activo')
    list_filter = ('emocion', 'activo')
    search_fields = ('tipo_evento', 'mensaje')
