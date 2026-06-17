from django import forms
from django.contrib import admin
from .models import Nivel, MisionVocabulario, ProgresoEstudiante, ProgresoNivel, Zona

class NivelAdminForm(forms.ModelForm):
    """
    Oculta del selector de zona las zonas marcadas como `cerrada` al CREAR
    un nivel nuevo (capa de usabilidad: evita el error antes de que ocurra).
    La protección real está en `Nivel.clean()`, que se aplica siempre,
    incluso si este formulario no se usa (shell, scripts, etc.).
    Al EDITAR un nivel ya existente se mantiene su zona actual disponible
    en la lista, aunque esa zona haya sido cerrada después.
    """
    class Meta:
        model = Nivel
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        claves_cerradas = set(Zona.objects.filter(cerrada=True).values_list('clave', flat=True))
        if self.instance and self.instance.pk:
            claves_cerradas.discard(self.instance.zona)
        self.fields['zona'].choices = [
            (clave, etiqueta) for clave, etiqueta in Nivel.ZONA_CHOICES if clave not in claves_cerradas
        ]

@admin.register(Nivel)
class NivelAdmin(admin.ModelAdmin):
    form = NivelAdminForm
    list_display = ('numero', 'titulo', 'puntos_recompensa', 'zona', 'orden_en_zona')
    list_filter = ('zona',)
    ordering = ('numero',)

@admin.register(Zona)
class ZonaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'clave', 'orden', 'cerrada')
    list_editable = ('cerrada',)
    ordering = ('orden',)

@admin.register(MisionVocabulario)
class MisionVocabularioAdmin(admin.ModelAdmin):
    list_display = ('palabra_objetivo', 'nivel', 'tipo')
    list_filter = ('tipo', 'nivel')

@admin.register(ProgresoEstudiante)
class ProgresoEstudianteAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'nivel_actual', 'puntos_acumulados')

@admin.register(ProgresoNivel)
class ProgresoNivelAdmin(admin.ModelAdmin):
    list_display = ('progreso', 'nivel', 'mejores_estrellas')
    list_filter = ('mejores_estrellas',)