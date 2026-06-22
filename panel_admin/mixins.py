from django.http import Http404


class StaffRequiredMixin:
    """Restringe una vista a usuarios con is_staff=True.

    Responde 404 (no 302 a login ni 403) para no delatar que el panel
    de administración existe ante usuarios comunes o anónimos.
    """

    def dispatch(self, request, *args, **kwargs):
        if not (request.user.is_authenticated and request.user.is_staff):
            raise Http404
        return super().dispatch(request, *args, **kwargs)
