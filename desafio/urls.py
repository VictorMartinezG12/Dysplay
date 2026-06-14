from django.urls import path

from . import views

urlpatterns = [
    path('', views.desafio_view, name='desafio'),
    path('evaluar/', views.evaluar_ejercicio, name='desafio_evaluar'),
]
