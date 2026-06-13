from django.urls import path
from . import views

app_name = 'avatar'

urlpatterns = [
    path('personalizar/', views.personalizar_avatar, name='personalizar'),
]
