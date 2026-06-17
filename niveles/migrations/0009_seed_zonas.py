from django.db import migrations

# Mismas 5 zonas y orden fijo que niveles.services.ZONAS_MAPA_AVENTURA — se
# hardcodean aquí (en vez de importar services.py) porque las migraciones no
# deben depender de código de la app que puede cambiar con el tiempo.
ZONAS = [
    {'clave': 'bosque_encantado', 'nombre': 'Bosque Encantado', 'orden': 0, 'descripcion': 'Vocales y sonidos básicos'},
    {'clave': 'montana_letras', 'nombre': 'Montaña de las Letras', 'orden': 1, 'descripcion': 'Consonantes y combinaciones'},
    {'clave': 'valle_silabas', 'nombre': 'Valle de las Sílabas', 'orden': 2, 'descripcion': 'Sílabas y ritmo'},
    {'clave': 'castillo_palabras', 'nombre': 'Castillo de las Palabras', 'orden': 3, 'descripcion': 'Palabras completas'},
    {'clave': 'reino_lectura', 'nombre': 'Reino de la Lectura', 'orden': 4, 'descripcion': 'Frases y comprensión'},
]


def crear_zonas(apps, schema_editor):
    Zona = apps.get_model('niveles', 'Zona')
    for datos in ZONAS:
        Zona.objects.get_or_create(clave=datos['clave'], defaults=datos)


def eliminar_zonas(apps, schema_editor):
    Zona = apps.get_model('niveles', 'Zona')
    Zona.objects.filter(clave__in=[z['clave'] for z in ZONAS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('niveles', '0008_zona'),
    ]

    operations = [
        migrations.RunPython(crear_zonas, eliminar_zonas),
    ]
