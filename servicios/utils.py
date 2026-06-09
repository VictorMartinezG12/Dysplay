import azure.cognitiveservices.speech as speechsdk
from django.conf import settings


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
            'texto_reconocido': result.text
        }
    else:
        return {
            'status': 'error',
            'message': f"Error de reconocimiento. Razón: {result.reason}"
        }