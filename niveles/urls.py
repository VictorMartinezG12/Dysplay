from django.urls import path
from . import views

urlpatterns = [
    path('', views.niveles_view, name='niveles'),
    path('guardar-progreso/', views.guardar_progreso, name='guardar_progreso'),
]