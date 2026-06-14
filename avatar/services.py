"""
Capa de servicios del módulo `avatar`.

Contiene la lógica de negocio relacionada con la casa del avatar y la
compra de ítems de la tienda. Las vistas deben delegar en estas funciones
para mantenerse delgadas.
"""

import logging

from django.db import transaction

from recompensas.services import cobrar_monedas, SaldoInsuficienteError
from .models import CasaAvatar, InventarioAvatar, Item

# Categorías de ítems que pueden colocarse en la casa del avatar.
CATEGORIAS_CASA = ('habitacion', 'fondo')

logger = logging.getLogger(__name__)

# Campos de CasaAvatar que pueden recibir un ítem (slots de habitación).
SLOTS_CASA_VALIDOS = ('cama', 'cuadro', 'alfombra', 'lampara')


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
            setattr(casa, slot, item)
            casa.save(update_fields=[slot])

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
    setattr(casa, slot, item)
    casa.save(update_fields=[slot])

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
