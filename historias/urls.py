from django.urls import path
from . import views

urlpatterns = [
    path('', views.historias_view, name='historias'),
    path('<int:historia_id>/evaluar/', views.evaluar_fragmento, name='historias_evaluar'),
]
