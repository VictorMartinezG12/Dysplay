from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from .models import ConfiguracionGlobal

@login_required
def ver_configuracion(request):
    config, created = ConfiguracionGlobal.objects.get_or_create(usuario=request.user)
    
    if request.method == 'POST':
        # 1. Tema Visual
        config.tema_visual = request.POST.get('tema_visual', config.tema_visual)
        
        # 2. Tipo de Fuente
        config.tipo_fuente = request.POST.get('tipo_fuente', config.tipo_fuente)
        
        # 3. Tamaño de Fuente
        config.tamano_fuente = request.POST.get('tamano_fuente', config.tamano_fuente)
        
        # 4. Velocidad de Narración
        config.velocidad_narracion = request.POST.get('velocidad_narracion', config.velocidad_narracion)
        
        config.save()
        
        # 5. Correo del tutor (se guarda en el modelo de Usuario)
        request.user.correo_tutor = request.POST.get('correo_tutor', request.user.correo_tutor)
        request.user.save()
        
        return redirect('configuracion:ver')

    return render(request, 'configuracion/panel.html', {'config': config})
