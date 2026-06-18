from django.urls import path
from . import views

urlpatterns = [
    path('', views.historias_view, name='historias'),
    path('<int:historia_id>/evaluar/', views.evaluar_fragmento, name='historias_evaluar'),
    path('generar-mia/', views.generar_historia_ia_view, name='historias_generar_mia'),
    path(
        'generadas/<int:historia_generada_id>/evaluar/',
        views.evaluar_fragmento_generado,
        name='historias_generada_evaluar',
    ),
    path('generadas/', views.listar_historias_generadas, name='historias_generadas_listar'),
]
