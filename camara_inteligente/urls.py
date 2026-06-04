from django.urls import path
from . import views

urlpatterns = [
    path('', views.camara_view, name='camara'),
]
