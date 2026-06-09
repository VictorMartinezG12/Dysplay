import os
import tempfile
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required

from .models import Nivel, ProgresoEstudiante, MisionVocabulario
from servicios.utils import evaluar_pronunciacion


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
    }
    return render(request, 'niveles/niveles.html', context)


@login_required
def guardar_progreso(request):
    if request.method == 'POST':
        # CASO A: El Javascript nos envía el audio para evaluar en Azure
        if request.FILES.get('audio'):
            audio_file = request.FILES.get('audio')
            palabra_objetivo = request.POST.get('palabra_objetivo')
            nivel_id = request.POST.get('nivel_id')

            if not audio_file or not palabra_objetivo:
                return JsonResponse({'status': 'error', 'message': 'Faltan datos de audio o palabra.'})

            # Guardar el audio temporalmente para que Azure lo pueda leer
            with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as temp_audio:
                for chunk in audio_file.chunks():
                    temp_audio.write(chunk)
                temp_audio_path = temp_audio.name

            try:
                # Enviar a tu función global de Azure
                resultado_azure = evaluar_pronunciacion(temp_audio_path, palabra_objetivo)
                os.remove(temp_audio_path)  # Limpiar el archivo

                if resultado_azure['status'] == 'success':
                    return JsonResponse({
                        'status': 'success',
                        'score': resultado_azure['score_global']
                    })
                else:
                    return JsonResponse({'status': 'error', 'message': resultado_azure['message']})

            except Exception as e:
                if os.path.exists(temp_audio_path):
                    os.remove(temp_audio_path)
                return JsonResponse({'status': 'error', 'message': str(e)})

        # CASO B: El niño presionó el botón final de "Siguiente Nivel"
        else:
            nivel_id = request.POST.get('nivel_id')
            score = request.POST.get('score_obtenido')

            # (Más adelante aquí pondremos la lógica para subir de nivel en la base de datos)
            return redirect('niveles')

    return redirect('niveles')