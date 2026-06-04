from django.shortcuts import render
from django.contrib.auth.decorators import login_required

@login_required
def avatar_view(request):
    return render(request, 'avatar/avatar.html')