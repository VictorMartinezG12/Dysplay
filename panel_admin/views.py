from django.contrib import messages
from django.forms import modelform_factory
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import CreateView, DeleteView, ListView, TemplateView, UpdateView

from .mixins import StaffRequiredMixin
from .registry import REGISTRO, REGISTRO_POR_SLUG, grupos_para_sidebar


def _obtener_recurso(slug):
    recurso = REGISTRO_POR_SLUG.get(slug)
    if recurso is None:
        raise Http404
    return recurso


def _valor_para_mostrar(objeto, campo):
    """Usa get_<campo>_display() si el campo tiene choices; si no, el valor crudo."""
    metodo_display = getattr(objeto, f'get_{campo}_display', None)
    if callable(metodo_display):
        return metodo_display()
    return getattr(objeto, campo)


class PanelHomeView(StaffRequiredMixin, TemplateView):
    """Landing del panel: una tarjeta por grupo del registro + los pendientes."""

    template_name = 'panel_admin/home.html'

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        grupos = grupos_para_sidebar()
        tarjetas = [
            {
                'grupo': grupo,
                'icono': recursos[0].icono,
                'descripcion': f'{len(recursos)} tipo(s) de contenido administrable',
                'disponible': True,
                'recursos': recursos,
            }
            for grupo, recursos in grupos.items()
        ]
        contexto['tarjetas'] = tarjetas
        return contexto


class RecursoListView(StaffRequiredMixin, ListView):
    template_name = 'panel_admin/recurso_lista.html'
    paginate_by = 30
    context_object_name = 'objetos'

    def dispatch(self, request, *args, **kwargs):
        self.recurso = _obtener_recurso(kwargs['slug'])
        if self.recurso.singleton:
            objeto, _creado = self.recurso.modelo.objects.get_or_create(pk=1)
            return redirect('panel_admin:editar', slug=self.recurso.slug, pk=objeto.pk)
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return self.recurso.modelo.objects.all()

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto['recurso'] = self.recurso
        contexto['filas'] = [
            (objeto, [_valor_para_mostrar(objeto, campo) for campo in self.recurso.campos_lista])
            for objeto in contexto['objetos']
        ]
        return contexto


class RecursoFormMixin(StaffRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        self.recurso = _obtener_recurso(kwargs['slug'])
        if self.recurso.solo_lectura:
            raise Http404
        self.model = self.recurso.modelo
        return super().dispatch(request, *args, **kwargs)

    def get_template_names(self):
        return [self.recurso.template_form]

    def get_queryset(self):
        return self.recurso.modelo.objects.all()

    def get_form_class(self):
        campos = self.recurso.campos_form or '__all__'
        return modelform_factory(self.recurso.modelo, fields=campos)

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto['recurso'] = self.recurso
        return contexto

    def form_valid(self, form):
        respuesta = super().form_valid(form)
        messages.success(self.request, f'{self.recurso.nombre_plural}: guardado correctamente.')
        return respuesta

    def get_success_url(self):
        if self.recurso.singleton:
            return reverse('panel_admin:editar', kwargs={'slug': self.recurso.slug, 'pk': self.object.pk})
        return reverse('panel_admin:lista', kwargs={'slug': self.recurso.slug})


class RecursoCreateView(RecursoFormMixin, CreateView):
    def dispatch(self, request, *args, **kwargs):
        # Un singleton no se "crea": ya existe (pk=1) y RecursoListView
        # redirige directo a editarlo. Se valida antes de tocar la base.
        if _obtener_recurso(kwargs['slug']).singleton:
            raise Http404
        return super().dispatch(request, *args, **kwargs)


class RecursoUpdateView(RecursoFormMixin, UpdateView):
    pk_url_kwarg = 'pk'


class RecursoDeleteView(StaffRequiredMixin, DeleteView):
    template_name = 'panel_admin/recurso_confirmar_eliminar.html'
    pk_url_kwarg = 'pk'

    def dispatch(self, request, *args, **kwargs):
        self.recurso = _obtener_recurso(kwargs['slug'])
        if self.recurso.solo_lectura or self.recurso.singleton:
            raise Http404
        self.model = self.recurso.modelo
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return self.recurso.modelo.objects.all()

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto['recurso'] = self.recurso
        return contexto

    def get_success_url(self):
        messages.success(self.request, f'{self.recurso.nombre_plural}: eliminado correctamente.')
        return reverse('panel_admin:lista', kwargs={'slug': self.recurso.slug})
