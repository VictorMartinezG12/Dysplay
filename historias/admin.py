from django import forms
from django.contrib import admin, messages
from django.shortcuts import redirect, render
from django.urls import path, reverse

from . import services
from .models import (
    FragmentoGenerado,
    FragmentoHistoria,
    Historia,
    HistoriaGenerada,
    OpcionGenerada,
    OpcionRespuesta,
    ProgresoHistoria,
)


class GenerarHistoriaIAForm(forms.Form):
    """Formulario mínimo del admin para generar una `Historia` completa vía IA a partir de un tema."""

    tema = forms.CharField(
        label='Tema de la historia',
        max_length=255,
        help_text='Ej. "un dragón que aprende a compartir".',
    )
    nivel_dificultad = forms.ChoiceField(
        label='Nivel de dificultad de vocabulario',
        choices=[(str(n), str(n)) for n in range(1, 6)],
        initial='1',
    )


class OpcionRespuestaInline(admin.TabularInline):
    model = OpcionRespuesta
    fk_name = 'fragmento'
    extra = 1


class FragmentoHistoriaInline(admin.StackedInline):
    model = FragmentoHistoria
    extra = 1
    show_change_link = True


@admin.register(Historia)
class HistoriaAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'nivel_dificultad', 'duracion_estimada_minutos', 'recompensa_monedas', 'orden', 'activa')
    list_filter = ('nivel_dificultad', 'activa')
    search_fields = ('titulo',)
    inlines = [FragmentoHistoriaInline]
    change_list_template = 'admin/historias/historia/change_list.html'

    def get_urls(self):
        """Agrega la URL personalizada del formulario de generación de historias vía IA."""
        urls_personalizadas = [
            path(
                'generar-ia/',
                self.admin_site.admin_view(self.generar_historia_ia_view),
                name='historias_historia_generar_ia',
            ),
        ]
        return urls_personalizadas + super().get_urls()

    def generar_historia_ia_view(self, request):
        """
        Vista del admin que muestra un formulario simple (tema + nivel de
        dificultad) y, al enviarse, genera una `Historia` completa vía Azure
        OpenAI (`services.crear_historia_desde_ia`) y la persiste igual que
        una historia curada manualmente.

        Protegida por los permisos estándar del admin: requiere estar
        autenticado como staff (`admin_site.admin_view`) y, explícitamente,
        tener permiso de alta sobre `Historia`.
        """
        if not self.has_add_permission(request):
            messages.error(request, 'No tienes permiso para crear historias.')
            return redirect(reverse('admin:historias_historia_changelist'))

        if request.method == 'POST':
            formulario = GenerarHistoriaIAForm(request.POST)
            if formulario.is_valid():
                resultado = services.crear_historia_desde_ia(
                    tema=formulario.cleaned_data['tema'],
                    nivel_dificultad=int(formulario.cleaned_data['nivel_dificultad']),
                )

                if resultado['status'] == 'success':
                    messages.success(request, 'Historia generada correctamente. Revisa y ajusta su contenido.')
                    return redirect(reverse('admin:historias_historia_change', args=[resultado['historia_id']]))

                messages.error(request, resultado['message'])
                return redirect(reverse('admin:historias_historia_generar_ia'))
        else:
            formulario = GenerarHistoriaIAForm()

        contexto = {
            **self.admin_site.each_context(request),
            'form': formulario,
            'title': 'Generar historia completa con IA',
            'opts': self.model._meta,
        }
        return render(request, 'admin/historias/historia/generar_ia.html', contexto)


@admin.register(FragmentoHistoria)
class FragmentoHistoriaAdmin(admin.ModelAdmin):
    list_display = ('historia', 'orden', 'tipo_respuesta')
    list_filter = ('historia', 'tipo_respuesta')
    inlines = [OpcionRespuestaInline]


@admin.register(ProgresoHistoria)
class ProgresoHistoriaAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'historia', 'completada', 'fecha_inicio', 'fecha_fin')
    list_filter = ('completada', 'historia')
    search_fields = ('usuario__username',)


@admin.register(HistoriaGenerada)
class HistoriaGeneradaAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'palabras_clave', 'fecha_creacion', 'fecha_expiracion', 'completada')
    list_filter = ('completada',)
    search_fields = ('usuario__username', 'palabras_clave')
