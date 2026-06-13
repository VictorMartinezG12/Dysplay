from django.contrib import admin
from .models import ConfiguracionGlobal

@admin.register(ConfiguracionGlobal)
class ConfiguracionGlobalAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'tema_visual', 'tipo_fuente', 'tamano_fuente', 'actualizado_en')
    search_fields = ('usuario__username', 'usuario__email')
    list_filter = ('tema_visual', 'tipo_fuente', 'tamano_fuente')
