from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import services
from .models import ReporteEnviado


@login_required
@require_POST
def enviar_reporte_view(request):
    """Envía manualmente el reporte de progreso al tutor del usuario."""
    resultado = services.enviar_reporte_progreso(request.user, ReporteEnviado.TIPO_MANUAL)
    url = reverse('estadisticas')
    return redirect(f"{url}?reporte={resultado['status']}")
