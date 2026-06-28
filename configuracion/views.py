import logging

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from servicios.utils import sintetizar_voz_azure

from . import services
from .models import ConfiguracionGlobal

logger = logging.getLogger(__name__)

# Cantidad máxima de caracteres permitidos por petición de síntesis de voz
# (se rechaza, no se trunca, para no narrar un texto distinto al solicitado).
MAX_CARACTERES_TTS = 500


@login_required
def ver_configuracion(request):
    config, _creado = ConfiguracionGlobal.objects.get_or_create(usuario=request.user)

    if request.method == 'POST':
        config = services.guardar_configuracion(request.user, request.POST)
        services.actualizar_correo_tutor(request.user, request.POST.get('correo_tutor'))
        return redirect('home')

    return render(request, 'configuracion/panel.html', {'config': config})


@require_POST
@login_required
def sintetizar_audio(request):
    """Vista delgada: orquesta la síntesis de voz neural con Azure Speech."""
    texto = request.POST.get('texto', '').strip()

    if not texto:
        return JsonResponse({'error': 'texto vacío'}, status=400)

    if len(texto) > MAX_CARACTERES_TTS:
        return JsonResponse({'error': 'texto demasiado largo'}, status=400)

    config, _creado = ConfiguracionGlobal.objects.get_or_create(usuario=request.user)

    try:
        audio_bytes = sintetizar_voz_azure(
            texto, config.tipo_voz, config.velocidad_narracion, config.volumen_narracion
        )
    except Exception:
        logger.error('Error al sintetizar audio con Azure Speech', exc_info=True)
        return JsonResponse({'error': 'no se pudo generar el audio'}, status=500)

    return HttpResponse(audio_bytes, content_type='audio/mpeg')
