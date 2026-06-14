from django.contrib import admin

from .models import FragmentoHistoria, Historia, OpcionRespuesta, ProgresoHistoria


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
