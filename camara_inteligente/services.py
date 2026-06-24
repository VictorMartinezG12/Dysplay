"""
Capa de servicios del módulo `camara_inteligente` (Módulo G del Master Plan).

Contiene la lógica de negocio del flujo de Cámara Inteligente: validación de
la imagen capturada, reconocimiento del objeto y generación de la frase de
práctica en una sola llamada multimodal a Gemini (objeto + frase, según el
nivel del estudiante), y evaluación de la pronunciación de esa frase
reutilizando el mismo pipeline de Azure Speech que el resto de la plataforma.

Las vistas de `camara_inteligente/views.py` deben mantenerse "delgadas" y
delegar toda la lógica de negocio a las funciones definidas aquí.
"""

import base64
import binascii
import json
import logging
import os
import re

import magic
from django.conf import settings
from django.core.cache import cache
from google import genai
from google.genai import types

from avatar.reactions import obtener_reaccion
from estadisticas.models import RegistroActividad
from niveles.models import ProgresoEstudiante
from niveles.services import (
    UMBRAL_SUPERACION_NIVEL,
    evaluar_pronunciacion_azure,
    procesar_audio_subido,
)
from recompensas.services import otorgar_monedas

from .models import ConfiguracionCamara, FraseTemplate

logger = logging.getLogger(__name__)

# Tamaño máximo permitido para las imágenes capturadas por la cámara (en bytes).
TAMANO_MAXIMO_IMAGEN_BYTES = getattr(settings, 'FILE_UPLOAD_MAX_MEMORY_SIZE', 5 * 1024 * 1024)

# Tipos MIME aceptados como imagen válida.
TIPOS_MIME_IMAGEN_VALIDOS = {'image/jpeg', 'image/png'}

# Monedas otorgadas cuando el objeto detectado no tiene una `FraseTemplate`
# asociada (frase genérica de respaldo).
RECOMPENSA_MONEDAS_FALLBACK = 5

# Frase genérica usada en modo normal cuando Gemini falla y no hay ninguna
# `FraseTemplate` guardada para el objeto, para que el flujo nunca se
# interrumpa.
FRASE_GENERICA = '¡Qué interesante! Veo algo llamado {objeto}. ¿Puedes describirlo en voz alta?'

# Frase de última barrera usada SOLO en "modo económico" (`ConfiguracionCamara`)
# cuando ni siquiera hay una `FraseTemplate` guardada para el objeto: a
# diferencia de `FRASE_GENERICA`, no pretende ser una frase elaborada, solo
# pide pronunciar el nombre del objeto (no se llama a Gemini en absoluto en
# este modo).
FRASE_SOLO_NOMBRE = 'Este objeto se llama {objeto}. Dilo en voz alta: {objeto}.'

# Nombre genérico usado como último recurso para `FRASE_GENERICA` cuando
# Gemini falló Y no había `clase_offline` (COCO-SSD) disponible para
# identificar siquiera aproximadamente el objeto.
OBJETO_GENERICO_SIN_IDENTIFICAR = 'algo'

# Monedas otorgadas cuando la frase fue generada dinámicamente por Gemini en
# lugar de provenir de una `FraseTemplate` registrada en BD. Se usa el mismo
# valor que la frase genérica de respaldo (RECOMPENSA_MONEDAS_FALLBACK)
# porque ambas son frases "no curadas manualmente"; si en el futuro se quiere
# incentivar más el uso de Gemini basta con subir esta constante.
RECOMPENSA_MONEDAS_GEMINI = RECOMPENSA_MONEDAS_FALLBACK

# Modelo de Gemini usado para reconocer el objeto y generar la frase en una
# sola llamada multimodal. "Flash" porque la latencia importa: el niño está
# esperando frente a la cámara (ver experimento_gemini/resultados.json, que
# motivó esta migración desde Vision + Azure OpenAI).
MODELO_GEMINI_CAMARA = 'gemini-2.5-flash'

# Tiempo de espera máximo (milisegundos) para la llamada a Gemini, para que
# nunca bloquee el flujo de captura de la cámara si el servicio está lento.
TIMEOUT_GEMINI_CAMARA_MS = 10_000

# Tiempo (segundos) que se cachea el "eco" de corto plazo por estudiante: si
# vuelve a detectar exactamente el mismo objeto (misma `clase_offline` de
# COCO-SSD) dentro de esta ventana, se le repite la misma frase de la vez
# anterior sin llamar a Gemini, para no generar costo extra por capturas
# casi inmediatas del mismo objeto. 15 minutos: cubre una sesión de juego
# típica sin necesidad de que cierre la página.
CACHE_ECO_CAMARA_TIMEOUT_SEGUNDOS = 60 * 15

# Cantidad máxima de variantes de `FraseTemplate` que se auto-guardan por
# combinación de objeto/nivel (ver `_guardar_frase_template_automatica`): pasado
# este límite, ya hay suficiente variedad y se deja de insertar filas nuevas
# para esa combinación, para no crecer la tabla sin límite con el tiempo.
MAXIMO_VARIANTES_FRASE_AUTOGUARDADA = 5

# Longitud máxima aceptada para `clase_offline` (nombre de clase de
# COCO-SSD, ej. "bottle", "cup"): nunca debería superar unas pocas palabras;
# cualquier cosa más larga se trata como ausente (cliente malformado).
LONGITUD_MAXIMA_CLASE_OFFLINE = 40

# Diccionario de traducción usado en "modo económico" (cuando no se llama a
# Gemini en absoluto) para traducir la `clase_offline` detectada localmente
# por COCO-SSD (TensorFlow.js, ver `static/js/camara_inteligente/camara.js`)
# a español. Las claves son las 80 clases que reconoce COCO-SSD.
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
    'sports ball': 'pelota',
    'shoe': 'zapato',
    'footwear': 'zapato',
    'cup': 'taza',
    'mug': 'taza',
    'bottle': 'botella',
    'wine glass': 'copa',
    'flower': 'flor',
    'potted plant': 'planta',
    'tree': 'árbol',
    'house': 'casa',
    'clock': 'reloj',
    'mobile phone': 'teléfono',
    'cell phone': 'teléfono',
    'telephone': 'teléfono',
    'smartphone': 'teléfono',
    'laptop': 'computadora',
    'computer': 'computadora',
    'tv': 'televisor',
    'tvmonitor': 'televisor',
    'bicycle': 'bicicleta',
    'motorbike': 'motocicleta',
    'bird': 'pájaro',
    'fish': 'pez',
    'banana': 'plátano',
    'orange': 'naranja',
    'bread': 'pan',
    'spoon': 'cuchara',
    'fork': 'tenedor',
    'knife': 'cuchillo',
    'plate': 'plato',
    'tableware': 'plato',
    'bowl': 'tazón',
    'bed': 'cama',
    'couch': 'sofá',
    'sofa': 'sofá',
    'lamp': 'lámpara',
    'lighting': 'lámpara',
    'window': 'ventana',
    'door': 'puerta',
    'hat': 'sombrero',
    'shirt': 'camisa',
    't-shirt': 'camisa',
    'handbag': 'bolso',
    'backpack': 'mochila',
    'bag': 'bolso',
    'suitcase': 'maleta',
    'key': 'llave',
    'scissors': 'tijeras',
    'pen': 'bolígrafo',
    'notebook': 'cuaderno',
    'ruler': 'regla',
    'umbrella': 'sombrilla',
    'glasses': 'lentes',
    'sunglasses': 'gafas de sol',
    'mirror': 'espejo',
    'sock': 'calcetín',
    'balloon': 'globo',
    'kite': 'cometa',
    'drum': 'tambor',
    'guitar': 'guitarra',
    'piano': 'piano',
    'teddy bear': 'oso de peluche',
    'doll': 'muñeca',
    'toy': 'muñeca',
    'train': 'tren',
    'airplane': 'avión',
    'aeroplane': 'avión',
    'boat': 'barco',
    'candle': 'vela',
    'egg': 'huevo',
    'carrot': 'zanahoria',
    'strawberry': 'fresa',
    'grape': 'uva',
    'pizza': 'pizza',
    'donut': 'dona',
    'cake': 'pastel',
    'sandwich': 'sándwich',
    'helmet': 'casco',
    'butterfly': 'mariposa',
    'headphones': 'audífonos',
    'earphones': 'audífonos',
    'keyboard': 'teclado',
    'mouse': 'mouse',
    'watch': 'reloj',
    'wristwatch': 'reloj',
    'remote': 'control remoto',
    'remote control': 'control remoto',
    'speaker': 'parlante',
    'camera': 'cámara',
    'tablet computer': 'tableta',
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
    'fan': 'ventilador',
    'person': 'persona',
    'horse': 'caballo',
    'sheep': 'oveja',
    'cow': 'vaca',
    'elephant': 'elefante',
    'bear': 'oso',
    'zebra': 'cebra',
    'giraffe': 'jirafa',
    'frisbee': 'frisbee',
    'skis': 'esquís',
    'snowboard': 'snowboard',
    'skateboard': 'patineta',
    'surfboard': 'tabla de surf',
    'tennis racket': 'raqueta de tenis',
    'baseball bat': 'bate de béisbol',
    'baseball glove': 'guante de béisbol',
    'oven': 'horno',
    'toaster': 'tostadora',
    'sink': 'lavabo',
    'refrigerator': 'refrigerador',
    'vase': 'jarrón',
    'scissor': 'tijeras',
    'hair drier': 'secadora de pelo',
    'toothbrush ': 'cepillo de dientes',
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
        tuple[bytes, str]: `(imagen_bytes, mime_type)`, donde `mime_type` es
            el tipo MIME real detectado (`image/jpeg` o `image/png`), listo
            para enviarse a Gemini.

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

    return imagen_bytes, tipo_mime_detectado


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


def _sanear_clase_offline(clase_offline):
    """
    Valida la `clase_offline` (nombre de clase de COCO-SSD, ej. `"bottle"`)
    enviada por el cliente.

    Igual de defensivo que `_sanear_punto_objetivo`: cualquier valor que no
    sea un string corto y no vacío se trata como ausente, nunca rompe el
    flujo de captura.

    Args:
        clase_offline: valor crudo recibido del cliente.

    Returns:
        str | None: la clase en minúsculas y sin espacios sobrantes, o
            `None` si no tiene la forma esperada.
    """
    if not isinstance(clase_offline, str):
        return None
    clase = clase_offline.strip().lower()
    if not clase or len(clase) > LONGITUD_MAXIMA_CLASE_OFFLINE:
        return None
    return clase


# Cantidad de repeticiones consecutivas de la misma palabra a partir de la
# cual una respuesta se considera "atascada" (degenerada) y se descarta. Una
# frase normal casi nunca repite la misma palabra varias veces seguidas; esto
# es una red de seguridad genérica por si Gemini alguna vez degenera de forma
# similar a lo que hacía el LLM débil de Azure que se retiró en esta
# migración (ver `_tiene_repeticion_degenerada`).
MAXIMO_REPETICIONES_CONSECUTIVAS_PALABRA = 3


def _tiene_repeticion_degenerada(texto):
    """
    Detecta si `texto` tiene la misma palabra repetida de forma mecánica más
    de `MAXIMO_REPETICIONES_CONSECUTIVAS_PALABRA` veces seguidas (ej. "peina
    peina peina peina peina"), un patrón de degeneración conocido en modelos
    pequeños (Azure Phi-4-mini-instruct, ya retirado de este módulo): el
    modelo arranca bien y luego se "atasca" en un bucle de la misma palabra.
    Se mantiene como defensa genérica también para la frase de Gemini.

    Args:
        texto (str): texto a evaluar (ej. una frase generada).

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


def _construir_prompt_gemini(nivel_usuario, punto_objetivo):
    """
    Construye el prompt en español pedido a Gemini para reconocer el objeto
    principal de la imagen y generar, en la misma respuesta, una frase corta
    de práctica de pronunciación.

    Args:
        nivel_usuario (int): nivel de dificultad del estudiante (1-5).
        punto_objetivo (dict | None): `{'x', 'y'}` normalizado 0-1 (centro
            del objeto que el niño tenía resaltado en vivo con COCO-SSD al
            capturar), o `None` si no se recibió. Se usa solo como pista
            para desambiguar cuando hay varios objetos en la foto.

    Returns:
        str: el prompt completo a enviar junto con la imagen.
    """
    pista_punto = ''
    if punto_objetivo:
        pista_punto = (
            f' Si hay varios objetos en la imagen, el niño tenía centrada la cámara cerca '
            f'del punto normalizado (x={punto_objetivo["x"]:.2f}, y={punto_objetivo["y"]:.2f}) '
            '(0,0 = esquina superior izquierda, 1,1 = esquina inferior derecha); prioriza ese '
            'objeto sobre otros que aparezcan de fondo.'
        )
    return (
        'Eres parte de una app educativa para niños con dislexia que practican lectura en '
        'voz alta mostrando objetos a la cámara. Mira la imagen y responde ÚNICAMENTE con un '
        'JSON (sin markdown, sin explicación) con esta forma exacta: '
        '{"objeto": "<nombre del objeto principal, en español, una o dos palabras>", '
        '"frase": "<frase corta y natural en español, máximo 10 palabras, para que el niño la '
        f'lea en voz alta y practique pronunciación>"}}.{pista_punto} La frase debe '
        f'corresponder a un nivel de dificultad {nivel_usuario} de 5 (1 = muy simple, '
        '5 = más elaborada), y su contenido debe ser siempre positivo y apropiado para niños.'
    )


def _generar_objeto_y_frase_gemini(imagen_bytes, mime_type, nivel_usuario, punto_objetivo):
    """
    Reconoce el objeto principal de `imagen_bytes` y genera su frase de
    práctica en una sola llamada multimodal a Gemini (`MODELO_GEMINI_CAMARA`).

    Reemplaza el pipeline anterior (Google Vision + dos llamadas a Azure
    OpenAI) tras un experimento real (`experimento_gemini/resultados.json`)
    que mostró que Azure OpenAI fallaba por rate limit en la mayoría de
    capturas, mientras que Gemini resolvió objeto+frase en un solo paso, más
    rápido y siempre en español.

    Args:
        imagen_bytes (bytes): imagen ya validada (ver `validar_imagen_base64`).
        mime_type (str): tipo MIME real de la imagen (`image/jpeg` o `image/png`).
        nivel_usuario (int): nivel de dificultad del estudiante (1-5).
        punto_objetivo (dict | None): `{'x', 'y'}` ya saneado, o `None`.

    Returns:
        dict | None: `{'objeto': str, 'frase': str}`, o `None` si la llamada
            falla por cualquier motivo (timeout, error de red, credenciales,
            JSON inválido, o frase vacía/demasiado larga/degenerada). Nunca
            lanza una excepción hacia el caller.
    """
    try:
        cliente = genai.Client(
            api_key=settings.GEMINI_API_KEY,
            http_options=types.HttpOptions(timeout=TIMEOUT_GEMINI_CAMARA_MS),
        )
        respuesta = cliente.models.generate_content(
            model=MODELO_GEMINI_CAMARA,
            contents=[
                _construir_prompt_gemini(nivel_usuario, punto_objetivo),
                types.Part.from_bytes(data=imagen_bytes, mime_type=mime_type),
            ],
        )
        texto_respuesta = (respuesta.text or '').strip()
        if texto_respuesta.startswith('```'):
            texto_respuesta = texto_respuesta.strip('`')
            if texto_respuesta.lower().startswith('json'):
                texto_respuesta = texto_respuesta[4:]
            texto_respuesta = texto_respuesta.strip()

        datos = json.loads(texto_respuesta)
        objeto = str(datos.get('objeto', '')).strip()
        frase = str(datos.get('frase', '')).strip().strip('"')

        if (
            not objeto
            or not frase
            or len(objeto.split()) > 4
            or len(frase.split()) > 20
            or _tiene_repeticion_degenerada(frase)
        ):
            raise ValueError('La respuesta de Gemini no tiene un objeto/frase válidos.')
    except Exception:
        logger.error(
            'Error al reconocer objeto/generar frase con Gemini (nivel=%s)', nivel_usuario, exc_info=True,
        )
        return None

    return {'objeto': objeto, 'frase': frase}


def _clave_cache_eco(usuario_id, clase_offline):
    """Clave de caché del eco de corto plazo por estudiante (ver `CACHE_ECO_CAMARA_TIMEOUT_SEGUNDOS`)."""
    return f'eco_camara_{usuario_id}_{clase_offline.lower()}'


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
    Guarda automáticamente una frase generada con éxito por Gemini como una
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
        frase (str): frase generada por Gemini.

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
        recompensa_monedas=RECOMPENSA_MONEDAS_GEMINI,
        creada_automaticamente=True,
    )


def generar_objeto_y_frase(imagen_bytes, mime_type, nivel_usuario, usuario_id, punto_objetivo=None, clase_offline=None):
    """
    Genera el objeto detectado y su frase de práctica a partir de la imagen
    capturada (G.2).

    Antes de cualquier otra cosa, revisa el "eco" de corto plazo del
    estudiante (`CACHE_ECO_CAMARA_TIMEOUT_SEGUNDOS`, 15 minutos), indexado
    por `clase_offline` (la clase de COCO-SSD detectada en vivo por el
    cliente, ver `static/js/camara_inteligente/camara.js`): si ya detectó
    exactamente la misma clase hace poco, repite la misma frase de esa vez
    sin llamar a nada. Si no hay `clase_offline` (COCO-SSD no reconoció
    ningún objeto de sus 80 clases), no hay eco posible y siempre se
    continúa con el flujo normal.

    Luego revisa `ConfiguracionCamara.obtener().modo_economico`:

    - Si está ACTIVO: nunca se llama a Gemini. Si tampoco hay
      `clase_offline`, no hay nada que practicar (se devuelve `None`). Si la
      hay, se traduce con el diccionario fijo `TRADUCCION_OBJETOS` (o se usa
      la clase en inglés tal cual si ni siquiera está ahí) y la frase sale de
      una `FraseTemplate` guardada o, si no hay ninguna, de
      `FRASE_SOLO_NOMBRE` (última barrera mínima, solo pronuncia el nombre).
    - Si está INACTIVO (modo normal): se llama a Gemini
      (`_generar_objeto_y_frase_gemini`) con la imagen completa. Si tiene
      éxito, la frase se guarda automáticamente como una nueva
      `FraseTemplate` (`_guardar_frase_template_automatica`) para que el
      banco de frases reutilizables crezca con el tiempo. Si Gemini falla,
      se cae a `FraseTemplate`/`FRASE_GENERICA` usando `clase_offline`
      traducido (o `OBJETO_GENERICO_SIN_IDENTIFICAR` si tampoco hay
      `clase_offline`) para que el flujo nunca se interrumpa.

    El resultado SIEMPRE incluye `caja_deteccion: None, fuente_calificador:
    None`: a diferencia de Google Vision, Gemini no devuelve un cuadro
    delimitador confiable. El frontend (`mostrarCajaDeteccion` en
    `camara.js`) ya degrada limpio cuando no hay caja.

    Args:
        imagen_bytes (bytes): imagen ya validada (ver `validar_imagen_base64`).
        mime_type (str): tipo MIME real de la imagen.
        nivel_usuario (int): nivel de dificultad del estudiante (1-5), ver
            `_nivel_dificultad_usuario`.
        usuario_id: id del estudiante autenticado, usado solo para la clave
            del eco de corto plazo (no se guarda nada más por estudiante).
        punto_objetivo (dict | None): `{'x', 'y'}` normalizado 0-1 ya saneado
            (ver `_sanear_punto_objetivo`), o `None` si no se recibió.
        clase_offline (str | None): clase de COCO-SSD ya saneada (ver
            `_sanear_clase_offline`), o `None` si no se recibió.

    Returns:
        dict | None: `{'objeto': str, 'frase_generada': str,
            'recompensa_monedas': int, 'fuente_calificador': None,
            'caja_deteccion': None}`, o `None` si no hay ningún objeto que
            practicar (solo posible en modo económico sin `clase_offline`).
    """
    datos_caja = {'fuente_calificador': None, 'caja_deteccion': None}

    if clase_offline:
        clave_eco = _clave_cache_eco(usuario_id, clase_offline)
        eco = cache.get(clave_eco)
        if eco is not None:
            return {**eco, **datos_caja}

    if ConfiguracionCamara.obtener().modo_economico:
        if not clase_offline:
            return None
        objeto_es = TRADUCCION_OBJETOS.get(clase_offline, clase_offline)
        frase_generada, recompensa_monedas = _resolver_frase_respaldo(objeto_es, nivel_usuario, FRASE_SOLO_NOMBRE)
    else:
        resultado_gemini = _generar_objeto_y_frase_gemini(imagen_bytes, mime_type, nivel_usuario, punto_objetivo)
        if resultado_gemini:
            objeto_es, frase_generada = resultado_gemini['objeto'], resultado_gemini['frase']
            recompensa_monedas = RECOMPENSA_MONEDAS_GEMINI
            _guardar_frase_template_automatica(objeto_es, nivel_usuario, frase_generada)
        else:
            objeto_fallback = TRADUCCION_OBJETOS.get(clase_offline, clase_offline) if clase_offline else OBJETO_GENERICO_SIN_IDENTIFICAR
            objeto_es = objeto_fallback
            frase_generada, recompensa_monedas = _resolver_frase_respaldo(objeto_es, nivel_usuario, FRASE_GENERICA)

    resultado = {
        'objeto': objeto_es,
        'frase_generada': frase_generada,
        'recompensa_monedas': recompensa_monedas,
    }
    if clase_offline:
        clave_eco = _clave_cache_eco(usuario_id, clase_offline)
        cache.set(clave_eco, resultado, CACHE_ECO_CAMARA_TIMEOUT_SEGUNDOS)
    return {**resultado, **datos_caja}


def procesar_captura_imagen(usuario, imagen_base64, punto_objetivo_json=None, clase_offline=None):
    """
    Orquesta el flujo de captura de imagen (G.1, endpoint `/camara/capturar/`).

    Valida la imagen recibida y construye, en una sola llamada a Gemini, el
    objeto detectado y la frase de práctica correspondiente al nivel del
    estudiante (ver `generar_objeto_y_frase`).

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
        clase_offline (str | None): clase de COCO-SSD (TensorFlow.js)
            detectada en vivo por el cliente para el objeto resaltado (ver
            `_sanear_clase_offline`), o `None` si no se envió.

    Returns:
        dict: `{'status': 'success', 'objeto': str, 'frase_generada': str,
            'fuente_calificador': None, 'caja_deteccion': None}`, o
            `{'status': 'error', 'message': str}` si la imagen no es válida
            o no se pudo reconocer ningún objeto.
    """
    try:
        imagen_bytes, mime_type = validar_imagen_base64(imagen_base64)
    except ValueError as error:
        return {'status': 'error', 'message': str(error)}

    try:
        punto_objetivo = _sanear_punto_objetivo(json.loads(punto_objetivo_json)) if punto_objetivo_json else None
    except (TypeError, ValueError):
        punto_objetivo = None

    clase_offline_saneada = _sanear_clase_offline(clase_offline)

    resultado = generar_objeto_y_frase(
        imagen_bytes, mime_type, _nivel_dificultad_usuario(usuario), usuario.id, punto_objetivo, clase_offline_saneada
    )
    if resultado is None:
        return {'status': 'error', 'message': 'No pudimos reconocer ningún objeto. Intenta acercarte más o con mejor luz.'}

    return {
        'status': 'success',
        'objeto': resultado['objeto'],
        'frase_generada': resultado['frase_generada'],
        'fuente_calificador': resultado['fuente_calificador'],
        'caja_deteccion': resultado['caja_deteccion'],
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
