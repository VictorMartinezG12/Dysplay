# Migración de datos: crea el TipoInsignia "Aventurero Diario", otorgado al
# completar un desafío diario completo (criterio 'desafio_diario', agregado
# en la migración 0002 como parte del Módulo E).

from django.db import migrations


def crear_insignia_desafio_diario(apps, schema_editor):
    TipoInsignia = apps.get_model('recompensas', 'TipoInsignia')
    TipoInsignia.objects.get_or_create(
        criterio='desafio_diario',
        defaults={
            'nombre': 'Aventurero Diario',
            'descripcion': 'Completaste un desafío diario completo. ¡El reino te lo agradece!',
            'valor_umbral': 1,
        },
    )


def eliminar_insignia_desafio_diario(apps, schema_editor):
    TipoInsignia = apps.get_model('recompensas', 'TipoInsignia')
    TipoInsignia.objects.filter(criterio='desafio_diario').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('recompensas', '0002_alter_tipoinsignia_criterio'),
    ]

    operations = [
        migrations.RunPython(crear_insignia_desafio_diario, eliminar_insignia_desafio_diario),
    ]
