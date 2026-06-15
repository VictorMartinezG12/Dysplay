from django.urls import path

from . import views

app_name = 'recompensas'

urlpatterns = [
    path('insignias-pendientes/', views.insignias_pendientes_view, name='insignias_pendientes'),
]
