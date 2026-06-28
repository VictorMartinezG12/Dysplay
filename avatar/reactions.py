"""
Catálogo de reacciones textuales del avatar.

Define frases que el avatar puede mostrar/decir ante distintos eventos del
sistema (pronunciación correcta, nivel completado, racha activa, etc.).
Estas frases son independientes del modelo `ReaccionAvatar` (que maneja
emoción + mensaje configurables desde el admin) y se usan para variar el
texto mostrado en pantalla con varias alternativas aleatorias.
"""

import logging
import random

logger = logging.getLogger(__name__)

# Diccionario de reacciones: cada clave es un tipo de evento y su valor es
# una lista de variantes de mensaje que el avatar puede mostrar.
REACCIONES = {
    'pronunciacion_correcta': [
        '¡Excelente pronunciación! ¡Eres increíble!',
        '¡Lo lograste! Esa fue perfecta.',
        '¡5 seguidas! ¡Imparable!',
    ],
    'pronunciacion_incorrecta': [
        '¡Casi! Escucha de nuevo y vuelve a intentar.',
        'Tómate tu tiempo, tú puedes.',
    ],
    'nivel_completado': [
        '¡NIVEL SUPERADO! ¡Eres una estrella!',
        '¡Wow! ¡Sigue así, aventurero!',
    ],
    'racha_activa': [
        '¡Tu racha va por {dias} días! ¡No la rompas!',
    ],
    'insignia_nueva': [
        '¡Conseguiste una insignia nueva! Mírala en tu panel.',
    ],
    'bienvenida_diaria': [
        '¡Hola de nuevo! Te extrañé. ¿Listo para practicar?',
    ],
    'bienvenida_niveles': [
        '¡Bienvenido al mundo de la Aventura! ¿Listo para conquistar el mapa?',
        '¡El mapa te espera! Elige una zona y a practicar.',
        '¡Hora de aventura! ¿Cuántos niveles superarás hoy?',
    ],
    'bienvenida_historias': [
        '¡Bienvenido al mundo de las Historias! ¿Qué cuento leeremos hoy?',
        '¡Las historias te llaman! Vamos a leer juntos.',
        '¡Hora de un cuento! Elige tu historia favorita.',
    ],
    'bienvenida_camara': [
        '¡Bienvenido a la Cámara Inteligente! Apúntame a algo y lo descubrimos.',
        '¡Hora de explorar con la cámara! ¿Qué objeto encontrarás hoy?',
        '¡Di "apunta" y encontraremos algo increíble juntos!',
    ],
    'bienvenida_desafio': [
        '¡Bienvenido al Desafío del día! ¡Tú puedes con esto!',
        '¡El reto de hoy te espera! ¿Estás listo, campeón?',
        '¡Un desafío nuevo cada día! Vamos a intentarlo.',
    ],
    'bienvenida_estadisticas': [
        '¡Mira todo lo que has logrado! ¡Eres increíble!',
        '¡Aquí están tus logros! ¡Sigue así, estrella!',
        '¡Tus estadísticas brillan! ¡Estoy muy orgulloso de ti!',
    ],
    'historia_completada': [
        '¡Historia terminada! ¡Eres todo un lector!',
    ],
    'desafio_completado': [
        '¡Desafío de hoy completado! ¡Vuelve mañana por uno nuevo!',
        '¡Lo lograste todo! El reino te lo agradece.',
    ],
}


def obtener_reaccion(tipo_evento, **kwargs):
    """
    Devuelve una frase aleatoria del avatar para un tipo de evento dado.

    Selecciona al azar una de las variantes de texto definidas en
    `REACCIONES` para `tipo_evento` y, si la frase contiene placeholders
    (por ejemplo `{dias}`), los reemplaza usando los valores recibidos en
    `kwargs`.

    Args:
        tipo_evento (str): clave del evento (debe existir en `REACCIONES`).
        **kwargs: valores para formatear placeholders dentro del mensaje
            (por ejemplo `dias=5` para `racha_activa`).

    Returns:
        str | None: la frase seleccionada (formateada), o `None` si
            `tipo_evento` no existe en `REACCIONES`.
    """
    variantes = REACCIONES.get(tipo_evento)

    if not variantes:
        logger.warning("Tipo de evento de reacción no encontrado: %s", tipo_evento)
        return None

    mensaje = random.choice(variantes)

    try:
        return mensaje.format(**kwargs)
    except (KeyError, IndexError):
        logger.error(
            "Faltan datos para formatear la reacción '%s' con kwargs=%s",
            tipo_evento, kwargs, exc_info=True
        )
        return mensaje
