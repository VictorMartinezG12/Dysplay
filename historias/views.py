from django.shortcuts import render
from django.contrib.auth.decorators import login_required

@login_required # Obliga a que el niño haya iniciado sesión para ver esto
def historias_view(request):
    return render(request, 'historias/historias.html')