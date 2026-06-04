from django.shortcuts import render
from django.contrib.auth.decorators import login_required

@login_required # Obliga a que el niño haya iniciado sesión para ver esto
def camara_view(request):
    return render(request, 'camara_inteligente/camara.html')