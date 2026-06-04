from django.urls import path
from . import views

urlpatterns = [
    path('', views.estadisticas_view, name='estadisticas'),
]