from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from .models import Avatar, Item, InventarioAvatar

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
