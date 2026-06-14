"""
Capa de servicios del módulo `niveles`.

Contiene la lógica de negocio para el flujo de evaluación de pronunciación:
validación del audio recibido, evaluación contra Azure Speech, persistencia
del progreso del estudiante y cálculo de recompensas (monedas).

Las vistas de `niveles/views.py` deben mantenerse "delgadas" y delegar toda
la lógica de negocio a las funciones definidas aquí.
"""

import logging
import os
import tempfile

import magic

from django.conf import settings

from .models import Nivel, ProgresoEstudiante
from avatar.reactions import obtener_reaccion
from recompensas.services import otorgar_monedas
from servicios.utils import evaluar_pronunciacion

logger = logging.getLogger(__name__)

# Tamaño máximo permitido para los audios de pronunciación (en bytes).
# Si el proyecto define FILE_UPLOAD_MAX_MEMORY_SIZE en settings.py se respeta
# ese valor; de lo contrario se usa un límite razonable de 5 MB, suficiente
# para una grabación corta de una sola palabra/frase en formato WAV.
TAMANO_MAXIMO_AUDIO_BYTES = getattr(settings, 'FILE_UPLOAD_MAX_MEMORY_SIZE', 5 * 1024 * 1024)

# Tipos MIME aceptados como audio WAV válido (varían según el sistema/navegador).
TIPOS_MIME_WAV_VALIDOS = {'audio/x-wav', 'audio/wav', 'audio/vnd.wave'}

# Umbral de puntuación (sobre 100) a partir del cual se considera que el
# estudiante superó la misión de pronunciación. Definido en el Master Plan.
UMBRAL_SUPERACION_NIVEL = 70


def procesar_audio_subido(request_file):
    """
    Valida y persiste temporalmente el archivo de audio enviado por el frontend.

    Realiza dos validaciones de seguridad antes de aceptar el archivo:
    1. Tamaño máximo permitido (TAMANO_MAXIMO_AUDIO_BYTES).
    2. Tipo real del archivo mediante `python-magic` (no se confía en la
       extensión ni en el `content_type` declarado por el navegador), debe
       corresponder a un audio WAV.

    Args:
        request_file: archivo subido (objeto `UploadedFile` de Django),
            normalmente obtenido de `request.FILES.get('audio')`.

    Returns:
        str: ruta absoluta del archivo temporal `.wav` creado en disco.
            El llamador es responsable de eliminar este archivo (por
            ejemplo, con `os.remove`) una vez que termine de usarlo.

    Raises:
        ValueError: si el archivo no se recibió, excede el tamaño máximo
            permitido, o su contenido real no corresponde a un audio WAV.
    """
    if not request_file:
        raise ValueError("No se recibió ningún archivo de audio.")

    if request_file.size > TAMANO_MAXIMO_AUDIO_BYTES:
        raise ValueError(
            f"El archivo de audio excede el tamaño máximo permitido "
            f"({TAMANO_MAXIMO_AUDIO_BYTES} bytes)."
        )

    # Leemos una porción inicial para detectar el tipo real del archivo
    # (la cabecera RIFF/WAVE está dentro de los primeros bytes).
    cabecera = request_file.read(2048)
    request_file.seek(0)

    tipo_mime_detectado = magic.from_buffer(cabecera, mime=True)
    if tipo_mime_detectado not in TIPOS_MIME_WAV_VALIDOS:
        raise ValueError(
            f"El archivo recibido no es un audio WAV válido "
            f"(tipo detectado: {tipo_mime_detectado})."
        )

    # Guardamos el audio temporalmente para que Azure Speech pueda leerlo.
    with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as archivo_temporal:
        for fragmento in request_file.chunks():
            archivo_temporal.write(fragmento)
        ruta_audio_temporal = archivo_temporal.name

    return ruta_audio_temporal


def evaluar_pronunciacion_azure(ruta_audio, texto_referencia):
    """
    Evalúa la pronunciación de un audio contra un texto de referencia usando Azure Speech.

    Es un envoltorio delgado sobre `servicios.utils.evaluar_pronunciacion`,
    de modo que la capa de servicios de `niveles` no dependa directamente
    del SDK de Azure.

    Args:
        ruta_audio (str): ruta absoluta del archivo de audio `.wav` a evaluar.
        texto_referencia (str): palabra u oración objetivo contra la cual se
            evalúa la pronunciación.

    Returns:
        dict: resultado de la evaluación, con las claves `status` y, en caso
            de éxito, `score_global`, `score_exactitud`, `score_fluidez` y
            `texto_reconocido` (o `message` en caso de error).
    """
    return evaluar_pronunciacion(ruta_audio, texto_referencia)


def guardar_progreso_estudiante(usuario, nivel_id, resultado_evaluacion):
    """
    Persiste el avance del estudiante en función del resultado de su evaluación.

    Busca el nivel indicado y el progreso actual del estudiante (creándolo si
    no existe). Si el puntaje global obtenido alcanza el umbral de superación
    definido en el Master Plan (UMBRAL_SUPERACION_NIVEL), se acumulan los
    puntos del nivel y se avanza al siguiente nivel disponible (si existe).

    Args:
        usuario: instancia de `UsuarioCustom` (estudiante autenticado).
        nivel_id: identificador (numero) del `Nivel` que se está evaluando.
        resultado_evaluacion (dict): resultado devuelto por
            `evaluar_pronunciacion_azure`, debe incluir la clave
            `score_global`.

    Returns:
        tuple[ProgresoEstudiante, bool]: el progreso actualizado (o sin
            cambios si no se alcanzó el umbral de superación) y un booleano
            `avanzo_de_nivel` que indica si `nivel_actual` cambió a un nivel
            distinto al evaluado en esta llamada.

    Raises:
        Nivel.DoesNotExist: si no existe un `Nivel` con el `numero` indicado.
    """
    try:
        nivel = Nivel.objects.get(numero=nivel_id)
    except Nivel.DoesNotExist:
        logger.error(
            "Intento de guardar progreso para un nivel inexistente (numero=%s)",
            nivel_id,
            exc_info=True,
        )
        raise

    progreso, _creado = ProgresoEstudiante.objects.get_or_create(usuario=usuario)

    score_global = resultado_evaluacion.get('score_global', 0)
    avanzo_de_nivel = False

    if score_global >= UMBRAL_SUPERACION_NIVEL:
        progreso.puntos_acumulados += nivel.puntos_recompensa

        # Avanzamos al siguiente nivel disponible (si el estudiante estaba
        # justo en este nivel y existe uno con número mayor).
        siguiente_nivel = Nivel.objects.filter(numero__gt=nivel.numero).order_by('numero').first()
        if siguiente_nivel and (progreso.nivel_actual is None or progreso.nivel_actual.numero <= nivel.numero):
            progreso.nivel_actual = siguiente_nivel
            avanzo_de_nivel = True

        progreso.save()

    return progreso, avanzo_de_nivel


def calcular_recompensas(usuario, score, nivel_id=None):
    """
    Calcula y otorga las recompensas (monedas) ganadas por el estudiante en su intento.

    Si el puntaje alcanza el umbral de superación (UMBRAL_SUPERACION_NIVEL),
    se otorgan al usuario las monedas correspondientes a `puntos_recompensa`
    del nivel evaluado (campo `monedas` de `UsuarioCustom`) y se persiste el
    cambio.

    Nota: La actualización de `racha_dias` se deja para el Módulo B (Sistema
    de Recompensas Unificado), que definirá el campo de fecha de última
    actividad necesario para calcularla correctamente. Este módulo NO debe
    modificar `racha_dias`.

    Args:
        usuario: instancia de `UsuarioCustom` (estudiante autenticado).
        score (float): puntaje global obtenido en la evaluación de pronunciación.
        nivel_id: identificador (numero) del `Nivel` recién evaluado. Se usa
            para determinar `puntos_recompensa`. Si no se proporciona o no
            se encuentra, se usa el valor por defecto del modelo `Nivel`.

    Returns:
        dict: con las claves `monedas_ganadas` (int, monedas otorgadas en
            este intento, puede ser 0) y `monedas_totales` (int, saldo
            actualizado de monedas del usuario).
    """
    monedas_ganadas = 0
    monedas_totales = usuario.monedas

    if score >= UMBRAL_SUPERACION_NIVEL:
        puntos_recompensa = Nivel._meta.get_field('puntos_recompensa').get_default()

        if nivel_id is not None:
            try:
                nivel = Nivel.objects.get(numero=nivel_id)
                puntos_recompensa = nivel.puntos_recompensa
            except Nivel.DoesNotExist:
                logger.error(
                    "Nivel inexistente al calcular recompensas (numero=%s)",
                    nivel_id,
                    exc_info=True,
                )

        monedas_ganadas = puntos_recompensa
        # El otorgamiento de monedas se delega en el Módulo B (recompensas),
        # que lo realiza de forma atómica y registra el movimiento en el log.
        monedas_totales = otorgar_monedas(usuario, monedas_ganadas, concepto='nivel_completado')

    return {
        'monedas_ganadas': monedas_ganadas,
        'monedas_totales': monedas_totales,
    }


def construir_reaccion_avatar(score_global, avanzo_de_nivel):
    """
    Construye los datos planos de la reacción del avatar para D.2.

    El avatar (Módulo C) no está disponible en `niveles.html`, por lo que su
    feedback se entrega como un diccionario simple (`tipo` + `mensaje`) para
    que el frontend lo renderice directamente en `#view-result`, sin depender
    de `AVATAR_EVENT`/`AvatarSystem`.

    Args:
        score_global (float): puntaje global obtenido en la evaluación de
            pronunciación.
        avanzo_de_nivel (bool): `True` si el estudiante avanzó de nivel en
            este intento (ver `guardar_progreso_estudiante`).

    Returns:
        dict: `{'tipo': str, 'mensaje': str}`, donde `tipo` es uno de
            `'nivel_completado'`, `'pronunciacion_correcta'` o
            `'pronunciacion_incorrecta'`, y `mensaje` es la frase
            correspondiente obtenida de `avatar.reactions.obtener_reaccion`.
    """
    if avanzo_de_nivel:
        tipo = 'nivel_completado'
    elif score_global >= UMBRAL_SUPERACION_NIVEL:
        tipo = 'pronunciacion_correcta'
    else:
        tipo = 'pronunciacion_incorrecta'

    mensaje = obtener_reaccion(tipo)

    return {'tipo': tipo, 'mensaje': mensaje}


# Nombres y descripciones de las zonas del Mapa de Aventura, en el orden fijo
# definido por el Master Plan (Módulo D).
ZONAS_MAPA_AVENTURA = [
    {
        'clave': Nivel.ZONA_BOSQUE,
        'nombre': 'Bosque Encantado',
        'descripcion': 'Vocales y sonidos básicos',
    },
    {
        'clave': Nivel.ZONA_MONTANA,
        'nombre': 'Montaña de las Letras',
        'descripcion': 'Consonantes y combinaciones',
    },
    {
        'clave': Nivel.ZONA_VALLE,
        'nombre': 'Valle de las Sílabas',
        'descripcion': 'Sílabas y ritmo',
    },
    {
        'clave': Nivel.ZONA_CASTILLO,
        'nombre': 'Castillo de las Palabras',
        'descripcion': 'Palabras completas',
    },
    {
        'clave': Nivel.ZONA_REINO,
        'nombre': 'Reino de la Lectura',
        'descripcion': 'Frases y comprensión',
    },
]


def obtener_mapa_aventura(usuario):
    """
    Construye la estructura de datos del Mapa de Aventura (D.1) para un usuario.

    Agrupa los `Nivel` existentes en BD por `zona`, en el orden fijo de las 5
    zonas del Master Plan (independientemente de si tienen niveles o no: las
    zonas sin niveles quedan con `niveles=[]` y es responsabilidad del
    frontend mostrarlas como "próximamente").

    El estado de cada nivel se calcula comparando su `numero` con el
    `numero` del `nivel_actual` del progreso del estudiante:
    - `numero < nivel_actual.numero` → `'completado'`.
    - `numero == nivel_actual.numero` → `'actual'`.
    - `numero > nivel_actual.numero` → `'bloqueado'`.
    - Si el estudiante no tiene `nivel_actual` asignado, todos los niveles de
      todas las zonas quedan en `'bloqueado'`.

    Una zona se marca como `desbloqueada=True` si contiene al menos un nivel
    en estado `'actual'` o `'completado'`, o si es la primera zona del mapa
    (Bosque Encantado) y el estudiante aún no tiene `nivel_actual` asignado
    (de forma que el mapa siempre muestre al menos la primera zona accesible
    para un estudiante nuevo).

    Args:
        usuario: instancia de `UsuarioCustom` (estudiante autenticado).

    Returns:
        list[dict]: una entrada por cada zona, con las claves `clave`,
            `nombre`, `descripcion`, `desbloqueada` (bool) y `niveles`
            (lista ordenada por `orden_en_zona`, cada elemento con `numero`,
            `titulo`, `orden_en_zona`, `narrativa_intro` y `estado`).
    """
    progreso, _creado = ProgresoEstudiante.objects.get_or_create(usuario=usuario)
    nivel_actual_numero = progreso.nivel_actual.numero if progreso.nivel_actual else None

    niveles_por_zona = {}
    for nivel in Nivel.objects.all().order_by('zona', 'orden_en_zona', 'numero'):
        niveles_por_zona.setdefault(nivel.zona, []).append(nivel)

    zonas = []
    for indice, zona_info in enumerate(ZONAS_MAPA_AVENTURA):
        niveles_zona = []
        for nivel in niveles_por_zona.get(zona_info['clave'], []):
            if nivel_actual_numero is None:
                estado = 'bloqueado'
            elif nivel.numero < nivel_actual_numero:
                estado = 'completado'
            elif nivel.numero == nivel_actual_numero:
                estado = 'actual'
            else:
                estado = 'bloqueado'

            niveles_zona.append({
                'numero': nivel.numero,
                'titulo': nivel.titulo,
                'orden_en_zona': nivel.orden_en_zona,
                'narrativa_intro': nivel.narrativa_intro,
                'estado': estado,
            })

        desbloqueada = any(n['estado'] in ('actual', 'completado') for n in niveles_zona)
        if indice == 0 and nivel_actual_numero is None:
            desbloqueada = True

        zonas.append({
            'clave': zona_info['clave'],
            'nombre': zona_info['nombre'],
            'descripcion': zona_info['descripcion'],
            'desbloqueada': desbloqueada,
            'niveles': niveles_zona,
        })

    return zonas


def procesar_intento_nivel(usuario, archivo_audio, palabra_objetivo, nivel_id):
    """
    Orquesta el flujo completo de un intento de pronunciación (D.2).

    Valida y procesa el audio recibido, lo evalúa contra Azure Speech,
    persiste el progreso del estudiante, calcula las recompensas obtenidas y
    construye la reacción del avatar correspondiente. El archivo temporal de
    audio se elimina siempre, sin importar el resultado.

    Args:
        usuario: instancia de `UsuarioCustom` (estudiante autenticado).
        archivo_audio: archivo de audio subido (`request.FILES.get('audio')`).
        palabra_objetivo (str): palabra/frase de referencia para la evaluación.
        nivel_id: identificador (numero) del `Nivel` que se está evaluando.

    Returns:
        dict: si la evaluación de Azure falla, `{'status': 'error',
            'message': str}`. Si todo sale bien, un diccionario con
            `status='success'` y las claves `score`, `score_exactitud`,
            `palabras`, `avanzo_de_nivel`, `monedas_ganadas`,
            `monedas_totales` y `reaccion_avatar` (`{'tipo', 'mensaje'}`).

    Raises:
        Exception: cualquier error inesperado se loguea con
            `logging.error(..., exc_info=True)` y se relanza; la vista que
            invoca esta función es responsable de convertirlo en una
            respuesta HTTP genérica.
    """
    ruta_audio_temporal = None
    try:
        ruta_audio_temporal = procesar_audio_subido(archivo_audio)
        resultado_azure = evaluar_pronunciacion_azure(ruta_audio_temporal, palabra_objetivo)

        if resultado_azure['status'] != 'success':
            return {'status': 'error', 'message': resultado_azure['message']}

        progreso, avanzo_de_nivel = guardar_progreso_estudiante(usuario, nivel_id, resultado_azure)
        recompensas = calcular_recompensas(usuario, resultado_azure['score_global'], nivel_id)
        reaccion_avatar = construir_reaccion_avatar(resultado_azure['score_global'], avanzo_de_nivel)

        return {
            'status': 'success',
            'score': resultado_azure['score_global'],
            'score_exactitud': resultado_azure.get('score_exactitud'),
            'palabras': resultado_azure.get('palabras', []),
            'avanzo_de_nivel': avanzo_de_nivel,
            'monedas_ganadas': recompensas['monedas_ganadas'],
            'monedas_totales': recompensas['monedas_totales'],
            'reaccion_avatar': reaccion_avatar,
        }
    except Exception:
        logger.error("Error inesperado al procesar el intento de nivel", exc_info=True)
        raise
    finally:
        if ruta_audio_temporal and os.path.exists(ruta_audio_temporal):
            os.remove(ruta_audio_temporal)
