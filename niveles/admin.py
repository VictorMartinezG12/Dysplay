from django.contrib import admin
from .models import Nivel, MisionVocabulario, ProgresoEstudiante

@admin.register(Nivel)
class NivelAdmin(admin.ModelAdmin):
    list_display = ('numero', 'titulo', 'puntos_recompensa', 'zona', 'orden_en_zona')
    list_filter = ('zona',)
    ordering = ('numero',)

@admin.register(MisionVocabulario)
class MisionVocabularioAdmin(admin.ModelAdmin):
    list_display = ('palabra_objetivo', 'nivel', 'tipo')
    list_filter = ('tipo', 'nivel')

@admin.register(ProgresoEstudiante)
class ProgresoEstudianteAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'nivel_actual', 'puntos_acumulados')