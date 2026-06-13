from django.urls import path
from . import views

app_name = 'configuracion'

urlpatterns = [
    path('', views.ver_configuracion, name='ver'),
]
