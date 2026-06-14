from django.urls import path
from . import views

urlpatterns = [
    path('', views.camara_view, name='camara'),
    path('capturar/', views.capturar_objeto, name='camara_capturar'),
    path('evaluar/', views.evaluar_pronunciacion, name='camara_evaluar'),
]
