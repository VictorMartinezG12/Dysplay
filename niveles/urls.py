from django.urls import path
from . import views

urlpatterns = [
    # El 'name' es súper importante, lo usaremos para los botones HTML
    path('', views.niveles_view, name='niveles'),
]