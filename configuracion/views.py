from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from . import services
from .models import ConfiguracionGlobal


@login_required
def ver_configuracion(request):
    config, _creado = ConfiguracionGlobal.objects.get_or_create(usuario=request.user)

    if request.method == 'POST':
        config = services.guardar_configuracion(request.user, request.POST)
        services.actualizar_correo_tutor(request.user, request.POST.get('correo_tutor'))
        return redirect('configuracion:ver')

    return render(request, 'configuracion/panel.html', {'config': config})
