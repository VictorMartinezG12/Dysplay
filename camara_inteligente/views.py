import logging

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse

from avatar.reactions import obtener_reaccion
from . import services

logger = logging.getLogger(__name__)


@login_required  # Obliga a que el niño haya iniciado sesión para ver esto
def camara_view(request):
    context = {
        'camara_config': {
            'url_capturar': reverse('camara_capturar'),
            'url_evaluar': reverse('camara_evaluar'),
            'url_home': reverse('home'),
        },
        'avatar_frase_contextual': obtener_reaccion('bienvenida_camara'),
    }
    return render(request, 'camara_inteligente/camara.html', context)


@login_required
def capturar_objeto(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Método no permitido.'}, status=405)

    imagen_base64 = request.POST.get('imagen')
    punto_objetivo_json = request.POST.get('punto_objetivo')
    clase_offline = request.POST.get('clase_offline')

    try:
        resultado = services.procesar_captura_imagen(
            request.user, imagen_base64, punto_objetivo_json, clase_offline
        )
        return JsonResponse(resultado)
    except Exception:
        logger.error('Error al procesar la captura de la cámara inteligente', exc_info=True)
        return JsonResponse(
            {'status': 'error', 'message': 'Ocurrió un error al analizar la imagen. Inténtalo de nuevo.'},
            status=500,
        )


@login_required
def evaluar_pronunciacion(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Método no permitido.'}, status=405)

    frase_referencia = request.POST.get('frase_referencia')

    try:
        resultado = services.procesar_evaluacion_pronunciacion(
            request.user, request.FILES.get('audio'), frase_referencia
        )
        return JsonResponse(resultado)
    except Exception:
        logger.error('Error al evaluar la pronunciación de la cámara inteligente', exc_info=True)
        return JsonResponse(
            {'status': 'error', 'message': 'Ocurrió un error al procesar tu intento. Inténtalo de nuevo.'},
            status=500,
        )
