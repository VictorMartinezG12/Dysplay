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
import json
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
AZURE_OPENAI_TIMEOUT_SEGUNDOS = 8

# Tiempo (segundos) que se cachea una frase generada por el LLM para un mismo
# objeto y nivel de dificultad. 24 horas: las frases pueden variar día a día
# sin necesidad de llamar al LLM en cada captura del mismo objeto.
CACHE_FRASE_LLM_TIMEOUT_SEGUNDOS = 60 * 60 * 24

# Diccionario de traducción de respaldo, usado SOLO cuando Azure OpenAI falla
# por completo (timeout/error de red): permite caer en una `FraseTemplate`
# curada para los objetos más comunes en vez de la `FRASE_GENERICA`. Ya NO es
# el límite de qué objetos puede practicar el niño — ver `generar_frase_objeto`,
# que primero intenta el LLM con CUALQUIER etiqueta que entregue Vision.
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


def generar_objeto_y_frase_llm(etiqueta_en, nivel_usuario):
    """
    Traduce `etiqueta_en` (etiqueta en inglés devuelta por Google Vision) al
    español y genera, en el mismo llamado a Azure OpenAI, una frase corta de
    práctica para esa palabra.

    Permite que CUALQUIER objeto detectado por Vision (no solo los ~80 del
    diccionario `TRADUCCION_OBJETOS`) tenga su frase de práctica, sin
    depender de un diccionario fijo. El resultado se cachea (vía
    `django.core.cache.cache`) por la combinación `(etiqueta_en, nivel_usuario)`
    durante `CACHE_FRASE_LLM_TIMEOUT_SEGUNDOS`, para no llamar al LLM
    repetidamente con el mismo objeto y nivel.

    Args:
        etiqueta_en (str): etiqueta en inglés tal cual la entrega Google
            Vision (ej. "pencil", "dolphin", "hairbrush").
        nivel_usuario (int): nivel de dificultad del estudiante (1-5).

    Returns:
        dict | None: `{'objeto': str, 'frase': str}` con el objeto traducido
            al español y la frase generada, o `None` si la llamada al LLM
            falla por cualquier motivo (timeout, error de red, credenciales,
            respuesta vacía o malformada). Nunca lanza una excepción hacia
            el caller.
    """
    clave_cache = f'frase_llm_camara_{etiqueta_en.lower()}_{nivel_usuario}'
    resultado_en_cache = cache.get(clave_cache)
    if resultado_en_cache is not None:
        return resultado_en_cache

    try:
        cliente = AzureOpenAI(
            api_key=settings.AZURE_OPENAI_API_KEY,
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_version=AZURE_OPENAI_API_VERSION,
        )
        # El modelo configurado (Phi-4-mini-instruct) no respeta de forma confiable
        # una instrucción de sistema separada ni el parámetro `response_format`
        # (responde con campos de su propia invención en vez del esquema pedido).
        # Un único mensaje de usuario con un ejemplo completo de la forma esperada
        # (few-shot) incrustado en el prompt produce resultados consistentes; mismo
        # patrón que `historias.services.generar_historia_completa_ia`.
        ejemplo_formato = {'objeto': 'lápiz', 'frase': 'El lápiz amarillo escribe en el cuaderno.'}
        prompt = (
            f'La etiqueta en inglés "{etiqueta_en}" identifica un objeto detectado por la '
            'cámara de un niño. Traduce esa etiqueta a UNA sola palabra en español (el '
            'nombre común del objeto) y escribe una frase corta (máximo 10 palabras) en '
            f'español para que el niño practique pronunciación usando esa palabra. La '
            f'dificultad de la frase debe corresponder a un nivel {nivel_usuario} de 5 '
            '(1 = muy simple, 5 = más elaborada). El contenido debe ser siempre positivo y '
            'apropiado para niños. Responde ÚNICAMENTE con un JSON válido, sin texto antes '
            'ni después, sin markdown, con EXACTAMENTE esta forma (el siguiente es solo un '
            'ejemplo de formato, tu objeto y frase deben corresponder a la etiqueta dada):\n'
            + json.dumps(ejemplo_formato, ensure_ascii=False)
        )
        respuesta = cliente.chat.completions.create(
            model=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
            messages=[{'role': 'user', 'content': prompt}],
            temperature=0.3,
            max_tokens=80,
            timeout=AZURE_OPENAI_TIMEOUT_SEGUNDOS,
        )
        contenido = respuesta.choices[0].message.content.strip()
        datos = json.loads(contenido)
        objeto = datos.get('objeto')
        frase = datos.get('frase')
        # Defensa adicional: si el modelo no devuelve el JSON esperado, o la frase
        # es un párrafo largo (razonamiento, preguntas, disculpas), se descarta y
        # se cae al fallback de TRADUCCION_OBJETOS/FraseTemplate/FRASE_GENERICA.
        if (
            not objeto or not isinstance(objeto, str)
            or not frase or not isinstance(frase, str)
            or len(frase.split()) > 20
        ):
            raise ValueError('La respuesta del LLM no tiene el objeto/frase esperados.')
    except Exception:
        logger.error(
            'Error al generar objeto/frase con Azure OpenAI para etiqueta=%s nivel=%s',
            etiqueta_en, nivel_usuario, exc_info=True,
        )
        return None

    resultado = {'objeto': objeto.strip(), 'frase': frase.strip()}
    cache.set(clave_cache, resultado, CACHE_FRASE_LLM_TIMEOUT_SEGUNDOS)
    return resultado


def generar_frase_objeto(etiquetas_vision, nivel_usuario):
    """
    Genera la frase de práctica para el objeto detectado por Google Vision (G.2).

    Toma la etiqueta de mayor confianza devuelta por Vision (en inglés, tal
    cual la entrega la API) e intenta generar el objeto en español y su
    frase de práctica con Azure OpenAI (`generar_objeto_y_frase_llm`): así
    CUALQUIER objeto que Vision reconozca puede practicarse, no solo los
    registrados en `TRADUCCION_OBJETOS`.

    Si el LLM falla por completo (timeout/error de red), se cae a un
    respaldo de emergencia: si la etiqueta está en `TRADUCCION_OBJETOS`, se
    busca una `FraseTemplate` para ese objeto (preferentemente del nivel del
    estudiante, o cualquier nivel si no hay); si tampoco hay `FraseTemplate`,
    se devuelve `FRASE_GENERICA` con el objeto traducido (o la etiqueta en
    inglés si ni siquiera está en el diccionario), para que el flujo nunca
    se interrumpa.

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
    etiqueta_principal = etiquetas_ordenadas[0]
    etiqueta_en = etiqueta_principal['description'].lower()

    resultado_llm = generar_objeto_y_frase_llm(etiqueta_en, nivel_usuario)
    if resultado_llm:
        return {
            'objeto': resultado_llm['objeto'],
            'confianza': etiqueta_principal['score'],
            'frase_generada': resultado_llm['frase'],
            'recompensa_monedas': RECOMPENSA_MONEDAS_LLM,
        }

    objeto_respaldo = TRADUCCION_OBJETOS.get(etiqueta_en)
    if objeto_respaldo:
        frase = (
            FraseTemplate.objects.filter(objeto_keyword=objeto_respaldo, nivel_dificultad__lte=nivel_usuario).order_by('?').first()
            or FraseTemplate.objects.filter(objeto_keyword=objeto_respaldo).order_by('?').first()
        )
        if frase:
            return {
                'objeto': objeto_respaldo,
                'confianza': etiqueta_principal['score'],
                'frase_generada': frase.frase_plantilla,
                'recompensa_monedas': frase.recompensa_monedas,
            }

    objeto_generico = objeto_respaldo or etiqueta_en
    return {
        'objeto': objeto_generico,
        'confianza': etiqueta_principal['score'],
        'frase_generada': FRASE_GENERICA.format(objeto=objeto_generico),
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
