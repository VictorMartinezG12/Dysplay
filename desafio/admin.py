from django.contrib import admin

from .models import ConfiguracionDesafio, DesafioDiario, ProgresoDesafio


@admin.register(ConfiguracionDesafio)
class ConfiguracionDesafioAdmin(admin.ModelAdmin):
    list_display = ('zona_activa', 'palabras_meta_hoy', 'recompensa_monedas_base')


@admin.register(DesafioDiario)
class DesafioDiarioAdmin(admin.ModelAdmin):
    list_display = ('fecha', 'recompensa_monedas', 'recompensa_coleccionable')
    list_filter = ('fecha',)


@admin.register(ProgresoDesafio)
class ProgresoDesafioAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'desafio', 'completado', 'fecha_completado', 'monedas_ganadas')
    list_filter = ('completado', 'desafio')
    search_fields = ('usuario__username',)
