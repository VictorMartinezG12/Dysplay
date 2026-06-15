from django.contrib import admin

from .models import RegistroActividad


@admin.register(RegistroActividad)
class RegistroActividadAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'tipo_actividad', 'zona', 'score', 'fecha')
    list_filter = ('tipo_actividad', 'zona', 'fecha')
    search_fields = ('usuario__username',)
