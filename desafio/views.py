import logging

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse

from avatar.reactions import obtener_reaccion
from . import services

logger = logging.getLogger(__name__)


@login_required
def desafio_view(request):
    estado = services.construir_estado_desafio(request.user)

    context = {
        'desafio': estado['desafio'],
        'progreso': estado['progreso'],
        'narrativa': estado['narrativa'],
        'obligatorios': estado['obligatorios'],
        'opcionales': estado['opcionales'],
        'bloqueado': estado['bloqueado'],
        'segundos_restantes': estado['segundos_restantes'],
        'desafio_config': {
            'url_evaluar': reverse('desafio_evaluar'),
            'bloqueado': estado['bloqueado'],
            'segundos_restantes': estado['segundos_restantes'],
        },
        'mostrar_puntuacion_detallada': request.user.is_staff,
        'avatar_frase_contextual': obtener_reaccion('bienvenida_desafio'),
    }
    return render(request, 'desafio/desafio.html', context)


@login_required
def evaluar_ejercicio(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Método no permitido.'}, status=405)

    mision_id = request.POST.get('mision_id')

    if not mision_id or not request.FILES.get('audio'):
        return JsonResponse({'status': 'error', 'message': 'Faltan datos del ejercicio o el audio.'})

    try:
        resultado = services.procesar_intento_desafio(request.user, request.FILES.get('audio'), mision_id)
        return JsonResponse(resultado)
    except Exception:
        logger.error('Error al evaluar un ejercicio del desafío diario', exc_info=True)
        return JsonResponse(
            {'status': 'error', 'message': 'Ocurrió un error al procesar tu intento. Inténtalo de nuevo.'},
            status=500,
        )
