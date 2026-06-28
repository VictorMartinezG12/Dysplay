import logging

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST

from recompensas.services import SaldoInsuficienteError
from .models import Avatar, Item, InventarioAvatar
from .services import (
    ItemYaPoseidoError,
    SlotInvalidoError,
    colocar_item_en_casa,
    comprar_item_para_avatar,
    comprar_y_equipar_item,
    desequipar_item_avatar,
    equipar_item_avatar,
    obtener_items_colocados_casa,
    obtener_items_tienda_casa,
    obtener_o_crear_casa,
)

logger = logging.getLogger(__name__)


def _construir_contexto_armario(avatar_obj):
    """Construye el contexto compartido del armario ("paper doll").

    Usado tanto por `personalizar_avatar` (acceso directo por URL) como por
    `casa_avatar` (modal de armario dentro de la habitación), para que ambos
    rendericen exactamente el mismo partial `avatar/_armario_contenido.html`
    sin duplicar la lógica de armado de categorías/inventario.

    Args:
        avatar_obj: instancia de `Avatar` del usuario actual.

    Returns:
        dict: contexto listo para mezclar en el render de la vista que lo
        invoque (claves: items_por_cat, categorias_display,
        subcategorias_accesorio, equipados_ids, avatar_equipados,
        avatar_accesorios, ids_poseidos).
    """
    # Definir zonas del cuerpo y sus nombres amigables para la UI del armario.
    # Antes 'ropa_superior'/'ropa_inferior'/'calzado' se agrupaban en una sola
    # pestaña 'ropa'; el nuevo armario tipo "paper doll" las separa por zona
    # del cuerpo para que cada una tenga su propio par de sub-tabs Tengo/Tienda.
    categorias_display = {
        'cabello': 'Cabello',
        'ropa_superior': 'Torso superior',
        'ropa_inferior': 'Torso inferior',
        'calzado': 'Calzado',
        'accesorio': 'Accesorios',
    }

    # Sub-secciones independientes dentro de la pestaña "Accesorios": cada una
    # puede equiparse simultáneamente (ver `Item.SUBCATEGORIA_ACCESORIO_CHOICES`).
    subcategorias_accesorio = {
        'sombrero': 'Sombrero',
        'gafas': 'Gafas',
        'reloj': 'Reloj',
        'otro': 'Otros',
    }

    # Obtener items organizados por zona del cuerpo. El valor heredado 'ropa'
    # (categoría genérica anterior a la separación superior/inferior) se
    # incluye dentro de 'ropa_superior' para no perder ítems antiguos.
    items_raw = Item.objects.filter(activo=True)
    items_crudos_por_cat = {
        'cabello': items_raw.filter(categoria='cabello'),
        'ropa_superior': items_raw.filter(categoria__in=['ropa', 'ropa_superior']),
        'ropa_inferior': items_raw.filter(categoria='ropa_inferior'),
        'calzado': items_raw.filter(categoria='calzado'),
        'accesorio': items_raw.filter(categoria='accesorio'),
    }

    inventario = InventarioAvatar.objects.filter(avatar=avatar_obj, equipado=True).select_related('item')
    equipados_ids = [inv.item.id for inv in inventario]
    avatar_equipados = {inv.item.categoria: inv.item for inv in inventario}
    # Dict por subcategoría para que sombrero/gafas/reloj no se pisen entre
    # sí cuando hay varios accesorios equipados a la vez (ver `avatar_equipados`
    # arriba, que sigue colapsando a 1 sola entrada por categoría).
    avatar_accesorios = {
        inv.item.subcategoria or 'otro': inv.item
        for inv in inventario
        if inv.item.categoria == 'accesorio'
    }

    # Ids de ítems que el usuario ya posee (desbloqueados), equipados o no.
    # Permite distinguir en el template la pestaña "Tengo" (poseído) de la
    # pestaña "Tienda" (no poseído, con precio) sin tocar el modelo.
    ids_poseidos = set(
        InventarioAvatar.objects.filter(avatar=avatar_obj, desbloqueado=True)
        .values_list('item_id', flat=True)
    )

    # Pre-separar cada zona en listas "tengo"/"tienda" (y, para accesorios,
    # también por subcategoría) para que el template use el idiom nativo
    # `{% for %}{% empty %}` en vez de filtrar ítem por ítem sin mostrar
    # ningún mensaje cuando una lista queda vacía (bug reportado: el armario
    # se veía completamente en blanco para un usuario sin ítems poseídos).
    items_por_cat = {}
    for cat_id, queryset in items_crudos_por_cat.items():
        items_lista = list(queryset)
        if cat_id == 'accesorio':
            items_por_cat[cat_id] = {
                sub: {
                    'tengo': [i for i in items_lista if i.subcategoria == sub and i.id in ids_poseidos],
                    'tienda': [i for i in items_lista if i.subcategoria == sub and i.id not in ids_poseidos],
                }
                for sub in subcategorias_accesorio
            }
        else:
            items_por_cat[cat_id] = {
                'tengo': [i for i in items_lista if i.id in ids_poseidos],
                'tienda': [i for i in items_lista if i.id not in ids_poseidos],
            }

    return {
        'items_por_cat': items_por_cat,
        'categorias_display': categorias_display,
        'subcategorias_accesorio': subcategorias_accesorio,
        'equipados_ids': equipados_ids,
        'avatar_equipados': avatar_equipados,
        'avatar_accesorios': avatar_accesorios,
        'ids_poseidos': ids_poseidos,
    }


@login_required
def personalizar_avatar(request):
    avatar_obj, created = Avatar.objects.get_or_create(usuario=request.user)

    if request.method == 'POST':
        item_id = request.POST.get('item_id')
        if item_id:
            try:
                equipar_item_avatar(avatar_obj, item_id)
            except Item.DoesNotExist:
                logger.warning("Intento de equipar un ítem inexistente: %s", item_id)

        return redirect('avatar:personalizar')

    contexto = _construir_contexto_armario(avatar_obj)
    contexto['avatar'] = avatar_obj

    return render(request, 'avatar/personalizar.html', contexto)


@login_required
def casa_avatar(request):
    """Muestra la casa/habitación personalizable del avatar del usuario."""
    avatar_obj, _creado = Avatar.objects.get_or_create(usuario=request.user)
    casa_obj = obtener_o_crear_casa(avatar_obj)

    items_disponibles = InventarioAvatar.objects.filter(
        avatar=avatar_obj,
        item__categoria__in=['habitacion', 'fondo', 'mueble', 'decoracion'],
    ).select_related('item')

    items_tienda = obtener_items_tienda_casa(avatar_obj)
    items_colocados = obtener_items_colocados_casa(casa_obj)

    contexto = _construir_contexto_armario(avatar_obj)
    contexto.update({
        'avatar': avatar_obj,
        'casa': casa_obj,
        'items_disponibles': items_disponibles,
        'items_tienda': items_tienda,
        'items_colocados': items_colocados,
    })

    return render(request, 'avatar/casa.html', contexto)


@login_required
@require_POST
def comprar_item(request):
    """Procesa la compra de un ítem para el avatar/casa del usuario."""
    item_id = request.POST.get('item_id')
    slot = request.POST.get('slot') or None

    if not item_id:
        return JsonResponse({'exito': False, 'mensaje': 'Falta el ítem a comprar.'}, status=400)

    avatar_obj, _creado = Avatar.objects.get_or_create(usuario=request.user)

    try:
        comprar_item_para_avatar(request.user, avatar_obj, item_id, slot=slot)
        return JsonResponse({'exito': True, 'monedas': request.user.monedas})
    except Item.DoesNotExist:
        return JsonResponse({'exito': False, 'mensaje': 'El ítem no existe.'}, status=404)
    except ItemYaPoseidoError:
        return JsonResponse({'exito': False, 'mensaje': 'Ya tienes este ítem.'}, status=400)
    except SlotInvalidoError:
        return JsonResponse({'exito': False, 'mensaje': 'Ubicación no válida.'}, status=400)
    except SaldoInsuficienteError:
        return JsonResponse({'exito': False, 'mensaje': 'No tienes suficientes monedas.'}, status=400)
    except Exception:
        logger.error("Error al procesar la compra del ítem %s", item_id, exc_info=True)
        return JsonResponse({'exito': False, 'mensaje': 'Ocurrió un error al procesar la compra.'}, status=500)


@login_required
@require_POST
def colocar_item(request):
    """Coloca un ítem de habitación/fondo ya posedido en un espacio de la casa del usuario."""
    item_id = request.POST.get('item_id')
    slot = request.POST.get('slot')

    if not item_id or not slot:
        return JsonResponse({'exito': False, 'mensaje': 'Faltan datos para colocar el ítem.'}, status=400)

    avatar_obj, _creado = Avatar.objects.get_or_create(usuario=request.user)

    try:
        colocar_item_en_casa(avatar_obj, item_id, slot)
        return JsonResponse({'exito': True, 'monedas': request.user.monedas})
    except Item.DoesNotExist:
        return JsonResponse({'exito': False, 'mensaje': 'El ítem no existe.'}, status=404)
    except SlotInvalidoError:
        return JsonResponse({'exito': False, 'mensaje': 'Ubicación no válida.'}, status=400)
    except InventarioAvatar.DoesNotExist:
        return JsonResponse({'exito': False, 'mensaje': 'Todavía no tienes este ítem.'}, status=400)
    except Exception:
        logger.error("Error al colocar el ítem %s en la casa", item_id, exc_info=True)
        return JsonResponse({'exito': False, 'mensaje': 'Ocurrió un error al colocar el ítem.'}, status=500)


@login_required
@require_POST
def equipar_item(request):
    """Equipa (vía AJAX) un ítem ya posedido en el avatar del usuario."""
    item_id = request.POST.get('item_id')

    if not item_id:
        return JsonResponse({'exito': False, 'mensaje': 'Falta el ítem a equipar.'}, status=400)

    avatar_obj, _creado = Avatar.objects.get_or_create(usuario=request.user)

    try:
        inventario = equipar_item_avatar(avatar_obj, item_id)
        item = inventario.item
        return JsonResponse({
            'exito': True,
            'categoria': item.categoria,
            'subcategoria': item.subcategoria,
            'imagen_url': item.imagen_url_segura,
        })
    except Item.DoesNotExist:
        return JsonResponse({'exito': False, 'mensaje': 'El ítem no existe.'}, status=404)
    except Exception:
        logger.error("Error al equipar el ítem %s", item_id, exc_info=True)
        return JsonResponse({'exito': False, 'mensaje': 'Ocurrió un error al equipar el ítem.'}, status=500)


@login_required
@require_POST
def comprar_y_equipar(request):
    """Compra un ítem y lo equipa inmediatamente en un solo paso (AJAX)."""
    item_id = request.POST.get('item_id')

    if not item_id:
        return JsonResponse({'exito': False, 'mensaje': 'Falta el ítem a comprar.'}, status=400)

    avatar_obj, _creado = Avatar.objects.get_or_create(usuario=request.user)

    try:
        inventario = comprar_y_equipar_item(request.user, avatar_obj, item_id)
        item = inventario.item
        return JsonResponse({
            'exito': True,
            'monedas': request.user.monedas,
            'categoria': item.categoria,
            'subcategoria': item.subcategoria,
            'imagen_url': item.imagen_url_segura,
        })
    except Item.DoesNotExist:
        return JsonResponse({'exito': False, 'mensaje': 'El ítem no existe.'}, status=404)
    except ItemYaPoseidoError:
        return JsonResponse({'exito': False, 'mensaje': 'Ya tienes este ítem.'}, status=400)
    except SaldoInsuficienteError:
        return JsonResponse({'exito': False, 'mensaje': 'No tienes suficientes monedas.'}, status=400)
    except Exception:
        logger.error("Error al comprar y equipar el ítem %s", item_id, exc_info=True)
        return JsonResponse({'exito': False, 'mensaje': 'Ocurrió un error al procesar la compra.'}, status=500)


@login_required
def desequipar_item(request):
    """Quita un ítem equipado del avatar sin eliminarlo del inventario."""
    if request.method != 'POST':
        return JsonResponse({'exito': False}, status=405)

    item_id = request.POST.get('item_id')
    if not item_id:
        return JsonResponse({'exito': False, 'mensaje': 'Falta el ítem a desequipar.'}, status=400)

    try:
        avatar_obj = Avatar.objects.get(usuario=request.user)
        resultado = desequipar_item_avatar(avatar_obj, item_id)
        return JsonResponse({'exito': True, **resultado})
    except Avatar.DoesNotExist:
        return JsonResponse({'exito': False, 'mensaje': 'Avatar no encontrado.'}, status=404)
    except Exception:
        logger.error("Error al desequipar el ítem %s", item_id, exc_info=True)
        return JsonResponse({'exito': False, 'mensaje': 'Ocurrió un error al quitar el ítem.'}, status=500)
