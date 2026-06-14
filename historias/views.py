import logging

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse

from . import services
from .models import Historia

logger = logging.getLogger(__name__)


@login_required
def historias_view(request):
    historias = services.obtener_historias_disponibles(request.user)

    lectura = None
    url_evaluar = None
    historia_id = request.GET.get('historia')

    if historia_id:
        entrada = next((h for h in historias if str(h['id']) == historia_id and h['estado'] != 'bloqueada'), None)
        if entrada:
            try:
                historia = Historia.objects.get(pk=historia_id, activa=True)
                lectura = services.construir_estado_lectura(request.user, historia)
                url_evaluar = reverse('historias_evaluar', args=[historia.id])
            except Historia.DoesNotExist:
                logger.error('Historia inexistente solicitada (id=%s)', historia_id, exc_info=True)

    context = {
        'historias': historias,
        'lectura': lectura,
        'historias_config': {
            'lectura': lectura,
            'url_evaluar': url_evaluar,
        },
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
