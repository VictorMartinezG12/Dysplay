"""
Capa de servicios del módulo `camara_inteligente` (Módulo G del Master Plan).

Contiene la lógica de negocio del flujo de Cámara Inteligente: validación de
la imagen capturada, reconocimiento de objetos/logos/texto vía Google Cloud
Vision, generación de la frase de práctica según lo detectado y el nivel del
estudiante, y evaluación de la pronunciación de esa frase reutilizando el
mismo pipeline de Azure Speech que el resto de la plataforma.

Las vistas de `camara_inteligente/views.py` deben mantenerse "delgadas" y
delegar toda la lógica de negocio a las funciones definidas aquí.
"""

import base64
import binascii
import json
import logging
import os
import re
import time

import magic
from django.conf import settings
from django.core.cache import cache
from openai import AzureOpenAI

from avatar.reactions import obtener_reaccion
from estadisticas.models import RegistroActividad
from niveles.models import ProgresoEstudiante
from niveles.services import (
    UMBRAL_SUPERACION_NIVEL,
    evaluar_pronunciacion_azure,
    procesar_audio_subido,
)
from recompensas.services import otorgar_monedas
from servicios.utils import analizar_imagen_google_vision

from .models import ConfiguracionCamara, FraseTemplate

logger = logging.getLogger(__name__)

# Tamaño máximo permitido para las imágenes capturadas por la cámara (en bytes).
TAMANO_MAXIMO_IMAGEN_BYTES = getattr(settings, 'FILE_UPLOAD_MAX_MEMORY_SIZE', 5 * 1024 * 1024)

# Tipos MIME aceptados como imagen válida.
TIPOS_MIME_IMAGEN_VALIDOS = {'image/jpeg', 'image/png'}

# Monedas otorgadas cuando el objeto detectado no tiene una `FraseTemplate`
# asociada (frase genérica de respaldo).
RECOMPENSA_MONEDAS_FALLBACK = 5

# Frase genérica usada en modo normal cuando no hay traducción, `FraseTemplate`
# registrada, ni respuesta utilizable del LLM, para que el flujo nunca se
# interrumpa.
FRASE_GENERICA = '¡Qué interesante! Veo algo llamado {objeto}. ¿Puedes describirlo en voz alta?'

# Frase de última barrera usada SOLO en "modo económico" (`ConfiguracionCamara`)
# cuando ni siquiera hay una `FraseTemplate` guardada para el objeto: a
# diferencia de `FRASE_GENERICA`, no pretende ser una frase elaborada, solo
# pide pronunciar el nombre del objeto (no se llama al LLM en absoluto en
# este modo).
FRASE_SOLO_NOMBRE = 'Este objeto se llama {objeto}. Dilo en voz alta: {objeto}.'

# Monedas otorgadas cuando la frase fue generada dinámicamente por el LLM
# (Azure OpenAI) en lugar de provenir de una `FraseTemplate` registrada en BD.
# Se usa el mismo valor que la frase genérica de respaldo
# (RECOMPENSA_MONEDAS_FALLBACK) porque ambas son frases "no curadas
# manualmente"; si en el futuro se quiere incentivar más el uso del LLM basta
# con subir esta constante.
RECOMPENSA_MONEDAS_LLM = RECOMPENSA_MONEDAS_FALLBACK

# Versión de la API de Azure OpenAI. No existe una env var específica para esto
# en el proyecto, así que se fija un valor estable y reciente como constante.
AZURE_OPENAI_API_VERSION = '2024-10-21'

# Tiempo de espera máximo (segundos) para la llamada a Azure OpenAI, para que
# nunca bloquee el flujo de captura de la cámara si el servicio está lento.
AZURE_OPENAI_TIMEOUT_SEGUNDOS = 8

# Tiempo (segundos) que se cachea cada llamada al LLM (traducción y
# frase se cachean por separado, ver `_traducir_objeto_llm` y
# `_generar_frase_llm`). 24 horas: el contenido puede variar día a día
# sin necesidad de llamar al LLM en cada captura de la misma detección.
CACHE_LLM_CAMARA_TIMEOUT_SEGUNDOS = 60 * 60 * 24

# Tiempo (segundos) que se cachea el "eco" de corto plazo por estudiante: si
# vuelve a detectar exactamente el mismo objeto (misma etiqueta de Vision y
# calificador) dentro de esta ventana, se le repite la misma frase de la vez
# anterior sin llamar a nada (ni LLM ni Vision-translation), para no generar
# costo extra por capturas casi inmediatas del mismo objeto. 15 minutos:
# cubre una sesión de juego típica sin necesidad de que cierre la página.
CACHE_ECO_CAMARA_TIMEOUT_SEGUNDOS = 60 * 15

# Cantidad máxima de variantes de `FraseTemplate` que se auto-guardan por
# combinación de objeto/nivel (ver `_guardar_frase_template_automatica`): pasado
# este límite, ya hay suficiente variedad y se deja de insertar filas nuevas
# para esa combinación, para no crecer la tabla sin límite con el tiempo.
MAXIMO_VARIANTES_FRASE_AUTOGUARDADA = 5

# Diccionario de traducción de respaldo, usado SOLO cuando Azure OpenAI falla
# por completo (timeout/error de red): permite caer en una `FraseTemplate`
# curada para los objetos más comunes en vez de la `FRASE_GENERICA`. Ya
# NO es el límite de qué objetos puede practicar el niño — ver
# `generar_frase_deteccion`, que primero intenta el LLM con CUALQUIER
# detección que entregue Vision.
TRADUCCION_OBJETOS = {
    'pencil': 'lápiz',
    'book': 'libro',
    'apple': 'manzana',
    'dog': 'perro',
    'cat': 'gato',
    'chair': 'silla',
    'table': 'mesa',
    'dining table': 'mesa',
    'car': 'auto',
    'vehicle': 'auto',
    'ball': 'pelota',
    'shoe': 'zapato',
    'footwear': 'zapato',
    'cup': 'taza',
    'mug': 'taza',
    'bottle': 'botella',
    'flower': 'flor',
    'tree': 'árbol',
    'house': 'casa',
    'clock': 'reloj',
    'mobile phone': 'teléfono',
    'telephone': 'teléfono',
    'smartphone': 'teléfono',
    'laptop': 'computadora',
    'computer': 'computadora',
    'bicycle': 'bicicleta',
    'bird': 'pájaro',
    'fish': 'pez',
    'banana': 'plátano',
    'orange': 'naranja',
    'bread': 'pan',
    'spoon': 'cuchara',
    'fork': 'tenedor',
    'plate': 'plato',
    'tableware': 'plato',
    'bed': 'cama',
    'lamp': 'lámpara',
    'lighting': 'lámpara',
    'window': 'ventana',
    'door': 'puerta',
    'hat': 'sombrero',
    'shirt': 'camisa',
    't-shirt': 'camisa',
    'handbag': 'bolso',
    'bag': 'bolso',
    'key': 'llave',
    'scissors': 'tijeras',
    'pen': 'bolígrafo',
    'notebook': 'cuaderno',
    'ruler': 'regla',
    'backpack': 'mochila',
    'umbrella': 'sombrilla',
    'glasses': 'lentes',
    'mirror': 'espejo',
    'sock': 'calcetín',
    'balloon': 'globo',
    'kite': 'cometa',
    'drum': 'tambor',
    'guitar': 'guitarra',
    'piano': 'piano',
    'doll': 'muñeca',
    'toy': 'muñeca',
    'train': 'tren',
    'airplane': 'avión',
    'boat': 'barco',
    'candle': 'vela',
    'egg': 'huevo',
    'carrot': 'zanahoria',
    'strawberry': 'fresa',
    'grape': 'uva',
    'helmet': 'casco',
    'butterfly': 'mariposa',
    'headphones': 'audífonos',
    'earphones': 'audífonos',
    'headset': 'audífonos',
    'keyboard': 'teclado',
    'computer keyboard': 'teclado',
    'mouse': 'mouse',
    'computer mouse': 'mouse',
    'watch': 'reloj',
    'wristwatch': 'reloj',
    'television': 'televisor',
    'tv': 'televisor',
    'remote control': 'control remoto',
    'speaker': 'parlante',
    'loudspeaker': 'parlante',
    'camera': 'cámara',
    'tablet computer': 'tableta',
    'charger': 'cargador',
    'cable': 'cable',
    'wallet': 'billetera',
    'comb': 'peine',
    'hairbrush': 'cepillo',
    'toothbrush': 'cepillo de dientes',
    'towel': 'toalla',
    'soap': 'jabón',
    'pillow': 'almohada',
    'blanket': 'cobija',
    'calculator': 'calculadora',
    'stapler': 'engrapadora',
    'eraser': 'goma de borrar',
    'rubber': 'goma de borrar',
    'marker': 'marcador',
    'crayon': 'crayón',
    'paint': 'pintura',
    'brush': 'pincel',
    'plant': 'planta',
    'flowerpot': 'macetero',
    'sunglasses': 'gafas de sol',
    'fan': 'ventilador',
    'fork (cutlery)': 'tenedor',
}


def validar_imagen_base64(imagen_base64):
    """
    Valida y decodifica la imagen capturada por la cámara del estudiante.

    Acepta tanto una cadena base64 "pura" como una *data URL* completa
    (`data:image/jpeg;base64,...`), de la cual se descarta el prefijo. Antes
    de aceptar la imagen se valida su tamaño y su tipo real mediante
    `python-magic` (no se confía en la extensión ni en el `content_type`
    declarado por el navegador).

    Args:
        imagen_base64 (str): contenido de la imagen en base64, con o sin
            prefijo de *data URL*.

    Returns:
        str: la imagen en base64 sin el prefijo de *data URL*, lista para
            enviarse a Google Cloud Vision.

    Raises:
        ValueError: si la imagen no se recibió, no es base64 válido, excede
            el tamaño máximo permitido, o su contenido real no corresponde a
            una imagen JPEG/PNG.
    """
    if not imagen_base64:
        raise ValueError('No se recibió ninguna imagen.')

    if ',' in imagen_base64 and imagen_base64.strip().lower().startswith('data:'):
        imagen_base64 = imagen_base64.split(',', 1)[1]

    try:
        imagen_bytes = base64.b64decode(imagen_base64, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError('La imagen recibida no tiene un formato base64 válido.') from error

    if len(imagen_bytes) > TAMANO_MAXIMO_IMAGEN_BYTES:
        raise ValueError(
            f'La imagen excede el tamaño máximo permitido ({TAMANO_MAXIMO_IMAGEN_BYTES} bytes).'
        )

    tipo_mime_detectado = magic.from_buffer(imagen_bytes, mime=True)
    if tipo_mime_detectado not in TIPOS_MIME_IMAGEN_VALIDOS:
        raise ValueError(
            f'La imagen recibida no es un JPEG/PNG válido (tipo detectado: {tipo_mime_detectado}).'
        )

    return imagen_base64


def _nivel_dificultad_usuario(usuario):
    """
    Calcula el nivel de dificultad (1-5) de las frases de cámara para un estudiante.

    Se basa en `ProgresoEstudiante.nivel_actual.numero`, acotado al rango
    1-5 que usa `FraseTemplate.nivel_dificultad`. Si el estudiante no tiene
    progreso o nivel asignado, se usa el nivel 1 (más sencillo).

    Args:
        usuario: instancia de `UsuarioCustom` (estudiante autenticado).

    Returns:
        int: nivel de dificultad entre 1 y 5.
    """
    progreso = ProgresoEstudiante.objects.filter(usuario=usuario).first()
    if progreso and progreso.nivel_actual:
        return min(max(progreso.nivel_actual.numero, 1), 5)
    return 1


# Proporción máxima de caracteres numéricos que puede tener un texto detectado
# por TEXT_DETECTION para considerarlo una palabra real (marca, contenido) y
# no un código/número de serie (ej. "703064 44750" en una goma de borrar).
PROPORCION_MAXIMA_DIGITOS_TEXTO_VALIDO = 0.3

# Longitud máxima de un texto detectado para usarlo como calificador del
# objeto; los textos más largos suelen ser párrafos/etiquetas legales, no un
# nombre de producto corto.
LONGITUD_MAXIMA_TEXTO_CALIFICADOR = 30

# Etiquetas que `OBJECT_LOCALIZATION` puede devolver como "objeto" detectado
# pero que en realidad son artefactos impresos sobre el objeto real (código
# de barras, QR, etiqueta de producto), no algo que un niño nombraría. Se
# descartan al elegir el objeto principal, igual se filtran si aparecen con
# mayor confianza que el objeto real (ver `_detectar_objeto_y_calificador`).
ETIQUETAS_OBJETO_IGNORADAS = {
    '1d barcode', '2d barcode', 'barcode', 'bar code', 'qr code',
    'label', 'packaging and labeling', 'sticker', 'font', 'text',
}


def _es_etiqueta_objeto_valida(descripcion):
    """`False` si `descripcion` es un artefacto impreso (código de barras, QR, etiqueta) y no un objeto real."""
    descripcion_normalizada = descripcion.lower().strip()
    if descripcion_normalizada in ETIQUETAS_OBJETO_IGNORADAS:
        return False
    return 'barcode' not in descripcion_normalizada and 'qr code' not in descripcion_normalizada


def _texto_es_calificador_valido(contenido_texto):
    """
    Decide si un texto detectado por `TEXT_DETECTION` es una palabra real
    utilizable como calificador del objeto (ej. "agua", "Coca-Cola"), y no
    un código/número de serie sin sentido para una frase.

    Heurística simple: se descarta si está vacío, es muy largo, o más de
    `PROPORCION_MAXIMA_DIGITOS_TEXTO_VALIDO` de sus caracteres son dígitos.

    Args:
        contenido_texto (str): primera línea del texto detectado.

    Returns:
        bool: `True` si el texto parece una palabra/marca real.
    """
    texto = contenido_texto.strip()
    if not texto or len(texto) > LONGITUD_MAXIMA_TEXTO_CALIFICADOR:
        return False
    proporcion_digitos = sum(caracter.isdigit() for caracter in texto) / len(texto)
    return proporcion_digitos <= PROPORCION_MAXIMA_DIGITOS_TEXTO_VALIDO


def _caja_contiene_centro(caja_contenedora, caja_interior, margen=0.15):
    """
    Verifica si el centro de `caja_interior` cae dentro de `caja_contenedora`
    (ambas con `vertices` normalizados 0-1), expandida por `margen` en cada
    lado para tolerar pequeños desajustes del recuadro de Vision.

    Se usa para decidir si un logo/texto detectado está físicamente sobre el
    objeto principal (ej. la etiqueta "agua" sobre la botella) y por lo tanto
    puede usarse como su calificador, en vez de tratarse de algo aparte en la
    misma foto.

    Args:
        caja_contenedora (list[dict]): vértices `{'x', 'y'}` del objeto.
        caja_interior (list[dict]): vértices `{'x', 'y'}` del logo/texto.
        margen (float): expansión de la caja contenedora, en fracción 0-1.

    Returns:
        bool: `True` si el centro de `caja_interior` cae dentro del área
            (expandida) de `caja_contenedora`, o si falta alguna de las cajas
            (se asume solapamiento por no poder verificarlo).
    """
    if not caja_contenedora or not caja_interior:
        return True

    xs_contenedora = [vertice['x'] for vertice in caja_contenedora]
    ys_contenedora = [vertice['y'] for vertice in caja_contenedora]
    xs_interior = [vertice['x'] for vertice in caja_interior]
    ys_interior = [vertice['y'] for vertice in caja_interior]

    centro_x = sum(xs_interior) / len(xs_interior)
    centro_y = sum(ys_interior) / len(ys_interior)

    return (
        min(xs_contenedora) - margen <= centro_x <= max(xs_contenedora) + margen
        and min(ys_contenedora) - margen <= centro_y <= max(ys_contenedora) + margen
    )


def _sanear_punto_objetivo(punto_objetivo):
    """
    Valida y acota a `[0, 1]` el punto donde el niño apuntaba al capturar
    (el centro del recuadro que el navegador resaltaba en vivo vía
    COCO-SSD, ver `static/js/camara_inteligente/camara.js`).

    No se confía en que el cliente mande un valor ya acotado a 0-1: cualquier
    estructura inesperada (no es un dict, faltan `x`/`y`, no son numéricos)
    se trata como ausente en vez de lanzar una excepción, para que un punto
    malformado nunca interrumpa el flujo de captura.

    Args:
        punto_objetivo: valor crudo recibido (se espera `{'x': float, 'y': float}`).

    Returns:
        dict | None: `{'x': float, 'y': float}` acotado a `[0, 1]`, o `None`
            si `punto_objetivo` no tiene la forma esperada.
    """
    if not isinstance(punto_objetivo, dict):
        return None
    x = punto_objetivo.get('x')
    y = punto_objetivo.get('y')
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        return None
    return {'x': min(1.0, max(0.0, float(x))), 'y': min(1.0, max(0.0, float(y)))}


def _elegir_etiqueta_principal(etiquetas, punto_objetivo):
    """
    Elige la etiqueta principal entre `etiquetas`, dando prioridad a la que
    el niño estaba apuntando (`punto_objetivo`) sobre la de mayor confianza
    global.

    Si `punto_objetivo` cae dentro de la caja de una o más etiquetas, se
    elige la de mayor score ENTRE ESAS (apuntar mal a un objeto secundario no
    debería ganarle al objeto que el niño realmente estaba centrando). Si
    `punto_objetivo` es `None` o no cae dentro de ninguna caja, se mantiene
    el comportamiento anterior: la etiqueta de mayor score entre todas.

    Args:
        etiquetas (list[dict]): etiquetas ya filtradas de artefactos
            (`_es_etiqueta_objeto_valida`), cada una con `vertices`.
        punto_objetivo (dict | None): `{'x', 'y'}` ya saneado por
            `_sanear_punto_objetivo`, o `None`.

    Returns:
        dict: la etiqueta elegida.
    """
    if punto_objetivo:
        etiquetas_bajo_el_punto = [
            etiqueta for etiqueta in etiquetas
            if _caja_contiene_centro(etiqueta.get('vertices'), [punto_objetivo])
        ]
        if etiquetas_bajo_el_punto:
            return max(etiquetas_bajo_el_punto, key=lambda etiqueta: etiqueta['score'])

    return max(etiquetas, key=lambda etiqueta: etiqueta['score'])


def _detectar_objeto_y_calificador(resultado_vision, punto_objetivo=None):
    """
    Decide el objeto principal (siempre la base de la frase) y, si
    corresponde, un calificador que lo enriquezca (ej. "botella" + "agua" →
    "botella de agua"; "botella" + "Coca-Cola" → "botella de Coca-Cola").

    El objeto siempre viene de `etiquetas` (`OBJECT_LOCALIZATION`), descartando
    primero las que son artefactos impresos y no objetos reales (código de
    barras, QR, etiqueta de producto — ver `ETIQUETAS_OBJETO_IGNORADAS`): un
    código de barras puede ser lo más prominente que Vision encuentra sobre,
    por ejemplo, una goma de borrar, pero no es lo que el niño debe nombrar.
    Si tras filtrar no queda ningún objeto localizado utilizable, se cae a
    `etiquetas_generales` (`LABEL_DETECTION`, que analiza toda la foto en vez
    de un recuadro) como respaldo; en ese caso no hay caja para resaltar.
    Sin ningún objeto utilizable (ni localizado ni general) no hay nada que
    practicar, sin importar qué tan interesante sea un texto o logo suelto en
    la foto.

    Entre las etiquetas localizadas válidas, `punto_objetivo` (si está
    presente) decide cuál es "el objeto" cuando hay varios en la foto: se
    prioriza la etiqueta que el niño tenía centrada al capturar sobre la de
    mayor confianza global (ver `_elegir_etiqueta_principal`).

    Un logo o texto solo se usa como calificador del objeto elegido si (a)
    cae espacialmente sobre su caja (`_caja_contiene_centro`; si el objeto
    vino de `etiquetas_generales` y no tiene caja, se asume solapamiento) y
    (b), en el caso de texto, parece una palabra real y no un código/número
    de serie (`_texto_es_calificador_valido`). Se prioriza el logo sobre el
    texto porque un logo reconocido es siempre una marca real, mientras que
    el texto puede ser ambiguo.

    Args:
        resultado_vision (dict): salida de
            `servicios.utils.analizar_imagen_google_vision` en caso de
            éxito (`etiquetas`, `etiquetas_generales`, `logos`, `texto`).
        punto_objetivo (dict | None): `{'x', 'y'}` normalizado 0-1 ya saneado
            (ver `_sanear_punto_objetivo`), o `None` si no se recibió.

    Returns:
        dict | None: `{'etiqueta_en': str, 'confianza': float,
            'vertices': list[dict] | None, 'calificador': str | None,
            'fuente_calificador': 'logo'|'texto'|None}`, o `None` si no hay
            ningún objeto utilizable.
    """
    etiquetas_validas = [
        etiqueta for etiqueta in (resultado_vision.get('etiquetas') or [])
        if _es_etiqueta_objeto_valida(etiqueta['description'])
    ]

    if etiquetas_validas:
        etiqueta_principal = _elegir_etiqueta_principal(etiquetas_validas, punto_objetivo)
        caja_objeto = etiqueta_principal.get('vertices')
    else:
        etiquetas_generales_validas = [
            etiqueta for etiqueta in (resultado_vision.get('etiquetas_generales') or [])
            if _es_etiqueta_objeto_valida(etiqueta['description'])
        ]
        if not etiquetas_generales_validas:
            return None
        etiqueta_principal = max(etiquetas_generales_validas, key=lambda etiqueta: etiqueta['score'])
        caja_objeto = None

    calificador = None
    fuente_calificador = None

    logos = resultado_vision.get('logos') or []
    logos_sobre_objeto = [logo for logo in logos if _caja_contiene_centro(caja_objeto, logo.get('vertices'))]
    if logos_sobre_objeto:
        logo_principal = max(logos_sobre_objeto, key=lambda logo: logo['score'])
        calificador = logo_principal['description']
        fuente_calificador = 'logo'

    if calificador is None:
        texto = resultado_vision.get('texto')
        if texto and texto.get('contenido', '').strip():
            primera_linea = texto['contenido'].strip().splitlines()[0]
            if (
                _texto_es_calificador_valido(primera_linea)
                and _caja_contiene_centro(caja_objeto, texto.get('vertices'))
            ):
                calificador = primera_linea
                fuente_calificador = 'texto'

    return {
        'etiqueta_en': etiqueta_principal['description'].lower(),
        'confianza': etiqueta_principal['score'],
        'vertices': caja_objeto,
        'calificador': calificador,
        'fuente_calificador': fuente_calificador,
    }


def _traducir_objeto_llm(etiqueta_en, calificador):
    """
    Traduce `etiqueta_en` (etiqueta en inglés devuelta por Google Vision) al
    español, combinándola con `calificador` si corresponde (ej. "bottle" +
    "water" → "botella de agua").

    Es una tarea simple y acotada a propósito (pedirle solo esto al LLM, sin
    mezclarla con la generación creativa de la frase ni con un formato
    JSON estricto): el modelo configurado (Phi-4-mini-instruct) es poco
    confiable cuando se le piden varias cosas a la vez en un mismo llamado,
    pero traducir una palabra suelta es algo que incluso un modelo débil
    suele hacer bien. Separar esta llamada de `_generar_frase_llm`
    evita que un fallo en la parte creativa (la más propensa a fallar)
    arrastre también la traducción, que es la parte que SIEMPRE debería
    funcionar — así CUALQUIER objeto detectado por Vision puede tener su
    nombre en español, sin depender de que esté en el diccionario fijo
    `TRADUCCION_OBJETOS` (ese diccionario queda solo como último respaldo si
    esta llamada falla por completo, ver `generar_frase_deteccion`).

    El resultado se cachea (vía `django.core.cache.cache`) por la
    combinación `(etiqueta_en, calificador)` durante
    `CACHE_LLM_CAMARA_TIMEOUT_SEGUNDOS`.

    Args:
        etiqueta_en (str): etiqueta en inglés tal cual la entrega Vision.
        calificador (str | None): logo/texto real detectado sobre el objeto
            (no se traduce, se usa tal cual), o `None` si no hay ninguno.

    Returns:
        str | None: el nombre del objeto en español (y su calificador
            combinado si correspondía), o `None` si la llamada al LLM falla
            por cualquier motivo (timeout, error de red, credenciales,
            respuesta vacía o demasiado larga para ser una traducción).
            Nunca lanza una excepción hacia el caller.
    """
    clave_calificador = calificador.lower() if calificador else 'ninguno'
    clave_cache = f'traduccion_llm_camara_{etiqueta_en.lower()}_{clave_calificador}'
    resultado_en_cache = cache.get(clave_cache)
    if resultado_en_cache is not None:
        return resultado_en_cache

    if calificador:
        prompt = (
            f'Traduce esta etiqueta en inglés que identifica un objeto detectado por una '
            f'cámara: "{etiqueta_en}". El objeto además tiene escrito o muestra "{calificador}" '
            '(una marca o palabra real visible sobre él; NO la traduzcas, úsala tal cual). '
            f'Combina ambas naturalmente en español (ej. "bottle" + "water" → "botella de agua"; '
            '"bottle" + "Coca-Cola" → "botella de Coca-Cola"). Responde ÚNICAMENTE con el nombre '
            'final en español, sin comillas, sin punto final, sin explicaciones.'
        )
    else:
        prompt = (
            f'Traduce esta etiqueta en inglés que identifica un objeto detectado por una '
            f'cámara: "{etiqueta_en}", a UNA sola palabra o frase muy corta en español (el '
            'nombre común del objeto). Responde ÚNICAMENTE con esa palabra, sin comillas, sin '
            'punto final, sin explicaciones.'
        )

    inicio = time.monotonic()
    try:
        cliente = AzureOpenAI(
            api_key=settings.AZURE_OPENAI_API_KEY,
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_version=AZURE_OPENAI_API_VERSION,
            timeout=AZURE_OPENAI_TIMEOUT_SEGUNDOS,
            # Sin reintentos automáticos del SDK: si Azure OpenAI está lento/caído,
            # ya tenemos nuestro propio respaldo (TRADUCCION_OBJETOS) y reintentar
            # internamente solo multiplica la espera de un niño frente a la cámara.
            max_retries=0,
        )
        respuesta = cliente.chat.completions.create(
            model=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
            messages=[{'role': 'user', 'content': prompt}],
            temperature=0.2,
            max_tokens=20,
            timeout=AZURE_OPENAI_TIMEOUT_SEGUNDOS,
        )
        objeto_es = respuesta.choices[0].message.content.strip().strip('."\' ')
        # Defensa adicional: si el modelo devuelve un párrafo (explicación,
        # disculpa) en vez de solo el nombre, se descarta y se cae al
        # diccionario `TRADUCCION_OBJETOS` como respaldo.
        if not objeto_es or len(objeto_es.split()) > 6:
            raise ValueError('La traducción del LLM no es una palabra/frase corta válida.')
    except Exception:
        logger.error(
            'Error al traducir objeto con Azure OpenAI para etiqueta=%s calificador=%s (%.1fs transcurridos)',
            etiqueta_en, calificador, time.monotonic() - inicio, exc_info=True,
        )
        return None

    cache.set(clave_cache, objeto_es, CACHE_LLM_CAMARA_TIMEOUT_SEGUNDOS)
    return objeto_es


# Cantidad de repeticiones consecutivas de la misma palabra a partir de la
# cual una respuesta del LLM se considera "atascada" (degenerada) y se
# descarta. Una frase normal casi nunca repite la misma palabra varias veces
# seguidas; esto es una red de seguridad genérica contra modelos pequeños que
# a veces entran en bucle (ver `_tiene_repeticion_degenerada`).
MAXIMO_REPETICIONES_CONSECUTIVAS_PALABRA = 3


def _tiene_repeticion_degenerada(texto):
    """
    Detecta si `texto` tiene la misma palabra repetida de forma mecánica más
    de `MAXIMO_REPETICIONES_CONSECUTIVAS_PALABRA` veces seguidas (ej. "peina
    peina peina peina peina"), un patrón de degeneración conocido en
    modelos pequeños como Phi-4-mini-instruct: el modelo arranca bien y luego
    se "atasca" en un bucle de la misma palabra en vez de seguir el texto con
    normalidad.

    Args:
        texto (str): texto a evaluar (ej. una frase generada por el LLM).

    Returns:
        bool: `True` si alguna palabra se repite de forma consecutiva más
            veces que el límite permitido.
    """
    palabras = re.findall(r"[\wáéíóúñÁÉÍÓÚÑ]+", texto.lower())
    racha_actual = 1
    for anterior, actual in zip(palabras, palabras[1:]):
        racha_actual = racha_actual + 1 if actual == anterior else 1
        if racha_actual > MAXIMO_REPETICIONES_CONSECUTIVAS_PALABRA:
            return True
    return False


def _generar_frase_llm(objeto_es, nivel_usuario):
    """
    Genera una frase corta de práctica para `objeto_es`, que YA debe estar en
    español (ver `_traducir_objeto_llm` o `TRADUCCION_OBJETOS`).

    Igual que `_traducir_objeto_llm`, es una tarea simple y acotada a
    propósito: solo generar la frase, sin pedirle también al LLM que
    traduzca nada ni que respete un formato JSON. Esto aísla la parte más
    propensa a fallar (la generación creativa) de la traducción, que ya se
    resolvió antes y no debe perderse si esta llamada falla.

    El resultado se cachea (vía `django.core.cache.cache`) por la
    combinación `(objeto_es, nivel_usuario)` durante
    `CACHE_LLM_CAMARA_TIMEOUT_SEGUNDOS`.

    Args:
        objeto_es (str): nombre del objeto ya en español.
        nivel_usuario (int): nivel de dificultad del estudiante (1-5).

    Returns:
        str | None: la frase generada, o `None` si la llamada al LLM falla
            por cualquier motivo (timeout, error de red, credenciales,
            respuesta vacía o demasiado larga). Nunca lanza una excepción
            hacia el caller.
    """
    clave_cache = f'frase_llm_camara_{objeto_es.lower()}_{nivel_usuario}'
    resultado_en_cache = cache.get(clave_cache)
    if resultado_en_cache is not None:
        return resultado_en_cache

    prompt = (
        f'Escribe una frase corta y natural (máximo 10 palabras) en español que use la '
        f'palabra o frase "{objeto_es}", para que un niño la lea en voz alta y practique '
        f'pronunciación. La dificultad debe corresponder a un nivel {nivel_usuario} de 5 '
        '(1 = muy simple, 5 = más elaborada). El contenido debe ser siempre positivo y '
        'apropiado para niños. Responde ÚNICAMENTE con la frase, sin comillas, sin '
        'explicaciones, sin markdown.'
    )

    inicio = time.monotonic()
    try:
        cliente = AzureOpenAI(
            api_key=settings.AZURE_OPENAI_API_KEY,
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_version=AZURE_OPENAI_API_VERSION,
            timeout=AZURE_OPENAI_TIMEOUT_SEGUNDOS,
            # Sin reintentos automáticos del SDK: ver comentario equivalente
            # en `_traducir_objeto_llm`.
            max_retries=0,
        )
        respuesta = cliente.chat.completions.create(
            model=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
            messages=[{'role': 'user', 'content': prompt}],
            temperature=0.4,
            max_tokens=60,
            timeout=AZURE_OPENAI_TIMEOUT_SEGUNDOS,
        )
        frase = respuesta.choices[0].message.content.strip().strip('"')
        # Defensa adicional: si el modelo devuelve un párrafo largo
        # (razonamiento, preguntas, disculpas) en vez de una frase corta, o
        # se "atasca" repitiendo la misma palabra muchas veces seguidas
        # (degeneración conocida de modelos débiles como Phi-4-mini-instruct,
        # ej. "peina peina peina peina peina"), se descarta y se cae al
        # fallback de FraseTemplate/FRASE_GENERICA.
        if (
            not frase
            or len(frase.split()) > 20
            or _tiene_repeticion_degenerada(frase)
        ):
            raise ValueError('La frase generada no es válida.')
    except Exception:
        logger.error(
            'Error al generar frase con Azure OpenAI para objeto=%s nivel=%s (%.1fs transcurridos)',
            objeto_es, nivel_usuario, time.monotonic() - inicio, exc_info=True,
        )
        return None

    cache.set(clave_cache, frase, CACHE_LLM_CAMARA_TIMEOUT_SEGUNDOS)
    return frase


def _clave_cache_eco(usuario_id, etiqueta_en, calificador):
    """Clave de caché del eco de corto plazo por estudiante (ver `CACHE_ECO_CAMARA_TIMEOUT_SEGUNDOS`)."""
    clave_calificador = calificador.lower() if calificador else 'ninguno'
    return f'eco_camara_{usuario_id}_{etiqueta_en.lower()}_{clave_calificador}'


def _resolver_frase_respaldo(objeto_es, nivel_usuario, texto_generico):
    """
    Busca una `FraseTemplate` guardada para `objeto_es` (preferentemente del
    nivel del estudiante, o cualquier nivel si no hay) y, si no existe
    ninguna, devuelve `texto_generico.format(objeto=objeto_es)` como última
    barrera, para que el flujo nunca se interrumpa.

    Args:
        objeto_es (str): nombre del objeto ya en español.
        nivel_usuario (int): nivel de dificultad del estudiante (1-5).
        texto_generico (str): plantilla con un placeholder `{objeto}` (ej.
            `FRASE_GENERICA` o `FRASE_SOLO_NOMBRE`) a usar si no hay ninguna
            `FraseTemplate` guardada.

    Returns:
        tuple[str, int]: `(frase_generada, recompensa_monedas)`.
    """
    frase_template = (
        FraseTemplate.objects.filter(objeto_keyword=objeto_es, nivel_dificultad__lte=nivel_usuario).order_by('?').first()
        or FraseTemplate.objects.filter(objeto_keyword=objeto_es).order_by('?').first()
    )
    if frase_template:
        return frase_template.frase_plantilla, frase_template.recompensa_monedas
    return texto_generico.format(objeto=objeto_es), RECOMPENSA_MONEDAS_FALLBACK


def _guardar_frase_template_automatica(objeto_es, nivel_usuario, frase):
    """
    Guarda automáticamente una frase generada con éxito por el LLM como una
    nueva `FraseTemplate` (con `creada_automaticamente=True`), para construir
    con el tiempo un banco de frases reutilizables y dar variedad real a
    futuras detecciones del mismo objeto (la selección entre varias
    `FraseTemplate` del mismo `objeto_keyword` ya es al azar, ver
    `_resolver_frase_respaldo`).

    No guarda duplicados exactos, y deja de insertar filas nuevas para la
    misma combinación objeto/nivel una vez alcanzado
    `MAXIMO_VARIANTES_FRASE_AUTOGUARDADA`, para no crecer la tabla sin límite.

    Args:
        objeto_es (str): nombre del objeto ya en español.
        nivel_usuario (int): nivel de dificultad del estudiante (1-5).
        frase (str): frase generada por `_generar_frase_llm`.

    Returns:
        None
    """
    variantes_existentes = FraseTemplate.objects.filter(objeto_keyword=objeto_es, nivel_dificultad=nivel_usuario)
    if variantes_existentes.filter(frase_plantilla=frase).exists():
        return
    if variantes_existentes.count() >= MAXIMO_VARIANTES_FRASE_AUTOGUARDADA:
        return

    FraseTemplate.objects.create(
        objeto_keyword=objeto_es,
        frase_plantilla=frase,
        nivel_dificultad=nivel_usuario,
        recompensa_monedas=RECOMPENSA_MONEDAS_LLM,
        creada_automaticamente=True,
    )


def generar_frase_deteccion(resultado_vision, nivel_usuario, usuario_id, punto_objetivo=None):
    """
    Genera la frase de práctica a partir de lo detectado por Google
    Vision (G.2). El objeto localizado (`OBJECT_LOCALIZATION`) es siempre la
    base; un logo o texto detectado sobre ese mismo objeto se usa como
    calificador para enriquecerlo (ej. "botella de agua").

    Antes de cualquier otra cosa, revisa el "eco" de corto plazo del
    estudiante (`CACHE_ECO_CAMARA_TIMEOUT_SEGUNDOS`, 15 minutos): si ya
    detectó exactamente la misma etiqueta/calificador hace poco, repite la
    misma frase de esa vez sin llamar a Vision-translation/LLM ni consultar
    `ConfiguracionCamara`, para no generar costo extra en capturas casi
    inmediatas del mismo objeto.

    Si no hay eco, decide el objeto y su calificador con
    `_detectar_objeto_y_calificador` (priorizando, si `punto_objetivo` está
    presente, el objeto que el niño tenía centrado al capturar sobre el de
    mayor confianza global) y revisa `ConfiguracionCamara.obtener().modo_economico`:

    - Si está ACTIVO: no se llama a Azure OpenAI en absoluto. El objeto se
      traduce solo con el diccionario fijo `TRADUCCION_OBJETOS` (o se usa la
      etiqueta en inglés tal cual si ni siquiera está ahí), y la frase sale
      de una `FraseTemplate` guardada o, si no hay ninguna, de
      `FRASE_SOLO_NOMBRE` (última barrera mínima, solo pronuncia el nombre).
    - Si está INACTIVO (modo normal): se intenta traducir y generar la frase
      con el LLM (`_traducir_objeto_llm`/`_generar_frase_llm`, dos llamadas
      simples y separadas, ver sus docstrings para el porqué). Si la
      generación tiene éxito, la frase se guarda automáticamente como una
      nueva `FraseTemplate` (`_guardar_frase_template_automatica`) para que
      el banco de frases reutilizables crezca con el tiempo. Si el LLM falla
      en cualquier punto, se cae a `FraseTemplate`/`FRASE_GENERICA` igual que
      en modo económico, pero con el texto genérico más elaborado.

    Args:
        resultado_vision (dict): salida de
            `servicios.utils.analizar_imagen_google_vision` en caso de éxito.
        nivel_usuario (int): nivel de dificultad del estudiante (1-5), ver
            `_nivel_dificultad_usuario`.
        usuario_id: id del estudiante autenticado, usado solo para la clave
            del eco de corto plazo (no se guarda nada más por estudiante).
        punto_objetivo (dict | None): `{'x', 'y'}` normalizado 0-1 ya saneado
            (ver `_sanear_punto_objetivo`), o `None` si no se recibió.

    Returns:
        dict | None: `{'objeto': str, 'confianza': float,
            'frase_generada': str, 'recompensa_monedas': int,
            'fuente_calificador': str | None, 'caja_deteccion': list[dict] | None}`,
            o `None` si no se localizó ningún objeto.
    """
    deteccion = _detectar_objeto_y_calificador(resultado_vision, punto_objetivo)
    if deteccion is None:
        return None

    etiqueta_en = deteccion['etiqueta_en']
    calificador = deteccion['calificador']
    datos_caja = {
        'fuente_calificador': deteccion['fuente_calificador'],
        'caja_deteccion': deteccion['vertices'],
    }

    clave_eco = _clave_cache_eco(usuario_id, etiqueta_en, calificador)
    eco = cache.get(clave_eco)
    if eco is not None:
        return {**eco, **datos_caja}

    if ConfiguracionCamara.obtener().modo_economico:
        objeto_es = TRADUCCION_OBJETOS.get(etiqueta_en, etiqueta_en)
        frase_generada, recompensa_monedas = _resolver_frase_respaldo(objeto_es, nivel_usuario, FRASE_SOLO_NOMBRE)
    else:
        objeto_es = _traducir_objeto_llm(etiqueta_en, calificador) or TRADUCCION_OBJETOS.get(etiqueta_en, etiqueta_en)
        frase = _generar_frase_llm(objeto_es, nivel_usuario)
        if frase:
            _guardar_frase_template_automatica(objeto_es, nivel_usuario, frase)
            frase_generada, recompensa_monedas = frase, RECOMPENSA_MONEDAS_LLM
        else:
            frase_generada, recompensa_monedas = _resolver_frase_respaldo(objeto_es, nivel_usuario, FRASE_GENERICA)

    resultado = {
        'objeto': objeto_es,
        'confianza': deteccion['confianza'],
        'frase_generada': frase_generada,
        'recompensa_monedas': recompensa_monedas,
    }
    cache.set(clave_eco, resultado, CACHE_ECO_CAMARA_TIMEOUT_SEGUNDOS)
    return {**resultado, **datos_caja}


def procesar_captura_imagen(usuario, imagen_base64, punto_objetivo_json=None):
    """
    Orquesta el flujo de captura de imagen (G.1, endpoint `/camara/capturar/`).

    Valida la imagen recibida, la envía a Google Cloud Vision (objetos, logos
    y texto) y construye la frase de práctica correspondiente a lo
    detectado y al nivel del estudiante.

    Args:
        usuario: instancia de `UsuarioCustom` (estudiante autenticado).
        imagen_base64 (str): imagen capturada por la cámara, en base64 (con
            o sin prefijo de *data URL*).
        punto_objetivo_json (str | None): cadena JSON cruda recibida del
            cliente con el centro del recuadro que tenía resaltado en vivo al
            capturar (`{"x": float, "y": float}` normalizado 0-1), o `None`
            si no se envió. Cualquier valor que no sea JSON válido con esa
            forma se trata como ausente (ver `_sanear_punto_objetivo`); nunca
            interrumpe el flujo.

    Returns:
        dict: `{'status': 'success', 'objeto': str, 'confianza': float,
            'frase_generada': str, 'fuente_calificador': str | None,
            'caja_deteccion': list[dict] | None}`, o
            `{'status': 'error', 'message': str}` si la imagen no es válida,
            Vision no respondió correctamente o no se localizó ningún objeto.
    """
    try:
        imagen_validada = validar_imagen_base64(imagen_base64)
    except ValueError as error:
        return {'status': 'error', 'message': str(error)}

    try:
        punto_objetivo = _sanear_punto_objetivo(json.loads(punto_objetivo_json)) if punto_objetivo_json else None
    except (TypeError, ValueError):
        punto_objetivo = None

    resultado_vision = analizar_imagen_google_vision(imagen_validada)
    if resultado_vision['status'] != 'success':
        return {'status': 'error', 'message': resultado_vision['message']}

    resultado_frase = generar_frase_deteccion(
        resultado_vision, _nivel_dificultad_usuario(usuario), usuario.id, punto_objetivo
    )
    if resultado_frase is None:
        return {'status': 'error', 'message': 'No pudimos reconocer ningún objeto. Intenta acercarte más o con mejor luz.'}

    return {
        'status': 'success',
        'objeto': resultado_frase['objeto'],
        'confianza': resultado_frase['confianza'],
        'frase_generada': resultado_frase['frase_generada'],
        'fuente_calificador': resultado_frase['fuente_calificador'],
        'caja_deteccion': resultado_frase['caja_deteccion'],
    }


def _construir_reaccion_avatar(correcta):
    """Construye los datos planos `{tipo, mensaje}` de la reacción del avatar para un intento."""
    tipo = 'pronunciacion_correcta' if correcta else 'pronunciacion_incorrecta'
    return {'tipo': tipo, 'mensaje': obtener_reaccion(tipo)}


def procesar_evaluacion_pronunciacion(usuario, archivo_audio, frase_referencia):
    """
    Orquesta la evaluación de la pronunciación de la frase generada (G.1, endpoint `/camara/evaluar/`).

    Reutiliza el mismo pipeline de Azure Speech que `niveles`/`desafio`/
    `historias`: valida y procesa el audio recibido, lo evalúa contra
    `frase_referencia` y, si el puntaje supera `UMBRAL_SUPERACION_NIVEL`,
    otorga monedas (buscando la `FraseTemplate` que coincide exactamente con
    `frase_referencia` para conocer su recompensa; si no existe, se usa
    `RECOMPENSA_MONEDAS_FALLBACK`).

    Args:
        usuario: instancia de `UsuarioCustom` (estudiante autenticado).
        archivo_audio: archivo de audio subido (`request.FILES.get('audio')`).
        frase_referencia (str): frase que el estudiante debía
            pronunciar (devuelto previamente por `procesar_captura_imagen`).

    Returns:
        dict: si `frase_referencia` está vacío o la evaluación de
            Azure falla, `{'status': 'error', 'message': str}`. Si todo sale
            bien, `{'status': 'success', 'correcta': bool, 'score': float,
            'score_exactitud': float, 'palabras': list,
            'monedas_ganadas': int, 'monedas_totales': int,
            'reaccion_avatar': dict}`.

    Raises:
        Exception: cualquier error inesperado se loguea con
            `logging.error(..., exc_info=True)` y se relanza; la vista que
            invoca esta función es responsable de convertirlo en una
            respuesta HTTP genérica.
    """
    if not frase_referencia or not frase_referencia.strip():
        return {'status': 'error', 'message': 'Falta la frase de referencia a evaluar.'}

    ruta_audio_temporal = None
    try:
        ruta_audio_temporal = procesar_audio_subido(archivo_audio)
        resultado_azure = evaluar_pronunciacion_azure(ruta_audio_temporal, frase_referencia)
    except ValueError as error:
        return {'status': 'error', 'message': str(error)}
    except Exception:
        logger.error('Error inesperado al procesar la evaluación de la cámara inteligente', exc_info=True)
        raise
    finally:
        if ruta_audio_temporal and os.path.exists(ruta_audio_temporal):
            os.remove(ruta_audio_temporal)

    if resultado_azure['status'] != 'success':
        return {'status': 'error', 'message': resultado_azure['message']}

    score_global = resultado_azure['score_global']
    correcta = score_global >= UMBRAL_SUPERACION_NIVEL

    RegistroActividad.objects.registrar(usuario, RegistroActividad.TIPO_CAMARA, score_global)

    monedas_ganadas = 0
    monedas_totales = None
    if correcta:
        frase_template = FraseTemplate.objects.filter(frase_plantilla=frase_referencia).first()
        monedas_ganadas = frase_template.recompensa_monedas if frase_template else RECOMPENSA_MONEDAS_FALLBACK
        monedas_totales = otorgar_monedas(usuario, monedas_ganadas, concepto='camara_objeto_identificado')

    return {
        'status': 'success',
        'correcta': correcta,
        'score': score_global,
        'score_exactitud': resultado_azure.get('score_exactitud'),
        'palabras': resultado_azure.get('palabras', []),
        'monedas_ganadas': monedas_ganadas,
        'monedas_totales': monedas_totales,
        'reaccion_avatar': _construir_reaccion_avatar(correcta),
    }
