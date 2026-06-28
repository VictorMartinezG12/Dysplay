from django.urls import path

from . import views

app_name = 'panel_admin'

urlpatterns = [
    path('', views.PanelHomeView.as_view(), name='home'),
    path('configuracion-sistema/', views.ConfiguracionSistemaView.as_view(), name='configuracion_sistema'),
    path('<slug:slug>/', views.RecursoListView.as_view(), name='lista'),
    path('<slug:slug>/nuevo/', views.RecursoCreateView.as_view(), name='crear'),
    path('<slug:slug>/<int:pk>/editar/', views.RecursoUpdateView.as_view(), name='editar'),
    path('<slug:slug>/<int:pk>/eliminar/', views.RecursoDeleteView.as_view(), name='eliminar'),
]
