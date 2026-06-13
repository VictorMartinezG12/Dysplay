from .models import ConfiguracionGlobal

def configuracion_global(request):
    if request.user.is_authenticated:
        config, created = ConfiguracionGlobal.objects.get_or_create(usuario=request.user)
        return {'config_global': config}
    return {}
