"""
Capa de servicios del módulo `configuracion` (Módulo I del Master Plan).

Contiene la lógica de negocio para guardar las preferencias de accesibilidad
del usuario (`ConfiguracionGlobal`) y el correo del tutor (`UsuarioCustom`),
validando los datos recibidos desde el formulario antes de persistirlos.
"""

import logging

from .models import ConfiguracionGlobal

logger = logging.getLogger(__name__)

# Volumen mínimo y máximo permitido para narración y música (0-100).
VOLUMEN_MINIMO = 0
VOLUMEN_MAXIMO = 100

# Mapa de campos `choices` a validar: nombre del campo -> nombre del
# atributo de choices en `ConfiguracionGlobal`.
CAMPOS_CHOICES = {
    'tipo_fuente': 'TIPO_FUENTE_CHOICES',
    'tamano_fuente': 'TAMANO_FUENTE_CHOICES',
    'espaciado_letras': 'ESPACIADO_CHOICES',
    'espaciado_palabras': 'ESPACIADO_CHOICES',
    'tema_visual': 'TEMA_CHOICES',
    'velocidad_narracion': 'VELOCIDAD_NARRACION_CHOICES',
    'tipo_voz': 'TIPO_VOZ_CHOICES',
}

# Campos numéricos de volumen a validar y acotar entre 0 y 100.
CAMPOS_VOLUMEN = ['volumen_narracion', 'volumen_musica']


def _validar_campo_choice(config, datos, campo, nombre_choices):
    """
    Valida y asigna un campo de tipo `choices` de `ConfiguracionGlobal`.

    Si `datos` contiene un valor para `campo` y ese valor está entre las
    opciones válidas definidas en `ConfiguracionGlobal.<nombre_choices>`, se
    asigna a `config`. En caso contrario (valor ausente o inválido), se
    conserva el valor actual de `config` sin lanzar ninguna excepción.

    Args:
        config (ConfiguracionGlobal): instancia a modificar.
        datos (QueryDict): datos recibidos en el POST (`request.POST`).
        campo (str): nombre del atributo del modelo a validar.
        nombre_choices (str): nombre del atributo de clase que contiene las
            opciones válidas (p.ej. `'TEMA_CHOICES'`).

    Returns:
        None
    """
    valor_recibido = datos.get(campo)
    opciones_validas = [opcion[0] for opcion in getattr(ConfiguracionGlobal, nombre_choices)]

    if valor_recibido in opciones_validas:
        setattr(config, campo, valor_recibido)


def _validar_campo_volumen(config, datos, campo):
    """
    Valida y asigna un campo numérico de volumen (0-100) de `ConfiguracionGlobal`.

    Intenta convertir el valor recibido a `int` y lo acota (clamp) al rango
    0-100. Si el valor no está presente o no es un entero válido, se
    conserva el valor actual de `config` sin lanzar ninguna excepción.

    Args:
        config (ConfiguracionGlobal): instancia a modificar.
        datos (QueryDict): datos recibidos en el POST (`request.POST`).
        campo (str): nombre del atributo del modelo a validar
            (`'volumen_narracion'` o `'volumen_musica'`).

    Returns:
        None
    """
    valor_recibido = datos.get(campo)
    if valor_recibido is None:
        return

    try:
        valor_entero = int(valor_recibido)
    except (TypeError, ValueError):
        logger.warning('Valor de %s no es un entero válido: %r', campo, valor_recibido)
        return

    valor_acotado = max(VOLUMEN_MINIMO, min(VOLUMEN_MAXIMO, valor_entero))
    setattr(config, campo, valor_acotado)


def guardar_configuracion(usuario, datos):
    """
    Guarda las preferencias de accesibilidad del usuario en `ConfiguracionGlobal`.

    Valida y actualiza los 9 campos de accesibilidad (`tipo_fuente`,
    `tamano_fuente`, `espaciado_letras`, `espaciado_palabras`, `tema_visual`,
    `velocidad_narracion`, `tipo_voz`, `volumen_narracion`,
    `volumen_musica`). Los campos de tipo `choices` se validan contra las
    opciones definidas en el modelo; los campos de volumen se acotan al
    rango 0-100. Cualquier valor ausente o inválido conserva el valor
    actual sin generar error para el usuario.

    Args:
        usuario: instancia de `UsuarioCustom` (estudiante o tutor autenticado).
        datos (QueryDict): datos recibidos en el POST (`request.POST`).

    Returns:
        ConfiguracionGlobal: la instancia de configuración actualizada y guardada.
    """
    config, _creado = ConfiguracionGlobal.objects.get_or_create(usuario=usuario)

    for campo, nombre_choices in CAMPOS_CHOICES.items():
        _validar_campo_choice(config, datos, campo, nombre_choices)

    for campo in CAMPOS_VOLUMEN:
        _validar_campo_volumen(config, datos, campo)

    config.save()
    return config


def actualizar_correo_tutor(usuario, correo):
    """
    Actualiza el correo del tutor (`UsuarioCustom.correo_tutor`).

    Si `correo` es `None`, no se modifica el campo (el formulario no envió
    ese dato). Si `correo` es una cadena (incluida vacía), se asigna
    directamente, permitiendo al usuario vaciar el correo del tutor si lo
    desea.

    Args:
        usuario: instancia de `UsuarioCustom` (estudiante o tutor autenticado).
        correo (str | None): correo recibido en el POST
            (`request.POST.get('correo_tutor')`).

    Returns:
        None
    """
    if correo is None:
        return

    usuario.correo_tutor = correo
    usuario.save()
