from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from avatar.reactions import obtener_reaccion
from . import services


@login_required  # Obliga a que el niño haya iniciado sesión para ver esto
def estadisticas_view(request):
    contexto = services.construir_contexto_estadisticas(request.user)
    contexto['resultado_envio_reporte'] = request.GET.get('reporte')
    contexto['avatar_frase_contextual'] = obtener_reaccion('bienvenida_estadisticas')
    return render(request, 'estadisticas/estadisticas.html', contexto)
