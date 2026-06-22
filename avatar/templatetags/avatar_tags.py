from django import template

from avatar.models import CaraAvatar

register = template.Library()


@register.simple_tag
def caras_avatar():
    """Dict {estado: {'normal': url, 'parpadeo': url|None}} para `_svg_personaje.html`.

    Si una emoción no tiene fila en `CaraAvatar` todavía, usa la cara
    'neutral' como respaldo (si tampoco existe, esa emoción simplemente no
    se muestra — el panel de administración, Fase 2, es donde se sube esto).
    """
    filas = {fila.estado: fila for fila in CaraAvatar.objects.all()}
    neutral = filas.get('neutral')

    resultado = {}
    for estado, _etiqueta in CaraAvatar._meta.get_field('estado').choices:
        fila = filas.get(estado, neutral)
        if fila is None:
            continue
        resultado[estado] = {
            'normal': fila.imagen.url,
            'parpadeo': fila.imagen_parpadeo.url if fila.imagen_parpadeo else None,
        }
    return resultado
