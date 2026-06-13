import logging
import os

from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.contrib.auth.decorators import login_required

from .models import Nivel, ProgresoEstudiante, MisionVocabulario
from . import services

logger = logging.getLogger(__name__)


@login_required
def niveles_view(request):
    niveles = Nivel.objects.all().order_by('numero')
    progreso, created = ProgresoEstudiante.objects.get_or_create(usuario=request.user)

    # Si el estudiante no tiene un nivel asignado pero YA existen niveles en la BD,
    # le asignamos automáticamente el primer nivel disponible.
    if progreso.nivel_actual is None and niveles.exists():
        progreso.nivel_actual = niveles.first()
        progreso.save()

    mision_actual = None
    if progreso.nivel_actual:
        mision_actual = MisionVocabulario.objects.filter(nivel=progreso.nivel_actual).first()

    context = {
        'niveles': niveles,
        'progreso': progreso,
        'mision_actual': mision_actual,
        'niveles_config': {
            'url_guardar_progreso': reverse('guardar_progreso'),
        },
    }
    return render(request, 'niveles/niveles.html', context)


@login_required
def guardar_progreso(request):
    if request.method != 'POST':
        return redirect('niveles')

    # CASO A: El Javascript nos envía el audio para evaluar en Azure
    if request.FILES.get('audio'):
        return _evaluar_audio_y_responder(request)

    # CASO B: El niño presionó el botón final de "Siguiente Nivel" (sin audio)
    return _registrar_avance_nivel(request)


def _evaluar_audio_y_responder(request):
    """Orquesta la evaluación de pronunciación y devuelve el JSON al frontend."""
    palabra_objetivo = request.POST.get('palabra_objetivo')
    nivel_id = request.POST.get('nivel_id')

    if not palabra_objetivo:
        return JsonResponse({'status': 'error', 'message': 'Faltan datos de audio o palabra.'})

    ruta_audio_temporal = None
    try:
        ruta_audio_temporal = services.procesar_audio_subido(request.FILES.get('audio'))
        resultado_azure = services.evaluar_pronunciacion_azure(ruta_audio_temporal, palabra_objetivo)

        if resultado_azure['status'] != 'success':
            return JsonResponse({'status': 'error', 'message': resultado_azure['message']})

        services.guardar_progreso_estudiante(request.user, nivel_id, resultado_azure)
        recompensas = services.calcular_recompensas(request.user, resultado_azure['score_global'], nivel_id)

        return JsonResponse({
            'status': 'success',
            'score': resultado_azure['score_global'],
            'monedas_ganadas': recompensas['monedas_ganadas'],
            'monedas_totales': recompensas['monedas_totales'],
        })
    except Exception as e:
        logger.error(f"Error en guardar_progreso: {e}", exc_info=True)
        return JsonResponse(
            {'status': 'error', 'message': 'Ocurrió un error al procesar tu intento. Inténtalo de nuevo.'},
            status=500,
        )
    finally:
        if ruta_audio_temporal and os.path.exists(ruta_audio_temporal):
            os.remove(ruta_audio_temporal)


def _registrar_avance_nivel(request):
    """Persiste el avance de nivel al pulsar 'Siguiente Nivel' y redirige al mapa."""
    nivel_id = request.POST.get('nivel_id')
    score = request.POST.get('score_obtenido')
    try:
        resultado = {'score_global': float(score or 0)}
        services.guardar_progreso_estudiante(request.user, nivel_id, resultado)
    except Exception as e:
        logger.error(f"Error en guardar_progreso (CASO B): {e}", exc_info=True)
    return redirect('niveles')
