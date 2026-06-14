# Migración de datos: asigna zona/orden/narrativa a los niveles existentes
# del Mapa de Aventura (Módulo D del Master Plan).
#
# Solo existen 3 niveles reales en BD (numero=1,2,3). Todos pertenecen al
# Bosque Encantado, con orden_en_zona == numero. El nivel 1 recibe además la
# narrativa de introducción del Bosque Encantado; los niveles 2 y 3 dejan
# narrativa_intro=''.

from django.db import migrations

NARRATIVA_BOSQUE_NIVEL_1 = (
    "Las vocales mágicas del bosque se han perdido entre los árboles. "
    "¡El reino necesita que las encuentres pronunciándolas correctamente!"
)


def asignar_zona_bosque_encantado(apps, schema_editor):
    """Asigna zona/orden/narrativa de Bosque Encantado a los niveles 1, 2 y 3."""
    Nivel = apps.get_model('niveles', 'Nivel')

    for nivel in Nivel.objects.filter(numero__in=[1, 2, 3]):
        nivel.zona = 'bosque_encantado'
        nivel.orden_en_zona = nivel.numero
        if nivel.numero == 1:
            nivel.narrativa_intro = NARRATIVA_BOSQUE_NIVEL_1
        nivel.save(update_fields=['zona', 'orden_en_zona', 'narrativa_intro'])


class Migration(migrations.Migration):

    dependencies = [
        ('niveles', '0003_nivel_narrativa_intro_nivel_orden_en_zona_nivel_zona'),
    ]

    operations = [
        migrations.RunPython(asignar_zona_bosque_encantado, migrations.RunPython.noop),
    ]
