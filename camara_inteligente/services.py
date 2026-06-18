"""
Capa de servicios del módulo `camara_inteligente` (Módulo G del Master Plan).

Contiene la lógica de negocio del flujo de Cámara Inteligente: validación de
la imagen capturada, reconocimiento de objetos vía Google Cloud Vision,
generación de la frase de práctica según el objeto detectado y el nivel del
estudiante, y evaluación de la pronunciación de esa frase reutilizando el
mismo pipeline de Azure Speech que el resto de la plataforma.

Las vistas de `camara_inteligente/views.py` deben mantenerse "delgadas" y
delegar toda la lógica de negocio a las funciones definidas aquí.
"""

import base64
import binascii
import logging
import os

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

from .models import FraseTemplate

logger = logging.getLogger(__name__)

# Tamaño máximo permitido para las imágenes capturadas por la cámara (en bytes).
TAMANO_MAXIMO_IMAGEN_BYTES = getattr(settings, 'FILE_UPLOAD_MAX_MEMORY_SIZE', 5 * 1024 * 1024)

# Tipos MIME aceptados como imagen válida.
TIPOS_MIME_IMAGEN_VALIDOS = {'image/jpeg', 'image/png'}

# Monedas otorgadas cuando el objeto detectado no tiene una `FraseTemplate`
# asociada (frase genérica de respaldo).
RECOMPENSA_MONEDAS_FALLBACK = 5

# Plantilla genérica usada cuando ninguna etiqueta de Vision tiene traducción
# o `FraseTemplate` registrada, para que el flujo nunca se interrumpa.
FRASE_GENERICA = '¡Qué interesante! Veo algo llamado {objeto}. ¿Puedes describirlo en voz alta?'

# Monedas otorgadas cuando la frase fue generada dinámicamente por el LLM
# (Azure OpenAI) en lugar de provenir de una `FraseTemplate` registrada en BD.
# Se usa el mismo valor que la frase genérica de respaldo (RECOMPENSA_MONEDAS_FALLBACK)
# porque ambas son frases "no curadas manualmente"; si en el futuro se quiere
# incentivar más el uso del LLM basta con subir esta constante.
RECOMPENSA_MONEDAS_LLM = RECOMPENSA_MONEDAS_FALLBACK

# Versión de la API de Azure OpenAI. No existe una env var específica para esto
# en el proyecto, así que se fija un valor estable y reciente como constante.
AZURE_OPENAI_API_VERSION = '2024-10-21'

# Tiempo de espera máximo (segundos) para la llamada a Azure OpenAI, para que
# nunca bloquee el flujo de captura de la cámara si el servicio está lento.
AZURE_OPENAI_TIMEOUT_SEGUNDOS = 4

# Tiempo (segundos) que se cachea una frase generada por el LLM para un mismo
# objeto y nivel de dificultad. 24 horas: las frases pueden variar día a día
# sin necesidad de llamar al LLM en cada captura del mismo objeto.
CACHE_FRASE_LLM_TIMEOUT_SEGUNDOS = 60 * 60 * 24

# Diccionario de traducción de las etiquetas en inglés que devuelve Google
# Cloud Vision a las palabras en español usadas en `FraseTemplate.objeto_keyword`.
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


def generar_frase_llm(objeto_es, nivel_usuario):
    """
    Genera una frase corta de práctica para `objeto_es` usando Azure OpenAI.

    El resultado se cachea (vía `django.core.cache.cache`) por la combinación
    `(objeto_es, nivel_usuario)` durante `CACHE_FRASE_LLM_TIMEOUT_SEGUNDOS`,
    para no llamar al LLM repetidamente con el mismo objeto y nivel.

    El prompt separa una instrucción de sistema fija (reglas de la frase:
    idioma, longitud, dificultad, contenido apropiado para niños) de un
    mensaje de usuario que solo contiene el dato `objeto_es`. Aunque
    `objeto_es` proviene de un diccionario interno fijo (`TRADUCCION_OBJETOS`)
    y no de input arbitrario, se mantiene la separación system/user como
    buena práctica.

    Args:
        objeto_es (str): nombre en español del objeto detectado (ej. "lápiz").
        nivel_usuario (int): nivel de dificultad del estudiante (1-5).

    Returns:
        str | None: la frase generada, o `None` si la clave está en cache
            como fallo previo, o si la llamada al LLM falla por cualquier
            motivo (timeout, error de red, credenciales, respuesta vacía o
            malformada). Nunca lanza una excepción hacia el caller.
    """
    clave_cache = f'frase_llm_camara_{objeto_es}_{nivel_usuario}'
    frase_en_cache = cache.get(clave_cache)
    if frase_en_cache is not None:
        return frase_en_cache

    try:
        cliente = AzureOpenAI(
            api_key=settings.AZURE_OPENAI_API_KEY,
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_version=AZURE_OPENAI_API_VERSION,
        )
        respuesta = cliente.chat.completions.create(
            model=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
            messages=[
                {
                    'role': 'system',
                    'content': (
                        'Generas UNA sola frase corta en español (máximo 12 palabras), '
                        'pensada para que un niño con dislexia practique pronunciación. '
                        f'La dificultad debe corresponder a un nivel {nivel_usuario} de 5 '
                        '(1 = muy simple, 5 = más elaborado). El contenido debe ser siempre '
                        'apropiado para niños, positivo y sin ambigüedad. Responde únicamente '
                        'con la frase, sin comillas ni explicaciones adicionales.'
                    ),
                },
                {'role': 'user', 'content': objeto_es},
            ],
            timeout=AZURE_OPENAI_TIMEOUT_SEGUNDOS,
        )
        frase_generada = respuesta.choices[0].message.content.strip()
        if not frase_generada:
            raise ValueError('La respuesta del LLM llegó vacía.')
    except Exception:
        logger.error(
            'Error al generar frase con Azure OpenAI para objeto=%s nivel=%s',
            objeto_es, nivel_usuario, exc_info=True,
        )
        return None

    cache.set(clave_cache, frase_generada, CACHE_FRASE_LLM_TIMEOUT_SEGUNDOS)
    return frase_generada


def generar_frase_objeto(etiquetas_vision, nivel_usuario):
    """
    Genera la frase de práctica para el objeto detectado por Google Vision (G.2).

    Recorre las etiquetas devueltas por Vision (ordenadas por confianza
    descendente) y traduce cada una al español mediante `TRADUCCION_OBJETOS`.
    Para la primera etiqueta traducible, busca una `FraseTemplate` cuyo
    `nivel_dificultad` sea menor o igual al del estudiante; si no existe
    ninguna en ese rango, usa cualquier `FraseTemplate` de ese objeto. Si
    ninguna etiqueta es traducible o no hay `FraseTemplate` registrada,
    devuelve una frase genérica de respaldo con la primera etiqueta
    detectada, para que el flujo nunca se interrumpa.

    Args:
        etiquetas_vision (list[dict]): etiquetas devueltas por
            `servicios.utils.analizar_imagen_google_vision`, cada una con
            `description` (str, en inglés) y `score` (float).
        nivel_usuario (int): nivel de dificultad del estudiante (1-5), ver
            `_nivel_dificultad_usuario`.

    Returns:
        dict | None: `{'objeto': str, 'confianza': float,
            'frase_generada': str, 'recompensa_monedas': int}`, o `None` si
            `etiquetas_vision` está vacía.
    """
    if not etiquetas_vision:
        return None

    etiquetas_ordenadas = sorted(etiquetas_vision, key=lambda etiqueta: etiqueta['score'], reverse=True)

    for etiqueta in etiquetas_ordenadas:
        objeto = TRADUCCION_OBJETOS.get(etiqueta['description'].lower())
        if not objeto:
            continue

        frase_llm = generar_frase_llm(objeto, nivel_usuario)
        if frase_llm:
            return {
                'objeto': objeto,
                'confianza': etiqueta['score'],
                'frase_generada': frase_llm,
                'recompensa_monedas': RECOMPENSA_MONEDAS_LLM,
            }

        frase = (
            FraseTemplate.objects.filter(objeto_keyword=objeto, nivel_dificultad__lte=nivel_usuario).order_by('?').first()
            or FraseTemplate.objects.filter(objeto_keyword=objeto).order_by('?').first()
        )
        if frase:
            return {
                'objeto': objeto,
                'confianza': etiqueta['score'],
                'frase_generada': frase.frase_plantilla,
                'recompensa_monedas': frase.recompensa_monedas,
            }

    etiqueta_principal = etiquetas_ordenadas[0]
    objeto = TRADUCCION_OBJETOS.get(etiqueta_principal['description'].lower(), etiqueta_principal['description'].lower())
    return {
        'objeto': objeto,
        'confianza': etiqueta_principal['score'],
        'frase_generada': FRASE_GENERICA.format(objeto=objeto),
        'recompensa_monedas': RECOMPENSA_MONEDAS_FALLBACK,
    }


def procesar_captura_imagen(usuario, imagen_base64):
    """
    Orquesta el flujo de captura de imagen (G.1, endpoint `/camara/capturar/`).

    Valida la imagen recibida, la envía a Google Cloud Vision y construye la
    frase de práctica correspondiente al objeto detectado y al nivel del
    estudiante.

    Args:
        usuario: instancia de `UsuarioCustom` (estudiante autenticado).
        imagen_base64 (str): imagen capturada por la cámara, en base64 (con
            o sin prefijo de *data URL*).

    Returns:
        dict: `{'status': 'success', 'objeto': str, 'confianza': float,
            'frase_generada': str}`, o `{'status': 'error', 'message': str}`
            si la imagen no es válida, Vision no respondió correctamente o
            no se detectó ningún objeto.
    """
    try:
        imagen_validada = validar_imagen_base64(imagen_base64)
    except ValueError as error:
        return {'status': 'error', 'message': str(error)}

    resultado_vision = analizar_imagen_google_vision(imagen_validada)
    if resultado_vision['status'] != 'success':
        return {'status': 'error', 'message': resultado_vision['message']}

    resultado_frase = generar_frase_objeto(resultado_vision['etiquetas'], _nivel_dificultad_usuario(usuario))
    if resultado_frase is None:
        return {'status': 'error', 'message': 'No pudimos reconocer ningún objeto. Intenta acercarte más o con mejor luz.'}

    return {
        'status': 'success',
        'objeto': resultado_frase['objeto'],
        'confianza': resultado_frase['confianza'],
        'frase_generada': resultado_frase['frase_generada'],
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
        frase_referencia (str): frase que el estudiante debía pronunciar
            (devuelta previamente por `procesar_captura_imagen`).

    Returns:
        dict: si `frase_referencia` está vacía o la evaluación de Azure
            falla, `{'status': 'error', 'message': str}`. Si todo sale bien,
            `{'status': 'success', 'correcta': bool, 'score': float,
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
