"""
Script de experimento (NO forma parte de la app): compara, sobre el mismo
lote de fotos en `experimento_gemini/fotos/`, el pipeline actual del módulo
de Cámara Inteligente (Google Vision + Azure OpenAI, dos llamadas LLM) contra
una alternativa de un solo envío a Gemini (imagen + prompt -> objeto y frase).

Mide tiempo y compara los resultados para decidir si vale migrar el pipeline
real. No modifica nada de `camara_inteligente/`; solo importa sus funciones
para reutilizar exactamente la misma lógica de traducción/generación de frase
que usa la app hoy.

Uso:
    ./env/bin/python experimento_gemini/comparar_pipelines.py
"""

import base64
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from google import genai  # noqa: E402
from google.genai import types  # noqa: E402

from camara_inteligente.services import (  # noqa: E402
    _detectar_objeto_y_calificador,
    _generar_frase_llm,
    _traducir_objeto_llm,
)
from servicios.utils import analizar_imagen_google_vision  # noqa: E402

CARPETA_FOTOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fotos')
RUTA_RESULTADOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resultados.json')

# Nivel de dificultad fijo para que ambos pipelines generen frases comparables
# (en la app real depende del progreso del estudiante; aquí no hay estudiante).
NIVEL_DIFICULTAD_PRUEBA = 2

MODELO_GEMINI = 'gemini-2.5-flash'

PROMPT_GEMINI = (
    'Eres parte de una app educativa para niños con dislexia. Mira la imagen y '
    'responde SOLO con un JSON (sin markdown, sin explicación) con esta forma '
    'exacta: {{"objeto": "<nombre del objeto principal en español>", '
    '"frase": "<frase corta y natural en español, máximo 10 palabras, para que '
    'el niño la lea en voz alta y practique pronunciación, dificultad nivel {nivel} '
    'de 5 (1=muy simple, 5=elaborada), contenido siempre positivo y apropiado>"}}'
).format(nivel=NIVEL_DIFICULTAD_PRUEBA)


def _ejecutar_pipeline_actual(imagen_base64):
    """Corre Vision -> traducción LLM -> frase LLM, igual que `procesar_captura_imagen` hoy."""
    inicio_total = time.monotonic()

    inicio_vision = time.monotonic()
    resultado_vision = analizar_imagen_google_vision(imagen_base64)
    duracion_vision = time.monotonic() - inicio_vision

    if resultado_vision['status'] != 'success':
        return {
            'ok': False,
            'error': resultado_vision['message'],
            'duracion_total_segundos': time.monotonic() - inicio_total,
        }

    deteccion = _detectar_objeto_y_calificador(resultado_vision)
    if deteccion is None:
        return {
            'ok': False,
            'error': 'No se localizó ningún objeto.',
            'duracion_total_segundos': time.monotonic() - inicio_total,
        }

    inicio_llm = time.monotonic()
    objeto_es = _traducir_objeto_llm(deteccion['etiqueta_en'], deteccion['calificador']) or deteccion['etiqueta_en']
    frase = _generar_frase_llm(objeto_es, NIVEL_DIFICULTAD_PRUEBA)
    duracion_llm = time.monotonic() - inicio_llm

    return {
        'ok': True,
        'objeto': objeto_es,
        'frase': frase or '(el LLM falló, caería a FraseTemplate/FRASE_GENERICA)',
        'duracion_vision_segundos': round(duracion_vision, 2),
        'duracion_llm_segundos': round(duracion_llm, 2),
        'duracion_total_segundos': round(time.monotonic() - inicio_total, 2),
    }


def _ejecutar_pipeline_gemini(cliente_gemini, imagen_bytes, mime_type):
    """Corre una sola llamada a Gemini con la imagen, pidiendo objeto+frase en JSON."""
    inicio_total = time.monotonic()
    try:
        respuesta = cliente_gemini.models.generate_content(
            model=MODELO_GEMINI,
            contents=[
                PROMPT_GEMINI,
                types.Part.from_bytes(data=imagen_bytes, mime_type=mime_type),
            ],
        )
        texto = respuesta.text.strip()
        if texto.startswith('```'):
            texto = texto.strip('`').removeprefix('json').strip()
        datos = json.loads(texto)
        return {
            'ok': True,
            'objeto': datos.get('objeto'),
            'frase': datos.get('frase'),
            'duracion_total_segundos': round(time.monotonic() - inicio_total, 2),
        }
    except Exception as error:
        return {
            'ok': False,
            'error': str(error),
            'duracion_total_segundos': round(time.monotonic() - inicio_total, 2),
        }


def main():
    if not getattr(settings, 'GOOGLE_VISION_KEY', None):
        sys.exit('Falta GOOGLE_VISION_KEY en el .env — repórtalo antes de correr el experimento.')
    if not getattr(settings, 'GEMINI_API_KEY', None):
        sys.exit('Falta GEMINI_API_KEY en el .env — repórtalo antes de correr el experimento.')

    rutas_fotos = sorted(
        os.path.join(CARPETA_FOTOS, nombre)
        for nombre in os.listdir(CARPETA_FOTOS)
        if nombre.lower().endswith(('.jpg', '.jpeg', '.png'))
    )
    if not rutas_fotos:
        sys.exit(f'No hay fotos en {CARPETA_FOTOS}.')

    cliente_gemini = genai.Client(api_key=settings.GEMINI_API_KEY)

    resultados = []
    for ruta_foto in rutas_fotos:
        nombre_foto = os.path.basename(ruta_foto)
        print(f'\n=== {nombre_foto} ===')

        with open(ruta_foto, 'rb') as archivo:
            imagen_bytes = archivo.read()
        imagen_base64 = base64.b64encode(imagen_bytes).decode('ascii')
        mime_type = 'image/png' if ruta_foto.lower().endswith('.png') else 'image/jpeg'

        resultado_actual = _ejecutar_pipeline_actual(imagen_base64)
        print(f'  Pipeline actual (Vision+Azure): {resultado_actual}')

        resultado_gemini = _ejecutar_pipeline_gemini(cliente_gemini, imagen_bytes, mime_type)
        print(f'  Pipeline Gemini (1 llamada):    {resultado_gemini}')

        resultados.append({
            'foto': nombre_foto,
            'pipeline_actual': resultado_actual,
            'pipeline_gemini': resultado_gemini,
        })

    with open(RUTA_RESULTADOS, 'w', encoding='utf-8') as archivo_resultados:
        json.dump(resultados, archivo_resultados, ensure_ascii=False, indent=2)

    print(f'\nResultados completos guardados en {RUTA_RESULTADOS}')


if __name__ == '__main__':
    main()
