from django.urls import path
from . import views

urlpatterns = [
    path('', views.historias_view, name='historias'),
]