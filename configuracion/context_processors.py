from .models import ConfiguracionGlobal

def configuracion_global(request):
    """
    Expone la configuración global de accesibilidad/audio del usuario
    autenticado a todos los templates.

    - `config_global`: instancia completa del modelo (clave existente, no se modifica).
    - `config_audio_json`: dict plano JSON-serializable con los campos de audio
      (velocidad_narracion, tipo_voz, volumen_narracion, motor_voz) para ser
      consumido por `json_script` en el frontend (TTS). Para usuarios anónimos
      se devuelven valores por defecto razonables.
    """
    if request.user.is_authenticated:
        config, created = ConfiguracionGlobal.objects.get_or_create(usuario=request.user)
        config_audio_json = {
            'velocidad_narracion': config.velocidad_narracion,
            'tipo_voz': config.tipo_voz,
            'volumen_narracion': config.volumen_narracion,
            'motor_voz': config.motor_voz,
        }
        return {'config_global': config, 'config_audio_json': config_audio_json}

    config_audio_json = {
        'velocidad_narracion': 'normal',
        'tipo_voz': 'nino',
        'volumen_narracion': 80,
        'motor_voz': 'navegador',
    }
    return {'config_audio_json': config_audio_json}
