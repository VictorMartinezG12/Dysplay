from django.shortcuts import render
from django.contrib.auth.decorators import login_required

@login_required # Obliga a que el niño haya iniciado sesión para ver esto
def estadisticas_view(request):
    return render(request, 'estadisticas/estadisticas.html')