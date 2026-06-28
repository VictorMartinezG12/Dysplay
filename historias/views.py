import logging

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse

from avatar.reactions import obtener_reaccion
from . import services
from .models import Historia

logger = logging.getLogger(__name__)


@login_required
def historias_view(request):
    historias = services.obtener_historias_disponibles(request.user)

    lectura = None
    url_evaluar = None
    historia_id = request.GET.get('historia')
    historia_generada_id = request.GET.get('historia_generada')

    if historia_id:
        entrada = next((h for h in historias if str(h['id']) == historia_id and h['estado'] != 'bloqueada'), None)
        if entrada:
            try:
                historia = Historia.objects.get(pk=historia_id, activa=True)
                lectura = services.construir_estado_lectura(request.user, historia)
                url_evaluar = reverse('historias_evaluar', args=[historia.id])
            except Historia.DoesNotExist:
                logger.error('Historia inexistente solicitada (id=%s)', historia_id, exc_info=True)
    elif historia_generada_id:
        historia_generada = services.obtener_historia_generada_vigente(request.user, historia_generada_id)
        if historia_generada:
            lectura = services.construir_estado_lectura_generada(historia_generada)
            url_evaluar = reverse('historias_generada_evaluar', args=[historia_generada.id])

    context = {
        'historias': historias,
        'lectura': lectura,
        'historias_config': {
            'lectura': lectura,
            'url_evaluar': url_evaluar,
        },
        'avatar_frase_contextual': obtener_reaccion('bienvenida_historias'),
    }
    return render(request, 'historias/historias.html', context)


@login_required
def evaluar_fragmento(request, historia_id):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Método no permitido.'}, status=405)

    fragmento_id = request.POST.get('fragmento_id')
    if not fragmento_id:
        return JsonResponse({'status': 'error', 'message': 'Falta el identificador del fragmento.'})

    try:
        historia = Historia.objects.get(pk=historia_id, activa=True)
    except Historia.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'La historia solicitada no existe.'}, status=404)

    try:
        resultado = services.procesar_respuesta_fragmento(
            request.user,
            historia,
            fragmento_id,
            opcion_id=request.POST.get('opcion_id'),
            texto_respuesta=request.POST.get('texto_respuesta'),
            archivo_audio=request.FILES.get('audio'),
        )
        return JsonResponse(resultado)
    except Exception:
        logger.error('Error al evaluar un fragmento de historia', exc_info=True)
        return JsonResponse(
            {'status': 'error', 'message': 'Ocurrió un error al procesar tu respuesta. Inténtalo de nuevo.'},
            status=500,
        )


@login_required
def generar_historia_ia_view(request):
    """Crea una `HistoriaGenerada` a partir de las palabras clave del niño."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Método no permitido.'}, status=405)

    resultado = services.crear_historia_generada_desde_ia(
        request.user, request.POST.get('palabras_clave', ''),
    )
    return JsonResponse(resultado)


@login_required
def evaluar_fragmento_generado(request, historia_generada_id):
    """Procesa la respuesta del estudiante a un fragmento de `HistoriaGenerada` (sin recompensas)."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Método no permitido.'}, status=405)

    fragmento_id = request.POST.get('fragmento_id')
    if not fragmento_id:
        return JsonResponse({'status': 'error', 'message': 'Falta el identificador del fragmento.'})

    historia_generada = services.obtener_historia_generada_vigente(request.user, historia_generada_id)
    if not historia_generada:
        return JsonResponse({'status': 'error', 'message': 'La historia solicitada no existe.'}, status=404)

    try:
        resultado = services.procesar_respuesta_fragmento_generado(
            request.user,
            historia_generada,
            fragmento_id,
            opcion_id=request.POST.get('opcion_id'),
            texto_respuesta=request.POST.get('texto_respuesta'),
            archivo_audio=request.FILES.get('audio'),
        )
        return JsonResponse(resultado)
    except Exception:
        logger.error('Error al evaluar un fragmento de historia generada', exc_info=True)
        return JsonResponse(
            {'status': 'error', 'message': 'Ocurrió un error al procesar tu respuesta. Inténtalo de nuevo.'},
            status=500,
        )


@login_required
def listar_historias_generadas(request):
    """Devuelve las `HistoriaGenerada` vivas (no expiradas) del usuario autenticado."""
    historias = services.obtener_historias_generadas_vivas(request.user)
    return JsonResponse({'status': 'success', 'historias': historias})
