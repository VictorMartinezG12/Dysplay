from django.contrib import admin

from .models import ConfiguracionCamara, FraseTemplate


@admin.register(FraseTemplate)
class FraseTemplateAdmin(admin.ModelAdmin):
    list_display = ('objeto_keyword', 'frase_plantilla', 'nivel_dificultad', 'recompensa_monedas', 'creada_automaticamente')
    list_filter = ('nivel_dificultad', 'creada_automaticamente')
    search_fields = ('objeto_keyword', 'frase_plantilla')


@admin.register(ConfiguracionCamara)
class ConfiguracionCamaraAdmin(admin.ModelAdmin):
    """Admin de la configuración singleton: no se permite agregar un segundo registro ni eliminar el único existente."""

    list_display = ('modo_economico',)

    def has_add_permission(self, request):
        return not ConfiguracionCamara.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
