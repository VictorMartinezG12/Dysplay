from django.urls import path
from . import views

app_name = 'avatar'

urlpatterns = [
    path('personalizar/', views.personalizar_avatar, name='personalizar'),
    path('casa/', views.casa_avatar, name='casa'),
    path('comprar-item/', views.comprar_item, name='comprar_item'),
    path('colocar-item/', views.colocar_item, name='colocar_item'),
    path('equipar-item/', views.equipar_item, name='equipar_item'),
    path('comprar-y-equipar/', views.comprar_y_equipar, name='comprar_y_equipar'),
    path('desequipar-item/', views.desequipar_item, name='desequipar_item'),
]
