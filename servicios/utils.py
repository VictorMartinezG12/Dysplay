import json
import logging

import azure.cognitiveservices.speech as speechsdk
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

# Endpoint REST de Google Cloud Vision para detección de etiquetas (Módulo G).
URL_GOOGLE_VISION = 'https://vision.googleapis.com/v1/images:annotate'

# Número máximo de etiquetas a solicitar a Google Vision por imagen.
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
    Detecta los objetos presentes en una imagen usando Google Cloud Vision (Módulo G).

    Envía la imagen (codificada en base64) a la API REST de Google Cloud
    Vision solicitando detección de etiquetas (`LABEL_DETECTION`).

    Args:
        imagen_base64 (str): contenido de la imagen codificado en base64
            (sin el prefijo `data:image/...;base64,`).

    Returns:
        dict: `{'status': 'success', 'etiquetas': list[dict]}` donde cada
            etiqueta es `{'description': str, 'score': float}` (en inglés,
            tal como las devuelve Vision, ordenadas por confianza
            descendente); o `{'status': 'error', 'message': str}` si la
            petición falla o faltan credenciales.
    """
    api_key = getattr(settings, 'GOOGLE_VISION_KEY', None)
    if not api_key:
        return {'status': 'error', 'message': 'Faltan las credenciales de Google Cloud Vision en el settings.py / .env'}

    payload = {
        'requests': [
            {
                'image': {'content': imagen_base64},
                'features': [{'type': 'LABEL_DETECTION', 'maxResults': MAXIMO_ETIQUETAS_VISION}],
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

    etiquetas_crudas = respuesta.json()['responses'][0].get('labelAnnotations', [])
    etiquetas = [
        {'description': etiqueta['description'], 'score': etiqueta['score']}
        for etiqueta in etiquetas_crudas
    ]

    return {'status': 'success', 'etiquetas': etiquetas}