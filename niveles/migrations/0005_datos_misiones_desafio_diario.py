# Migración de datos: agrega ejercicios de pronunciación (MisionVocabulario)
# para los niveles 2 y 3, que actualmente no tienen ninguno.
#
# Es necesaria para el Módulo E (Desafío Diario): la generación del desafío
# del día elige 1 ejercicio obligatorio + hasta 3 opcionales al azar entre
# todas las MisionVocabulario existentes, y antes de esta migración solo
# existía 1 (nivel 1). No modifica ni elimina la misión existente.

from django.db import migrations

NUEVAS_MISIONES = [
    {
        'nivel_numero': 2,
        'palabra_objetivo': 'flor',
        'tipo': 'VOZ',
        'frase_historia': 'La abeja vuela cerca de la flor amarilla.',
    },
    {
        'nivel_numero': 3,
        'palabra_objetivo': 'sapo',
        'tipo': 'VOZ',
        'frase_historia': 'El sapo salta sobre la piedra mojada.',
    },
    {
        'nivel_numero': 1,
        'palabra_objetivo': 'león',
        'tipo': 'VOZ',
        'frase_historia': 'El león ruge fuerte en la selva verde.',
    },
]


def crear_misiones(apps, schema_editor):
    Nivel = apps.get_model('niveles', 'Nivel')
    MisionVocabulario = apps.get_model('niveles', 'MisionVocabulario')

    for datos in NUEVAS_MISIONES:
        try:
            nivel = Nivel.objects.get(numero=datos['nivel_numero'])
        except Nivel.DoesNotExist:
            continue

        MisionVocabulario.objects.get_or_create(
            nivel=nivel,
            palabra_objetivo=datos['palabra_objetivo'],
            defaults={
                'tipo': datos['tipo'],
                'frase_historia': datos['frase_historia'],
            },
        )


def eliminar_misiones(apps, schema_editor):
    MisionVocabulario = apps.get_model('niveles', 'MisionVocabulario')
    palabras = [datos['palabra_objetivo'] for datos in NUEVAS_MISIONES]
    MisionVocabulario.objects.filter(palabra_objetivo__in=palabras).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('niveles', '0004_datos_zona_mapa_aventura'),
    ]

    operations = [
        migrations.RunPython(crear_misiones, eliminar_misiones),
    ]
