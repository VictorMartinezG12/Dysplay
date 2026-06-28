"""
Capa de servicios del módulo `avatar`.

Contiene la lógica de negocio relacionada con la casa del avatar y la
compra de ítems de la tienda. Las vistas deben delegar en estas funciones
para mantenerse delgadas.
"""

import logging

from django.db import transaction

from recompensas.services import cobrar_monedas
from .models import CasaAvatar, InventarioAvatar, Item, ItemColocado

# Categorías de ítems que pueden colocarse en la casa del avatar. Se amplía
# con 'mueble' y 'decoracion' (ya existían en Item.CATEGORIA_CHOICES pero no
# se usaban en la tienda de casa) para que mesa/estante/cama/silla tengan
# ítems disponibles en la tienda.
CATEGORIAS_CASA = ('habitacion', 'fondo', 'mueble', 'decoracion')

logger = logging.getLogger(__name__)

# Slots de `ItemColocado` que aceptan un ítem colocado en la casa. El slot
# 'armario' no está acá: no coloca un ítem, abre el editor de personaje.
SLOTS_CASA_VALIDOS = ('mesa', 'estante', 'cama', 'silla', 'cuadro', 'lampara', 'alfombra')


class ItemYaPoseidoError(Exception):
    """Se lanza cuando el usuario intenta comprar un ítem que ya posee."""
    pass


class SlotInvalidoError(Exception):
    """Se lanza cuando el `slot` recibido no corresponde a un campo válido de CasaAvatar."""
    pass


def obtener_o_crear_casa(avatar_obj):
    """
    Obtiene la `CasaAvatar` de un avatar, creándola si no existe.

    Args:
        avatar_obj: instancia de `Avatar` cuya casa se obtiene.

    Returns:
        CasaAvatar: la casa del avatar (existente o recién creada).
    """
    casa, _creada = CasaAvatar.objects.get_or_create(avatar=avatar_obj)
    return casa


def comprar_item_para_avatar(usuario, avatar_obj, item_id, slot=None):
    """
    Procesa la compra de un ítem para el avatar de un usuario.

    Valida que el ítem exista, que el usuario no lo posea ya en su
    inventario, cobra el precio del ítem en monedas (de forma atómica vía
    `recompensas.services.cobrar_monedas`) y, si el cobro es exitoso,
    desbloquea el ítem en `InventarioAvatar`. Si se indica `slot` (uno de
    `SLOTS_CASA_VALIDOS`), también asigna el ítem comprado a ese campo de
    la `CasaAvatar` del usuario.

    Args:
        usuario: instancia de `UsuarioCustom` que realiza la compra.
        avatar_obj: instancia de `Avatar` del usuario.
        item_id (int): identificador del `Item` a comprar.
        slot (str | None): nombre del campo de `CasaAvatar` donde colocar
            el ítem comprado (cama, cuadro, alfombra o lampara), o `None`
            si el ítem no se asigna a la casa.

    Returns:
        InventarioAvatar: el registro de inventario creado/actualizado.

    Raises:
        Item.DoesNotExist: si no existe un ítem activo con `item_id`.
        ItemYaPoseidoError: si el usuario ya tiene el ítem desbloqueado.
        SlotInvalidoError: si `slot` no es uno de `SLOTS_CASA_VALIDOS`.
        SaldoInsuficienteError: si el usuario no tiene monedas suficientes.
    """
    if slot is not None and slot not in SLOTS_CASA_VALIDOS:
        raise SlotInvalidoError(f"Slot inválido: {slot}")

    item = Item.objects.get(pk=item_id, activo=True)

    ya_poseido = InventarioAvatar.objects.filter(
        avatar=avatar_obj, item=item, desbloqueado=True
    ).exists()
    if ya_poseido:
        raise ItemYaPoseidoError(f"El usuario {usuario.pk} ya posee el ítem {item.pk}")

    with transaction.atomic():
        # El cobro lanza SaldoInsuficienteError si no hay saldo; en ese
        # caso no se crea ningún registro de inventario.
        cobrar_monedas(usuario, item.precio_monedas, concepto=f"Compra de ítem: {item.nombre}")

        inventario, _creado = InventarioAvatar.objects.get_or_create(
            avatar=avatar_obj, item=item,
            defaults={'desbloqueado': True}
        )
        if not inventario.desbloqueado:
            inventario.desbloqueado = True
            inventario.save(update_fields=['desbloqueado'])

        if slot is not None:
            casa = obtener_o_crear_casa(avatar_obj)
            ItemColocado.objects.update_or_create(
                casa=casa, slot=slot, defaults={'item': item}
            )

    logger.info(
        "Compra de ítem completada: usuario=%s item=%s slot=%s",
        usuario.pk, item.pk, slot,
    )

    return inventario


def colocar_item_en_casa(avatar_obj, item_id, slot):
    """
    Asigna un ítem de habitación/fondo ya posedido por el usuario a un
    espacio (slot) de su `CasaAvatar`.

    A diferencia de `comprar_item_para_avatar`, esta función no realiza
    ningún cobro: solo reubica un ítem que el usuario ya tiene desbloqueado
    en su inventario.

    Args:
        avatar_obj: instancia de `Avatar` del usuario.
        item_id (int): identificador del `Item` a colocar.
        slot (str): nombre del campo de `CasaAvatar` donde colocar el ítem
            (cama, cuadro, alfombra o lampara).

    Returns:
        CasaAvatar: la casa actualizada del avatar.

    Raises:
        Item.DoesNotExist: si no existe un ítem activo con `item_id`.
        SlotInvalidoError: si `slot` no es uno de `SLOTS_CASA_VALIDOS`.
        InventarioAvatar.DoesNotExist: si el usuario no posee el ítem.
    """
    if slot not in SLOTS_CASA_VALIDOS:
        raise SlotInvalidoError(f"Slot inválido: {slot}")

    item = Item.objects.get(pk=item_id, activo=True)

    InventarioAvatar.objects.get(avatar=avatar_obj, item=item, desbloqueado=True)

    casa = obtener_o_crear_casa(avatar_obj)
    ItemColocado.objects.update_or_create(
        casa=casa, slot=slot, defaults={'item': item}
    )

    logger.info(
        "Ítem colocado en la casa: avatar=%s item=%s slot=%s",
        avatar_obj.pk, item.pk, slot,
    )

    return casa


def obtener_items_tienda_casa(avatar_obj):
    """
    Obtiene los ítems de habitación/fondo disponibles en la tienda que el
    usuario aún no posee.

    Args:
        avatar_obj: instancia de `Avatar` cuyo inventario se usa para
            excluir los ítems ya posedidos.

    Returns:
        QuerySet[Item]: ítems activos de categoría 'habitacion' o 'fondo'
        que el avatar todavía no tiene desbloqueados, ordenados por precio.
    """
    ids_poseidos = InventarioAvatar.objects.filter(
        avatar=avatar_obj,
        desbloqueado=True,
    ).values_list('item_id', flat=True)

    return Item.objects.filter(
        categoria__in=CATEGORIAS_CASA,
        activo=True,
    ).exclude(id__in=ids_poseidos).order_by('precio_monedas')


def obtener_items_colocados_casa(casa):
    """
    Devuelve los ítems colocados en una `CasaAvatar`, indexados por slot.

    Args:
        casa: instancia de `CasaAvatar` cuyos ítems colocados se consultan.

    Returns:
        dict[str, Item]: mapeo `{slot: item}` con un ítem por cada slot de
        `ItemColocado.SLOT_CHOICES` que tenga algo asignado. Los slots
        vacíos simplemente no aparecen como clave.
    """
    return {
        colocado.slot: colocado.item
        for colocado in casa.items_colocados.select_related('item')
    }


def equipar_item_avatar(avatar_obj, item_id):
    """
    Equipa un ítem en el avatar, desequipando solo lo que comparte su misma
    clave de exclusividad.

    Para la mayoría de categorías (cabello, ropa_superior, ropa_inferior,
    calzado, etc.) la exclusividad sigue siendo "uno por categoría", igual
    que antes. Para accesorios, la exclusividad es más fina: se calcula por
    `(categoria='accesorio', subcategoria=item.subcategoria)`, de modo que
    un sombrero nuevo solo desequipa el sombrero anterior, sin afectar a las
    gafas ni al reloj que el avatar ya tenga puestos — así pueden coexistir
    varios accesorios de distinta subcategoría a la vez.

    Args:
        avatar_obj: instancia de `Avatar` cuyo inventario se actualiza.
        item_id (int): identificador del `Item` a equipar.

    Returns:
        InventarioAvatar: el registro de inventario recién equipado.

    Raises:
        Item.DoesNotExist: si no existe un ítem activo con `item_id`.
    """
    item = Item.objects.get(pk=item_id, activo=True)

    filtro_exclusividad = {'item__categoria': item.categoria}
    if item.categoria == 'accesorio':
        filtro_exclusividad['item__subcategoria'] = item.subcategoria

    with transaction.atomic():
        InventarioAvatar.objects.filter(
            avatar=avatar_obj, **filtro_exclusividad
        ).update(equipado=False)

        inventario, _creado = InventarioAvatar.objects.get_or_create(
            avatar=avatar_obj, item=item
        )
        inventario.equipado = True
        inventario.save(update_fields=['equipado'])

    logger.info(
        "Ítem equipado: avatar=%s item=%s categoria=%s subcategoria=%s",
        avatar_obj.pk, item.pk, item.categoria, item.subcategoria,
    )

    return inventario


def desequipar_item_avatar(avatar_obj, item_id):
    """
    Quita un ítem equipado del avatar sin eliminarlo del inventario.

    Args:
        avatar_obj: instancia de `Avatar` cuyo inventario se actualiza.
        item_id (int): identificador del `Item` a desequipar.

    Returns:
        dict con 'categoria' y 'subcategoria' del ítem, para que el frontend
        pueda eliminar la capa visual correspondiente.

    Raises:
        InventarioAvatar.DoesNotExist: si el ítem no está en el inventario del avatar.
    """
    inventario = InventarioAvatar.objects.get(avatar=avatar_obj, item_id=item_id)
    inventario.equipado = False
    inventario.save(update_fields=['equipado'])
    logger.info(
        "Ítem desequipado: avatar=%s item=%s",
        avatar_obj.pk, inventario.item.pk,
    )
    return {'categoria': inventario.item.categoria, 'subcategoria': inventario.item.subcategoria}


def comprar_y_equipar_item(usuario, avatar_obj, item_id):
    """
    Compra un ítem para el avatar y lo equipa inmediatamente.

    Combina `comprar_item_para_avatar` (sin slot de casa, ya que es un ítem
    de armario) con `equipar_item_avatar`, para el flujo de "comprar y
    equipar en un solo paso" desde la tienda del armario.

    Args:
        usuario: instancia de `UsuarioCustom` que realiza la compra.
        avatar_obj: instancia de `Avatar` del usuario.
        item_id (int): identificador del `Item` a comprar y equipar.

    Returns:
        InventarioAvatar: el registro de inventario comprado y equipado.

    Raises:
        Item.DoesNotExist: si no existe un ítem activo con `item_id`.
        ItemYaPoseidoError: si el usuario ya tiene el ítem desbloqueado.
        SaldoInsuficienteError: si el usuario no tiene monedas suficientes.
    """
    comprar_item_para_avatar(usuario, avatar_obj, item_id, slot=None)
    return equipar_item_avatar(avatar_obj, item_id)
