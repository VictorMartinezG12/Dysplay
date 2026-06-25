# Generated manually: migra los datos de los 4 campos fijos de CasaAvatar
# (cama, cuadro, alfombra, lampara) al nuevo modelo ItemColocado, antes de
# eliminar esos campos en la migración 0008.

import logging

from django.db import migrations

logger = logging.getLogger(__name__)

# Slots que existían como campos fijos en CasaAvatar.
SLOTS_VIEJOS = ('cama', 'cuadro', 'alfombra', 'lampara')


def migrar_a_itemcolocado(apps, schema_editor):
    """Crea un `ItemColocado` por cada campo de `CasaAvatar` que tenga un
    ítem asignado (cama_id/cuadro_id/alfombra_id/lampara_id no nulos)."""
    CasaAvatar = apps.get_model('avatar', 'CasaAvatar')
    ItemColocado = apps.get_model('avatar', 'ItemColocado')

    for casa in CasaAvatar.objects.all():
        for slot in SLOTS_VIEJOS:
            item_id = getattr(casa, f'{slot}_id')
            if item_id is not None:
                ItemColocado.objects.update_or_create(
                    casa=casa, slot=slot, defaults={'item_id': item_id}
                )


def revertir_a_campos_viejos(apps, schema_editor):
    """Repuebla los 4 campos fijos de `CasaAvatar` a partir de los
    `ItemColocado` existentes para esos slots (reverso de la migración)."""
    CasaAvatar = apps.get_model('avatar', 'CasaAvatar')
    ItemColocado = apps.get_model('avatar', 'ItemColocado')

    for casa in CasaAvatar.objects.all():
        actualizado = False
        for slot in SLOTS_VIEJOS:
            try:
                colocado = ItemColocado.objects.get(casa=casa, slot=slot)
                setattr(casa, f'{slot}_id', colocado.item_id)
                actualizado = True
            except ItemColocado.DoesNotExist:
                continue
        if actualizado:
            casa.save()


class Migration(migrations.Migration):

    dependencies = [
        ('avatar', '0006_itemcolocado_item_subcategoria'),
    ]

    operations = [
        migrations.RunPython(migrar_a_itemcolocado, revertir_a_campos_viejos),
    ]
