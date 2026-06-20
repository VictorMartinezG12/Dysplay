import base64
import io
import json
import logging
from xml.sax.saxutils import escape

import azure.cognitiveservices.speech as speechsdk
import requests
from django.conf import settings
from PIL import Image

logger = logging.getLogger(__name__)

# Mapeo de tipo_voz (ConfiguracionGlobal.TIPO_VOZ_CHOICES) a voz neural de
# Azure Speech y al ajuste de tono (pitch) SSML correspondiente (Módulo I).
MAPA_VOZ_AZURE = {
    'nino': {'voz': 'es-MX-JorgeNeural', 'pitch': '+15%'},
    'nina': {'voz': 'es-MX-DaliaNeural', 'pitch': '+15%'},
    'adulto-masculino': {'voz': 'es-MX-JorgeNeural', 'pitch': '+0%'},
    'adulto-femenino': {'voz': 'es-MX-DaliaNeural', 'pitch': '+0%'},
}

# Mapeo de velocidad_narracion a la tasa (rate) SSML correspondiente.
MAPA_VELOCIDAD_AZURE = {
    'lenta': '-30%',
    'normal': '+0%',
    'rapida': '+30%',
}

# Endpoint REST de Google Cloud Vision para detección de objetos/logos/texto (Módulo G).
URL_GOOGLE_VISION = 'https://vision.googleapis.com/v1/images:annotate'

# Número máximo de objetos/logos a solicitar a Google Vision por imagen.
MAXIMO_ETIQUETAS_VISION = 5

# Tiempo máximo (segundos) de espera por la respuesta de Google Vision.
TIMEOUT_GOOGLE_VISION = 10


def _extraer_desglose_por_palabra(result):
    """
    Extrae el desglose de puntuación por palabra del resultado crudo de Azure.

    Azure Speech no ofrece un desglose por sílaba para español; se usa el
    desglose por palabra (incluido en el JSON de respuesta cuando
    `granularity=Phoneme`) como interpretación de "sílaba" para los
    indicadores de pronunciación del Master Plan.

    Args:
        result: objeto `SpeechRecognitionResult` devuelto por
            `speech_recognizer.recognize_once_async().get()`.

    Returns:
        list[dict]: lista de `{'palabra': str, 'score': float}`, una entrada
            por cada palabra reconocida. Devuelve `[]` si no se pudo extraer
            la información (JSON inválido o estructura inesperada).
    """
    try:
        json_crudo = result.properties.get(speechsdk.PropertyId.SpeechServiceResponse_JsonResult)
        datos = json.loads(json_crudo)
        palabras_nbest = datos['NBest'][0]['Words']
        return [
            {
                'palabra': palabra.get('Word', ''),
                'score': palabra.get('PronunciationAssessment', {}).get('AccuracyScore', 0),
            }
            for palabra in palabras_nbest
        ]
    except Exception:
        logger.error("No se pudo extraer el desglose por palabra del resultado de Azure", exc_info=True)
        return []


def evaluar_pronunciacion(audio_path, palabra_objetivo):
    """
    Función Global: Conecta con Azure Speech para evaluar la pronunciación
    de un archivo de audio contra una palabra objetivo.
    """
    # 1. Traer las llaves oficiales registradas en el settings.py
    speech_key = settings.AZURE_SPEECH_KEY
    speech_region = settings.AZURE_SPEECH_REGION

    if not speech_key or not speech_region:
        raise ValueError("Faltan las credenciales de Azure Speech en el settings.py / .env")

    # 2. Configurar Azure Speech
    speech_config = speechsdk.SpeechConfig(subscription=speech_key, region=speech_region)
    audio_config = speechsdk.audio.AudioConfig(filename=audio_path)

    # 3. Parámetros de evaluación fonética (0 a 100)
    pronunciation_config = speechsdk.PronunciationAssessmentConfig(
        reference_text=palabra_objetivo,
        grading_system=speechsdk.PronunciationAssessmentGradingSystem.HundredMark,
        granularity=speechsdk.PronunciationAssessmentGranularity.Phoneme
    )

    speech_recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)
    pronunciation_config.apply_to(speech_recognizer)

    # 4. Procesar la solicitud
    result = speech_recognizer.recognize_once_async().get()

    if result.reason == speechsdk.ResultReason.RecognizedSpeech:
        pron_result = speechsdk.PronunciationAssessmentResult(result)
        return {
            'status': 'success',
            'score_global': pron_result.pronunciation_score,
            'score_exactitud': pron_result.accuracy_score,
            'score_fluidez': pron_result.fluency_score,
            'texto_reconocido': result.text,
            'palabras': _extraer_desglose_por_palabra(result),
        }
    else:
        return {
            'status': 'error',
            'message': f"Error de reconocimiento. Razón: {result.reason}"
        }


def analizar_imagen_google_vision(imagen_base64):
    """
    Detecta objetos, logotipos y texto presentes en una imagen usando Google
    Cloud Vision (Módulo G).

    Envía la imagen (codificada en base64) a la API REST de Google Cloud
    Vision solicitando, en una sola petición, detección de objetos
    (`OBJECT_LOCALIZATION`, con su cuadro delimitador para poder resaltarlo
    en pantalla), de logotipos (`LOGO_DETECTION`), de texto (`TEXT_DETECTION`)
    y de etiquetas generales de toda la imagen (`LABEL_DETECTION`). Esta
    última sirve de respaldo cuando lo más prominente que `OBJECT_LOCALIZATION`
    encuentra es algo que no es el objeto en sí (ej. un código de barras o
    una etiqueta pegada), ya que analiza la foto completa en vez de un
    recuadro específico.

    Args:
        imagen_base64 (str): contenido de la imagen codificado en base64
            (sin el prefijo `data:image/...;base64,`).

    Returns:
        dict: si la petición falla o faltan credenciales,
            `{'status': 'error', 'message': str}`. Si tiene éxito:
            `{'status': 'success', 'etiquetas': list[dict],
            'etiquetas_generales': list[dict], 'logos': list[dict],
            'texto': dict | None}`, donde:
            - `etiquetas`: objetos localizados, cada uno
              `{'description': str, 'score': float, 'vertices': list[dict]}`
              (en inglés, ordenados por confianza descendente).
            - `etiquetas_generales`: etiquetas de `LABEL_DETECTION` sobre la
              imagen completa, cada una `{'description': str, 'score': float}`
              (sin `vertices`: no hay un recuadro específico).
            - `logos`: logotipos reconocidos, cada uno
              `{'description': str, 'score': float, 'vertices': list[dict]}`.
            - `texto`: `{'contenido': str, 'vertices': list[dict]}` con el
              texto legible completo detectado, o `None` si no se detectó.
            En `etiquetas`/`logos`/`texto`, `vertices` son 4 puntos
            `{'x': float, 'y': float}` normalizados 0-1 respecto al ancho/alto
            real de la imagen (Vision normaliza los de `etiquetas`; los de
            `logos`/`texto` se normalizan aquí mismo con las dimensiones
            reales de la imagen decodificada, para que todas las cajas vivan
            en el mismo sistema de coordenadas y puedan compararse por
            solapamiento). `etiquetas`, `etiquetas_generales` y `logos`
            siempre están presentes (lista vacía si no hay resultados), para
            mantener el contrato retrocompatible.
    """
    api_key = getattr(settings, 'GOOGLE_VISION_KEY', None)
    if not api_key:
        return {'status': 'error', 'message': 'Faltan las credenciales de Google Cloud Vision en el settings.py / .env'}

    try:
        ancho_imagen, alto_imagen = Image.open(io.BytesIO(base64.b64decode(imagen_base64))).size
    except Exception:
        logger.error('No se pudo leer el tamaño de la imagen recibida', exc_info=True)
        return {'status': 'error', 'message': 'La imagen recibida no se pudo procesar.'}

    payload = {
        'requests': [
            {
                'image': {'content': imagen_base64},
                'features': [
                    {'type': 'OBJECT_LOCALIZATION', 'maxResults': MAXIMO_ETIQUETAS_VISION},
                    {'type': 'LABEL_DETECTION', 'maxResults': MAXIMO_ETIQUETAS_VISION},
                    {'type': 'LOGO_DETECTION', 'maxResults': MAXIMO_ETIQUETAS_VISION},
                    {'type': 'TEXT_DETECTION'},
                ],
            }
        ]
    }

    try:
        respuesta = requests.post(
            URL_GOOGLE_VISION,
            params={'key': api_key},
            json=payload,
            timeout=TIMEOUT_GOOGLE_VISION,
        )
    except requests.RequestException:
        logger.error('Error de conexión con Google Cloud Vision', exc_info=True)
        return {'status': 'error', 'message': 'No se pudo conectar con el servicio de reconocimiento de imágenes.'}

    if respuesta.status_code != 200:
        logger.error('Google Cloud Vision respondió con error %s: %s', respuesta.status_code, respuesta.text)
        return {'status': 'error', 'message': 'El servicio de reconocimiento de imágenes no está disponible.'}

    datos_respuesta = respuesta.json()['responses'][0]

    etiquetas = [
        {
            'description': objeto['name'],
            'score': objeto['score'],
            'vertices': objeto['boundingPoly']['normalizedVertices'],
        }
        for objeto in datos_respuesta.get('localizedObjectAnnotations', [])
    ]

    etiquetas_generales = [
        {'description': etiqueta['description'], 'score': etiqueta['score']}
        for etiqueta in datos_respuesta.get('labelAnnotations', [])
    ]

    logos = [
        {
            'description': logo['description'],
            'score': logo.get('score', 0),
            'vertices': _normalizar_vertices(logo['boundingPoly']['vertices'], ancho_imagen, alto_imagen),
        }
        for logo in datos_respuesta.get('logoAnnotations', [])
    ]

    # El primer elemento de `textAnnotations` es siempre el texto completo
    # detectado (los siguientes son palabras individuales); no se usan.
    texto_anotaciones = datos_respuesta.get('textAnnotations', [])
    texto = None
    if texto_anotaciones:
        primera_anotacion = texto_anotaciones[0]
        texto = {
            'contenido': primera_anotacion['description'],
            'vertices': _normalizar_vertices(primera_anotacion['boundingPoly']['vertices'], ancho_imagen, alto_imagen),
        }

    return {
        'status': 'success',
        'etiquetas': etiquetas,
        'etiquetas_generales': etiquetas_generales,
        'logos': logos,
        'texto': texto,
    }


def _normalizar_vertices(vertices_en_pixeles, ancho_imagen, alto_imagen):
    """Convierte vértices en píxeles (`LOGO_DETECTION`/`TEXT_DETECTION`) a fracciones 0-1."""
    return [
        {'x': vertice.get('x', 0) / ancho_imagen, 'y': vertice.get('y', 0) / alto_imagen}
        for vertice in vertices_en_pixeles
    ]


def sintetizar_voz_azure(texto, tipo_voz, velocidad_narracion, volumen_narracion):
    """
    Sintetiza un texto a voz neural usando Azure Speech TTS (Módulo I).

    Construye un documento SSML con la voz, el tono (pitch), la velocidad
    (rate) y el volumen (volume) mapeados a partir de las preferencias de
    `ConfiguracionGlobal` del usuario, y lo envía a Azure Speech para obtener
    el audio sintetizado.

    Args:
        texto (str): texto a narrar. Debe venir ya validado en longitud por
            la vista (esta función no trunca el texto).
        tipo_voz (str): una de las claves de `ConfiguracionGlobal.TIPO_VOZ_CHOICES`
            (`'nino'`, `'nina'`, `'adulto-masculino'`, `'adulto-femenino'`).
        velocidad_narracion (str): una de las claves de
            `ConfiguracionGlobal.VELOCIDAD_NARRACION_CHOICES`
            (`'lenta'`, `'normal'`, `'rapida'`).
        volumen_narracion (int): volumen deseado, de 0 a 100.

    Returns:
        bytes: audio sintetizado en formato MP3 (16kHz, 32kbps, mono).

    Raises:
        ValueError: si faltan las credenciales de Azure Speech en el
            settings, o si Azure no pudo completar la síntesis de audio.
    """
    speech_key = settings.AZURE_SPEECH_KEY
    speech_region = settings.AZURE_SPEECH_REGION

    if not speech_key or not speech_region:
        raise ValueError("Faltan las credenciales de Azure Speech en el settings.py / .env")

    datos_voz = MAPA_VOZ_AZURE.get(tipo_voz, MAPA_VOZ_AZURE['nino'])
    voz_azure = datos_voz['voz']
    pitch = datos_voz['pitch']
    rate = MAPA_VELOCIDAD_AZURE.get(velocidad_narracion, MAPA_VELOCIDAD_AZURE['normal'])
    volume = str(volumen_narracion)

    # El texto se escapa para evitar romper el XML o permitir inyección de
    # tags SSML (condición obligatoria de seguridad del arquitecto).
    texto_escapado = escape(texto)

    ssml = (
        '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="es-MX">'
        f'<voice name="{voz_azure}">'
        f'<prosody pitch="{pitch}" rate="{rate}" volume="{volume}">'
        f'{texto_escapado}'
        '</prosody>'
        '</voice>'
        '</speak>'
    )

    speech_config = speechsdk.SpeechConfig(subscription=speech_key, region=speech_region)
    speech_config.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3
    )

    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
    result = synthesizer.speak_ssml_async(ssml).get()

    if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
        logger.error(
            "No se pudo sintetizar el audio con Azure Speech. Razón: %s", result.reason, exc_info=True
        )
        raise ValueError("No se pudo generar el audio.")

    return result.audio_data