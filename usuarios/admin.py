from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import UsuarioCustom

# Esto hace que los nuevos campos se vean bonitos en el panel de Django Admin
class UsuarioCustomAdmin(UserAdmin):
    model = UsuarioCustom
    fieldsets = UserAdmin.fieldsets + (
        ('Información de DysPlay', {'fields': ('es_estudiante', 'es_padre', 'es_profesor', 'monedas', 'racha_dias', 'correo_tutor')}),
    )

admin.site.register(UsuarioCustom, UsuarioCustomAdmin)