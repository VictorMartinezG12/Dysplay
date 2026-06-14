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
    obtener_items_tienda_casa,
    obtener_o_crear_casa,
)

logger = logging.getLogger(__name__)

@login_required
def personalizar_avatar(request):
    avatar_obj, created = Avatar.objects.get_or_create(usuario=request.user)
    
    if request.method == 'POST':
        item_id = request.POST.get('item_id')
        if item_id:
            try:
                item_to_equip = Item.objects.get(id=item_id)
                # Lógica: Solo un item por categoría equipado a la vez
                InventarioAvatar.objects.filter(
                    avatar=avatar_obj, 
                    item__categoria=item_to_equip.categoria
                ).update(equipado=False)
                
                # Equipar nuevo
                inv, _ = InventarioAvatar.objects.get_or_create(avatar=avatar_obj, item=item_to_equip)
                inv.equipado = True
                inv.save()
            except Item.DoesNotExist:
                pass
        
        return redirect('avatar:personalizar')

    # Definir categorías y sus nombres amigables para la UI
    categorias_display = {
        'cabello': 'Cabello',
        'ropa': 'Ropa',
        'accesorio': 'Accesorios',
    }

    # Obtener items organizados por categorías de visualización
    # Agrupamos ropa_superior, ropa_inferior y calzado bajo 'ropa' para el usuario
    items_raw = Item.objects.filter(activo=True)
    items_por_cat = {
        'cabello': items_raw.filter(categoria='cabello'),
        'ropa': items_raw.filter(categoria__in=['ropa', 'ropa_superior', 'ropa_inferior', 'calzado']),
        'accesorio': items_raw.filter(categoria='accesorio'),
    }
    
    inventario = InventarioAvatar.objects.filter(avatar=avatar_obj, equipado=True).select_related('item')
    equipados_ids = [inv.item.id for inv in inventario]
    avatar_equipados = {inv.item.categoria: inv.item for inv in inventario}

    return render(request, 'avatar/personalizar.html', {
        'avatar': avatar_obj,
        'items_por_cat': items_por_cat,
        'categorias_display': categorias_display,
        'equipados_ids': equipados_ids,
        'avatar_equipados': avatar_equipados
    })


@login_required
def casa_avatar(request):
    """Muestra la casa/habitación personalizable del avatar del usuario."""
    avatar_obj, _creado = Avatar.objects.get_or_create(usuario=request.user)
    casa_obj = obtener_o_crear_casa(avatar_obj)

    items_disponibles = InventarioAvatar.objects.filter(
        avatar=avatar_obj,
        item__categoria__in=['habitacion', 'fondo'],
    ).select_related('item')

    items_tienda = obtener_items_tienda_casa(avatar_obj)

    return render(request, 'avatar/casa.html', {
        'avatar': avatar_obj,
        'casa': casa_obj,
        'items_disponibles': items_disponibles,
        'items_tienda': items_tienda,
    })


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
