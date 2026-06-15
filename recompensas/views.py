from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from . import services


@login_required
@require_POST
def insignias_pendientes_view(request):
    """Devuelve las insignias pendientes de mostrar al usuario y las marca como vistas."""
    insignias = services.obtener_insignias_pendientes(request.user)
    datos = [
        {
            'nombre': insignia.tipo_insignia.nombre,
            'descripcion': insignia.tipo_insignia.descripcion,
            'imagen': insignia.tipo_insignia.imagen.url if insignia.tipo_insignia.imagen else '',
        }
        for insignia in insignias
    ]
    return JsonResponse({'insignias': datos})
