from django.contrib import admin
from .models import Avatar, Item, InventarioAvatar, ReaccionAvatar, CasaAvatar

@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'categoria', 'precio_monedas', 'evento_especial', 'activo')
    list_filter = ('categoria', 'activo')
    search_fields = ('nombre',)

@admin.register(Avatar)
class AvatarAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'nombre_avatar', 'nivel_visual', 'estado_actual', 'personalidad')
    search_fields = ('usuario__username', 'nombre_avatar')

@admin.register(CasaAvatar)
class CasaAvatarAdmin(admin.ModelAdmin):
    list_display = ('avatar', 'cama', 'cuadro', 'alfombra', 'lampara')
    search_fields = ('avatar__usuario__username',)

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
