from django.urls import path

from . import views

app_name = 'reportes'

urlpatterns = [
    path('enviar/', views.enviar_reporte_view, name='enviar'),
]
