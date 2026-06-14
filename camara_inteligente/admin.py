from django.contrib import admin

from .models import FraseTemplate


@admin.register(FraseTemplate)
class FraseTemplateAdmin(admin.ModelAdmin):
    list_display = ('objeto_keyword', 'frase_plantilla', 'nivel_dificultad', 'recompensa_monedas')
    list_filter = ('nivel_dificultad',)
    search_fields = ('objeto_keyword', 'frase_plantilla')
