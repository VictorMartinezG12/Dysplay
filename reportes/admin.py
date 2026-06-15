from django.contrib import admin

from .models import ReporteEnviado


@admin.register(ReporteEnviado)
class ReporteEnviadoAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'correo_destino', 'tipo_envio', 'exitoso', 'fecha_envio')
    list_filter = ('tipo_envio', 'exitoso')
