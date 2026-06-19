from django.urls import path
from . import views

app_name = 'configuracion'

urlpatterns = [
    path('', views.ver_configuracion, name='ver'),
    path('audio/sintetizar/', views.sintetizar_audio, name='sintetizar_audio'),
]
