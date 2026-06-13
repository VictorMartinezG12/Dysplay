from django.contrib import admin

from .models import (
    Coleccionable,
    ColeccionableUsuario,
    EventoEspecial,
    Insignia,
    Mascota,
    MascotaUsuario,
    TipoInsignia,
)


@admin.register(TipoInsignia)
class TipoInsigniaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'criterio', 'valor_umbral')
    list_filter = ('criterio',)
    search_fields = ('nombre',)


@admin.register(Insignia)
class InsigniaAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'tipo_insignia', 'fecha_obtenida', 'mostrada')
    list_filter = ('mostrada', 'tipo_insignia')
    search_fields = ('usuario__username',)


@admin.register(Mascota)
class MascotaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'especie', 'precio_monedas')
    list_filter = ('especie',)
    search_fields = ('nombre',)


@admin.register(MascotaUsuario)
class MascotaUsuarioAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'mascota', 'fecha_adopcion', 'nivel_afecto')
    search_fields = ('usuario__username', 'mascota__nombre')


@admin.register(Coleccionable)
class ColeccionableAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'tipo', 'precio_monedas')
    list_filter = ('tipo',)
    search_fields = ('nombre',)


@admin.register(ColeccionableUsuario)
class ColeccionableUsuarioAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'coleccionable', 'fecha_obtencion')
    search_fields = ('usuario__username', 'coleccionable__nombre')


@admin.register(EventoEspecial)
class EventoEspecialAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'tipo', 'fecha_inicio', 'fecha_fin', 'activo')
    list_filter = ('tipo', 'activo')
    search_fields = ('nombre',)
