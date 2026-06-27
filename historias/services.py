"""
Capa de servicios del módulo `historias` (Módulo F del Master Plan).

Contiene la lógica de negocio del flujo de Historias Interactivas: listado de
historias con su estado de desbloqueo, lectura/avance de fragmentos
(incluyendo ramificación vía `OpcionRespuesta.fragmento_siguiente`),
evaluación de la respuesta del estudiante (voz, texto u opción) y
otorgamiento de recompensas (monedas + insignia) al completar una historia.
"""

import datetime
import json
import logging
import os
import re
import unicodedata

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from openai import AzureOpenAI

from google import genai
from google.genai import types

from avatar.reactions import obtener_reaccion
from estadisticas.models import RegistroActividad
from niveles.services import (
    UMBRAL_SUPERACION_NIVEL,
    evaluar_pronunciacion_azure,
    procesar_audio_subido,
)
from recompensas.services import otorgar_monedas, verificar_y_otorgar_insignias

from .models import (
    FragmentoGenerado,
    FragmentoHistoria,
    Historia,
    HistoriaGenerada,
    OpcionGenerada,
    OpcionRespuesta,
    ProgresoHistoria,
)

logger = logging.getLogger(__name__)

# Número de estrellas a mostrar en el carrusel según la dificultad (F.2/UX).
ESTRELLAS_POR_DIFICULTAD = {
    'facil': 3,
    'medio': 5,
    'dificil': 8,
}

# Versión de la API de Azure OpenAI usada por el generador de historias
# completas (mismo valor estable que el resto del proyecto, ver
# `camara_inteligente/services.py`).
AZURE_OPENAI_API_VERSION = '2024-10-21'

# Tiempo de espera máximo (segundos) para la llamada a Azure OpenAI al generar
# una historia completa. Es una operación administrativa (no bloquea el flujo
# del estudiante), por lo que se permite un margen mayor que en otros usos.
AZURE_OPENAI_TIMEOUT_SEGUNDOS = 30

# Duración estimada (minutos) asignada por defecto a una historia generada
# por IA, en función de la cantidad de fragmentos solicitada.
DURACION_MINUTOS_POR_FRAGMENTO = 2

# Recompensa en monedas otorgada por defecto a una historia generada por IA.
RECOMPENSA_MONEDAS_HISTORIA_IA = 15

# Mapeo de un nivel de dificultad numérico (1-5, usado por el formulario del
# admin) al choice real de `Historia.nivel_dificultad`.
NIVEL_DIFICULTAD_NUMERICO_A_CHOICE = {
    1: 'facil',
    2: 'facil',
    3: 'medio',
    4: 'medio',
    5: 'dificil',
}

TIPOS_RESPUESTA_VALIDOS = {'', 'elegir', 'escribir', 'pronunciar', 'comprender'}

# Longitud máxima permitida para las palabras clave que el niño escribe al
# pedir una historia generada por IA (debe coincidir con
# `HistoriaGenerada.palabras_clave`, `CharField(max_length=60)`).
LONGITUD_MAXIMA_PALABRAS_CLAVE = 60

# Allowlist estricta para las palabras clave del niño: letras (incluye
# tildes y ñ), espacios y comas. Cualquier otro carácter (backticks, llaves,
# símbolos de control, etc.) se rechaza para prevenir inyección de
# instrucciones hacia el LLM.
PATRON_PALABRAS_CLAVE_VALIDAS = re.compile(r'^[A-Za-zÁÉÍÓÚáéíóúÑñÜü ,]+$')

# Límite de `HistoriaGenerada` que un mismo usuario puede crear en una
# ventana de 24 horas (cuenta intentos reales, incluyendo historias ya
# expiradas, porque cada llamada exitosa a la IA tiene un costo real).
LIMITE_HISTORIAS_GENERADAS_POR_USUARIO_24H = 5

# Tope global de `HistoriaGenerada` creadas por todos los usuarios juntos en
# una ventana de 24 horas, para acotar el costo total de la API de IA.
TOPE_GLOBAL_HISTORIAS_GENERADAS_24H = 200

# Nivel de dificultad numérico fijo (1 a 5) usado para generar historias
# efímeras vía IA. Se simplifica con un valor medio fijo en lugar de leer
# `ProgresoEstudiante.nivel_actual` (que es un FK a `Nivel`, no un entero
# 1-5 directo) para no acoplar este flujo a la estructura interna del
# módulo `niveles`. Decisión documentada: ver Master Plan Módulo F.
NIVEL_DIFICULTAD_HISTORIA_GENERADA = 3

# Cantidad de fragmentos solicitados a la IA para una historia generada por
# el niño (más corta que las historias curadas, pensada para una sesión).
CANTIDAD_FRAGMENTOS_HISTORIA_GENERADA = 4


def normalizar_texto(texto):
    """
    Normaliza un texto para comparaciones tolerantes a mayúsculas y tildes.

    Convierte a minúsculas, recorta espacios y elimina los signos
    diacríticos (tildes, diéresis), de modo que "Dragón" y "dragon " se
    consideren equivalentes al evaluar respuestas escritas.

    Args:
        texto (str): texto a normalizar.

    Returns:
        str: texto normalizado.
    """
    texto = texto.strip().lower()
    texto_sin_tildes = unicodedata.normalize('NFKD', texto)
    return ''.join(c for c in texto_sin_tildes if not unicodedata.combining(c))


def obtener_historias_completadas(usuario):
    """
    Cuenta cuántas historias ha completado un usuario.

    Usado por `recompensas.services.verificar_y_otorgar_insignias` para
    evaluar el criterio de insignia `historias_10`.

    Args:
        usuario: instancia de `UsuarioCustom` (estudiante autenticado).

    Returns:
        int: cantidad de `ProgresoHistoria` con `completada=True`.
    """
    return ProgresoHistoria.objects.filter(usuario=usuario, completada=True).count()


def obtener_historias_disponibles(usuario):
    """
    Construye el carrusel de historias (F.2) con su estado para el usuario.

    El desbloqueo es secuencial según `Historia.orden`: la primera historia
    siempre está disponible; cada historia siguiente se desbloquea cuando el
    usuario completó la anterior.

    Args:
        usuario: instancia de `UsuarioCustom` (estudiante autenticado).

    Returns:
        list[dict]: una entrada por cada `Historia` activa, con las claves
            `id`, `titulo`, `descripcion_corta`, `portada_url`,
            `nivel_dificultad`, `nivel_dificultad_display`,
            `duracion_estimada_minutos`, `rango_estrellas` (lista para
            iterar en el template) y `estado`
            (`'completada'`, `'disponible'` o `'bloqueada'`).
    """
    historias = list(Historia.objects.filter(activa=True).order_by('orden', 'id'))

    ids_completadas = set(
        ProgresoHistoria.objects.filter(usuario=usuario, completada=True).values_list('historia_id', flat=True)
    )

    resultado = []
    anterior_completada = True
    for historia in historias:
        if historia.id in ids_completadas:
            estado = 'completada'
        elif anterior_completada:
            estado = 'disponible'
        else:
            estado = 'bloqueada'

        resultado.append({
            'id': historia.id,
            'titulo': historia.titulo,
            'descripcion_corta': historia.descripcion_corta,
            'portada_url': historia.portada.url if historia.portada else None,
            'nivel_dificultad': historia.nivel_dificultad,
            'nivel_dificultad_display': historia.get_nivel_dificultad_display(),
            'duracion_estimada_minutos': historia.duracion_estimada_minutos,
            'rango_estrellas': range(ESTRELLAS_POR_DIFICULTAD.get(historia.nivel_dificultad, 3)),
            'estado': estado,
        })

        anterior_completada = historia.id in ids_completadas

    return resultado


def obtener_o_crear_progreso(usuario, historia):
    """
    Obtiene el `ProgresoHistoria` de `usuario` para `historia`, creándolo si no existe.

    Si el progreso se crea ahora o no tiene `fragmento_actual` asignado, se
    posiciona en el primer fragmento (menor `orden`) de la historia.

    Args:
        usuario: instancia de `UsuarioCustom` (estudiante autenticado).
        historia (Historia): historia sobre la que se consulta el progreso.

    Returns:
        ProgresoHistoria: progreso del usuario sobre la historia indicada.
    """
    progreso, _creado = ProgresoHistoria.objects.get_or_create(usuario=usuario, historia=historia)

    necesita_reset = progreso.completada or progreso.fragmento_actual is None
    if necesita_reset:
        primer_fragmento = historia.fragmentos.order_by('orden').first()
        if primer_fragmento:
            progreso.fragmento_actual = primer_fragmento
            progreso.save()

    return progreso


def _serializar_opcion(opcion):
    """Convierte una `OpcionRespuesta` en un diccionario apto para JSON (sin revelar `es_correcta`)."""
    return {
        'id': opcion.id,
        'texto': opcion.texto,
    }


def _serializar_fragmento(fragmento):
    """Convierte un `FragmentoHistoria` en un diccionario apto para JSON."""
    return {
        'id': fragmento.id,
        'orden': fragmento.orden,
        'texto_narracion': fragmento.texto_narracion,
        'imagen_url': fragmento.imagen.url if getattr(fragmento, 'imagen', None) and fragmento.imagen else None,
        'audio_narracion_url': fragmento.audio_narracion.url if fragmento.audio_narracion else None,
        'pregunta_interactiva': fragmento.pregunta_interactiva,
        'tipo_respuesta': fragmento.tipo_respuesta,
        'opciones': [
            _serializar_opcion(opcion)
            for opcion in fragmento.opciones.all()
        ] if fragmento.tipo_respuesta == 'elegir' else [],
    }


def construir_estado_lectura(usuario, historia):
    """
    Construye todo el estado necesario para renderizar la lectura de una historia (F.2).

    Args:
        usuario: instancia de `UsuarioCustom` (estudiante autenticado).
        historia (Historia): historia que el usuario está leyendo.

    Returns:
        dict: con las claves `historia` (datos básicos), `fragmentos` (lista
            serializada en orden), `fragmento_actual_id` y `completada`.
    """
    progreso = obtener_o_crear_progreso(usuario, historia)
    fragmentos = historia.fragmentos.prefetch_related('opciones').order_by('orden')

    return {
        'historia': {
            'id': historia.id,
            'titulo': historia.titulo,
            'recompensa_monedas': historia.recompensa_monedas,
        },
        'fragmentos': [_serializar_fragmento(fragmento) for fragmento in fragmentos],
        'fragmento_actual_id': progreso.fragmento_actual_id,
        'completada': progreso.completada,
    }


def _siguiente_fragmento_por_orden(fragmento):
    """
    Devuelve el fragmento con `orden` inmediatamente mayor dentro de la misma
    historia, o `None`.

    Función genérica: funciona tanto con `FragmentoHistoria` (atributo
    `historia_id`) como con `FragmentoGenerado` (atributo
    `historia_generada_id`), ya que ambos exponen un manager `objects` en su
    propia clase (`type(fragmento).objects`) y comparten el nombre del campo
    `orden`.

    Args:
        fragmento: instancia de `FragmentoHistoria` o `FragmentoGenerado`.

    Returns:
        El siguiente fragmento del mismo tipo, o `None` si no hay más.
    """
    if hasattr(fragmento, 'historia_id'):
        filtro = {'historia_id': fragmento.historia_id}
    else:
        filtro = {'historia_generada_id': fragmento.historia_generada_id}

    return type(fragmento).objects.filter(
        orden__gt=fragmento.orden, **filtro,
    ).order_by('orden').first()


def _fragmento_siguiente_por_ramificacion(opcion):
    """
    Devuelve el fragmento de ramificación de `opcion`, si el modelo lo soporta.

    `OpcionRespuesta` permite ramificación vía `fragmento_siguiente`, pero
    `OpcionGenerada` (historias generadas por IA, lineales) no tiene ese
    campo. Esta función aísla ese acceso para que sea seguro llamarla con
    cualquiera de los dos tipos de opción.

    Args:
        opcion: instancia de `OpcionRespuesta` u `OpcionGenerada`.

    Returns:
        El fragmento de ramificación, o `None` si no existe o el modelo no
        soporta ramificación.
    """
    return getattr(opcion, 'fragmento_siguiente', None)


def _evaluar_elegir(fragmento, opcion_id):
    """Evalúa una respuesta de tipo 'elegir'. Devuelve `(correcta, siguiente_fragmento, mensaje_error)`."""
    try:
        opcion = fragmento.opciones.get(pk=opcion_id)
    except (OpcionRespuesta.DoesNotExist, OpcionGenerada.DoesNotExist):
        return None, None, 'La opción seleccionada no es válida.'

    siguiente = _fragmento_siguiente_por_ramificacion(opcion) or _siguiente_fragmento_por_orden(fragmento)
    return opcion.es_correcta, siguiente, None


def _evaluar_escribir(fragmento, texto_respuesta):
    """Evalúa una respuesta de tipo 'escribir' mediante comparación normalizada. Devuelve `(correcta, siguiente_fragmento, mensaje_error)`."""
    if not texto_respuesta or not texto_respuesta.strip():
        return None, None, 'Escribe una respuesta antes de continuar.'

    respuesta_normalizada = normalizar_texto(texto_respuesta)

    for opcion in fragmento.opciones.all():
        opcion_normalizada = normalizar_texto(opcion.texto)
        if opcion_normalizada and (
            respuesta_normalizada == opcion_normalizada
            or opcion_normalizada in respuesta_normalizada
        ):
            siguiente = _fragmento_siguiente_por_ramificacion(opcion) or _siguiente_fragmento_por_orden(fragmento)
            return opcion.es_correcta, siguiente, None

    return False, _siguiente_fragmento_por_orden(fragmento), None


def _evaluar_pronunciar(usuario, fragmento, archivo_audio):
    """Evalúa una respuesta de tipo 'pronunciar' contra Azure Speech. Devuelve `(correcta, siguiente_fragmento, mensaje_error)`."""
    opcion = fragmento.opciones.filter(es_correcta=True).first()
    if not opcion:
        return None, None, 'Este fragmento no tiene una palabra de referencia configurada.'

    ruta_audio_temporal = None
    try:
        ruta_audio_temporal = procesar_audio_subido(archivo_audio)
        resultado_azure = evaluar_pronunciacion_azure(ruta_audio_temporal, opcion.texto)
    except ValueError as error:
        return None, None, str(error)
    finally:
        if ruta_audio_temporal and os.path.exists(ruta_audio_temporal):
            os.remove(ruta_audio_temporal)

    if resultado_azure['status'] != 'success':
        return None, None, resultado_azure['message']

    RegistroActividad.objects.registrar(usuario, RegistroActividad.TIPO_HISTORIA, resultado_azure['score_global'])

    correcta = resultado_azure['score_global'] >= UMBRAL_SUPERACION_NIVEL
    siguiente = _fragmento_siguiente_por_ramificacion(opcion) or _siguiente_fragmento_por_orden(fragmento)
    return correcta, siguiente, None


def _evaluar_comprender(usuario, historia, fragmento, archivo_audio):
    """
    Evalúa la comprensión libre del estudiante: transcribe su audio con Gemini
    y puntúa qué tan bien explicó los puntos clave de la historia.

    Args:
        usuario: instancia de `UsuarioCustom`.
        historia (Historia): historia que acaba de leer el estudiante.
        fragmento (FragmentoHistoria): fragmento actual (último de la historia).
        archivo_audio: archivo WAV subido desde el navegador.

    Returns:
        tuple: `(correcta, siguiente_fragmento, mensaje_error, mensaje_feedback)`.
            `correcta` es `True` si el score ≥ UMBRAL_SUPERACION_NIVEL (70).
            `mensaje_feedback` es la frase de aliento devuelta por Gemini.
    """
    if not archivo_audio:
        return None, _siguiente_fragmento_por_orden(fragmento), 'Graba tu respuesta antes de continuar.', None

    ruta_audio = None
    try:
        ruta_audio = procesar_audio_subido(archivo_audio)
        with open(ruta_audio, 'rb') as f:
            audio_bytes = f.read()

        resumen = ' '.join(
            fr.texto_narracion for fr in historia.fragmentos.order_by('orden')
        )[:700]

        prompt = (
            f'Eres un evaluador educativo para niños con dislexia de primaria.\n'
            f'Historia: "{historia.titulo}"\n'
            f'Texto de la historia: {resumen}\n\n'
            f'El niño acaba de escuchar esta historia y grabó un audio '
            f'explicando con sus propias palabras lo que entendió.\n'
            f'Analiza el audio y devuelve SOLO este JSON sin texto extra:\n'
            f'{{"score": <número 0-100>, "mensaje": "<frase de aliento en español, máximo 15 palabras>"}}\n'
            f'Score 70 o más significa que el niño comprendió los puntos esenciales.'
        )

        cliente = genai.Client(
            api_key=settings.GEMINI_API_KEY,
            http_options=types.HttpOptions(timeout=25000),
        )
        respuesta = cliente.models.generate_content(
            model='gemini-2.5-flash-preview-05-14',
            contents=[prompt, types.Part.from_bytes(data=audio_bytes, mime_type='audio/wav')],
        )

        texto = (respuesta.text or '').strip()
        if texto.startswith('```'):
            texto = texto.strip('`')
            if texto.lower().startswith('json'):
                texto = texto[4:]
            texto = texto.strip()

        datos = json.loads(texto)
        score = max(0, min(100, int(datos.get('score', 0))))
        mensaje = str(datos.get('mensaje', '¡Buen intento, sigue adelante!'))[:120]

        correcta = score >= UMBRAL_SUPERACION_NIVEL
        siguiente = _siguiente_fragmento_por_orden(fragmento)
        return correcta, siguiente, None, mensaje

    except Exception:
        logger.error('Error al evaluar comprensión libre con Gemini', exc_info=True)
        return False, _siguiente_fragmento_por_orden(fragmento), None, '¡Buen intento, sigue adelante!'
    finally:
        if ruta_audio and os.path.exists(ruta_audio):
            os.remove(ruta_audio)


def _construir_reaccion_avatar(completada_ahora, correcta):
    """Construye los datos planos `{tipo, mensaje}` de la reacción del avatar para un intento."""
    if completada_ahora:
        tipo = 'historia_completada'
    elif correcta is True:
        tipo = 'pronunciacion_correcta'
    elif correcta is False:
        tipo = 'pronunciacion_incorrecta'
    else:
        return None

    return {'tipo': tipo, 'mensaje': obtener_reaccion(tipo)}


def procesar_respuesta_fragmento(usuario, historia, fragmento_id, opcion_id=None, texto_respuesta=None, archivo_audio=None):
    """
    Orquesta la evaluación de la respuesta del estudiante a un fragmento (F.2).

    Según `fragmento.tipo_respuesta`, evalúa la respuesta (opción elegida,
    texto escrito o audio pronunciado), determina el siguiente fragmento
    (respetando la ramificación de `OpcionRespuesta.fragmento_siguiente` si
    existe) y actualiza el `ProgresoHistoria`. Si no hay siguiente fragmento,
    marca la historia como completada y otorga las recompensas
    correspondientes (monedas + evaluación de insignias).

    Args:
        usuario: instancia de `UsuarioCustom` (estudiante autenticado).
        historia (Historia): historia a la que pertenece el fragmento.
        fragmento_id: identificador (`pk`) del `FragmentoHistoria` respondido.
        opcion_id: identificador de la `OpcionRespuesta` elegida (tipo 'elegir').
        texto_respuesta (str, optional): texto escrito por el estudiante (tipo 'escribir').
        archivo_audio: archivo de audio subido (tipo 'pronunciar').

    Returns:
        dict: `{'status': 'error', 'message': str}` si la validación falla,
            o `{'status': 'success', 'correcta': bool|None,
            'siguiente_fragmento': dict|None, 'completada': bool,
            'completada_ahora': bool, 'reaccion_avatar': dict|None,
            'monedas_ganadas': int, 'monedas_totales': int|None,
            'insignia_nueva': bool}`.

    Raises:
        Exception: cualquier error inesperado se loguea con
            `logging.error(..., exc_info=True)` y se relanza; la vista que
            invoca esta función es responsable de convertirlo en una
            respuesta HTTP genérica.
    """
    try:
        try:
            fragmento = historia.fragmentos.get(pk=fragmento_id)
        except FragmentoHistoria.DoesNotExist:
            return {'status': 'error', 'message': 'El fragmento solicitado no existe.'}

        progreso = obtener_o_crear_progreso(usuario, historia)
        ya_completada_antes = progreso.completada

        if progreso.fragmento_actual_id != fragmento.id:
            return {'status': 'error', 'message': 'Este fragmento no corresponde a tu progreso actual.'}

        correcta = None
        mensaje_comprension = None
        if fragmento.tipo_respuesta == 'elegir':
            correcta, siguiente, mensaje_error = _evaluar_elegir(fragmento, opcion_id)
        elif fragmento.tipo_respuesta == 'escribir':
            correcta, siguiente, mensaje_error = _evaluar_escribir(fragmento, texto_respuesta)
        elif fragmento.tipo_respuesta == 'pronunciar':
            correcta, siguiente, mensaje_error = _evaluar_pronunciar(usuario, fragmento, archivo_audio)
        elif fragmento.tipo_respuesta == 'comprender':
            correcta, siguiente, mensaje_error, mensaje_comprension = _evaluar_comprender(
                usuario, historia, fragmento, archivo_audio,
            )
        else:
            siguiente, mensaje_error = _siguiente_fragmento_por_orden(fragmento), None

        if mensaje_error:
            return {'status': 'error', 'message': mensaje_error}

        monedas_ganadas = 0
        monedas_totales = None
        insignia_nueva = False
        completada_ahora = False

        if siguiente is None:
            progreso.completada = True
            progreso.fecha_fin = timezone.now()
            progreso.save()

            if not ya_completada_antes:
                monedas_totales = otorgar_monedas(usuario, historia.recompensa_monedas, concepto='historia_completada')
                monedas_ganadas = historia.recompensa_monedas
                insignias_nuevas = verificar_y_otorgar_insignias(usuario)
                insignia_nueva = bool(insignias_nuevas)

            completada_ahora = True
        else:
            progreso.fragmento_actual = siguiente
            progreso.save()

        return {
            'status': 'success',
            'correcta': correcta,
            'siguiente_fragmento': _serializar_fragmento(siguiente) if siguiente else None,
            'completada': progreso.completada,
            'completada_ahora': completada_ahora,
            'es_repeticion': ya_completada_antes,
            'reaccion_avatar': _construir_reaccion_avatar(completada_ahora, correcta),
            'monedas_ganadas': monedas_ganadas,
            'monedas_totales': monedas_totales,
            'insignia_nueva': insignia_nueva,
            'mensaje_comprension': mensaje_comprension,
        }
    except Exception:
        logger.error('Error inesperado al procesar la respuesta de un fragmento de historia', exc_info=True)
        raise


def _validar_estructura_historia_generada(datos):
    """
    Valida que `datos` (ya parseado de JSON) tenga la estructura mínima
    esperada para crear una `Historia` completa.

    Args:
        datos (dict): estructura devuelta por el LLM tras `json.loads`.

    Raises:
        ValueError: si falta alguna clave obligatoria, los fragmentos están
            vacíos, o algún fragmento/opción tiene un tipo de dato inesperado.
    """
    if not isinstance(datos, dict):
        raise ValueError('La respuesta del LLM no es un objeto JSON.')

    titulo = datos.get('titulo')
    fragmentos = datos.get('fragmentos')

    if not titulo or not isinstance(titulo, str):
        raise ValueError('La respuesta del LLM no incluye un título válido.')

    if not fragmentos or not isinstance(fragmentos, list):
        raise ValueError('La respuesta del LLM no incluye fragmentos válidos.')

    for fragmento in fragmentos:
        if not isinstance(fragmento, dict):
            raise ValueError('Un fragmento de la respuesta del LLM no es un objeto válido.')

        if not fragmento.get('texto_narracion') or not isinstance(fragmento['texto_narracion'], str):
            raise ValueError('Un fragmento de la respuesta del LLM no tiene texto de narración.')

        tipo_respuesta = fragmento.get('tipo_respuesta', '')
        if tipo_respuesta not in TIPOS_RESPUESTA_VALIDOS:
            raise ValueError(f'Tipo de respuesta inesperado en la respuesta del LLM: {tipo_respuesta!r}.')

        opciones = fragmento.get('opciones', [])
        if opciones and not isinstance(opciones, list):
            raise ValueError('Las opciones de un fragmento de la respuesta del LLM no son una lista válida.')

        if tipo_respuesta == 'elegir' and not opciones:
            raise ValueError('Un fragmento de tipo "elegir" no tiene opciones en la respuesta del LLM.')


def generar_historia_completa_ia(tema, nivel_dificultad, cantidad_fragmentos=4):
    """
    Genera, vía Azure OpenAI, una historia infantil completa y lista para
    persistir como `Historia` curada (no efímera).

    Construye un prompt con una instrucción de sistema fija (idioma,
    formato JSON estricto, dificultad de vocabulario apropiada para niños
    con dislexia) y un mensaje de usuario con el `tema` solicitado. Se le
    pide al modelo `cantidad_fragmentos` fragmentos secuenciales con la
    siguiente forma:

    ```json
    {
        "titulo": "...",
        "fragmentos": [
            {
                "texto_narracion": "...",
                "tipo_respuesta": "elegir" | "escribir" | "pronunciar" | "",
                "pregunta_interactiva": "...",
                "opciones": [{"texto": "...", "es_correcta": true}, ...]
            }
        ]
    }
    ```

    El último fragmento puede tener `tipo_respuesta` vacío (solo narración,
    sin pregunta). `pregunta_interactiva` y `opciones` solo deben venir
    presentes cuando `tipo_respuesta` no es `""`, y `opciones` solo aplica
    a `tipo_respuesta == "elegir"`.

    Args:
        tema (str): tema o prompt libre dado por el administrador (ej.
            "un dragón que aprende a compartir").
        nivel_dificultad (int): nivel de dificultad de vocabulario, de 1
            (muy simple) a 5 (más elaborado).
        cantidad_fragmentos (int, optional): cantidad de fragmentos
            secuenciales a generar. Por defecto 4.

    Returns:
        dict: si la generación y validación tuvieron éxito,
            `{'status': 'success', 'titulo': str, 'fragmentos': list[dict]}`
            con la estructura ya validada. Si algo falla (red, timeout,
            JSON inválido o estructura inesperada),
            `{'status': 'error', 'message': str}` con un mensaje genérico
            (el detalle queda solo en el log interno).
    """
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
        # (few-shot) incrustado en el prompt produce resultados consistentes.
        nivel_descripcion = (
            'vocabulario muy simple y frases cortas' if nivel_dificultad <= 2
            else 'vocabulario moderado' if nivel_dificultad == 3
            else 'vocabulario más elaborado y frases más largas'
        )
        ejemplo_formato = {
            'titulo': 'El sol y la luna',
            'fragmentos': [
                {
                    'texto_narracion': 'El sol brilla en el cielo.',
                    'tipo_respuesta': '',
                    'pregunta_interactiva': '',
                    'opciones': [],
                },
                {
                    'texto_narracion': 'La luna sale de noche.',
                    'tipo_respuesta': 'elegir',
                    'pregunta_interactiva': '¿Cuándo sale la luna?',
                    'opciones': [
                        {'texto': 'De noche', 'es_correcta': True},
                        {'texto': 'De día', 'es_correcta': False},
                    ],
                },
            ],
        }
        prompt = (
            f'Genera una historia infantil corta en español sobre el tema: {tema}. '
            f'Debe tener exactamente {cantidad_fragmentos} fragmentos, con frases breves '
            f'({nivel_descripcion}). Al menos uno de los fragmentos debe tener '
            '"tipo_respuesta" igual a "elegir", con 2 opciones y solo una correcta. '
            'El contenido debe ser siempre positivo, apropiado para niños y sin ambigüedad. '
            'Responde ÚNICAMENTE con un JSON válido, sin texto antes ni después, sin '
            'markdown, con EXACTAMENTE esta forma (el siguiente es solo un ejemplo de '
            'formato, tu historia debe tener un tema y contenido distintos):\n'
            + json.dumps(ejemplo_formato, ensure_ascii=False)
        )

        respuesta = cliente.chat.completions.create(
            model=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
            messages=[{'role': 'user', 'content': prompt}],
            temperature=0.4,
            max_tokens=200 * cantidad_fragmentos,
            timeout=AZURE_OPENAI_TIMEOUT_SEGUNDOS,
        )

        contenido = respuesta.choices[0].message.content
        datos = json.loads(contenido)
        _validar_estructura_historia_generada(datos)

        return {
            'status': 'success',
            'titulo': datos['titulo'],
            'fragmentos': datos['fragmentos'],
        }
    except Exception:
        logger.error(
            'Error al generar historia completa con Azure OpenAI (tema=%s, nivel=%s)',
            tema, nivel_dificultad, exc_info=True,
        )
        return {
            'status': 'error',
            'message': 'No se pudo generar la historia. Intenta de nuevo.',
        }


def crear_historia_desde_ia(tema, nivel_dificultad):
    """
    Genera una historia completa vía IA y la persiste como `Historia` curada,
    con sus `FragmentoHistoria` y `OpcionRespuesta`, lista para usarse y
    editarse igual que una historia creada manualmente desde el admin.

    Calcula el siguiente `orden` disponible (máximo existente + 1) para no
    interferir con el desbloqueo secuencial de las historias ya creadas. No
    asigna `portada`: queda a criterio del administrador subirla después.

    Toda la creación (historia + fragmentos + opciones) ocurre dentro de una
    única transacción atómica: si la estructura devuelta por la IA resulta
    corrupta a mitad de la creación, se revierte por completo y no queda una
    `Historia` a medias en la base de datos.

    Args:
        tema (str): tema o prompt libre dado por el administrador.
        nivel_dificultad (int): nivel de dificultad de vocabulario, de 1 a 5.

    Returns:
        dict: `{'status': 'success', 'historia_id': int}` si la historia se
            creó correctamente, o `{'status': 'error', 'message': str}` con
            un mensaje genérico si la generación o la persistencia fallaron.
    """
    resultado_ia = generar_historia_completa_ia(tema, nivel_dificultad)
    if resultado_ia['status'] != 'success':
        return resultado_ia

    try:
        with transaction.atomic():
            siguiente_orden = (Historia.objects.aggregate(maximo=Max('orden'))['maximo'] or 0) + 1

            historia = Historia.objects.create(
                titulo=resultado_ia['titulo'][:100],
                nivel_dificultad=NIVEL_DIFICULTAD_NUMERICO_A_CHOICE.get(nivel_dificultad, 'facil'),
                duracion_estimada_minutos=max(
                    1, len(resultado_ia['fragmentos']) * DURACION_MINUTOS_POR_FRAGMENTO,
                ),
                recompensa_monedas=RECOMPENSA_MONEDAS_HISTORIA_IA,
                orden=siguiente_orden,
            )

            for indice, datos_fragmento in enumerate(resultado_ia['fragmentos'], start=1):
                fragmento = FragmentoHistoria.objects.create(
                    historia=historia,
                    orden=indice,
                    texto_narracion=datos_fragmento['texto_narracion'],
                    pregunta_interactiva=datos_fragmento.get('pregunta_interactiva') or '',
                    tipo_respuesta=datos_fragmento.get('tipo_respuesta') or '',
                )

                for datos_opcion in datos_fragmento.get('opciones') or []:
                    OpcionRespuesta.objects.create(
                        fragmento=fragmento,
                        texto=datos_opcion.get('texto', ''),
                        es_correcta=bool(datos_opcion.get('es_correcta')),
                    )

        return {'status': 'success', 'historia_id': historia.id}
    except Exception:
        logger.error(
            'Error al persistir la historia generada por IA (tema=%s, nivel=%s)',
            tema, nivel_dificultad, exc_info=True,
        )
        return {
            'status': 'error',
            'message': 'No se pudo guardar la historia generada. Intenta de nuevo.',
        }


def validar_palabras_clave(palabras_clave):
    """
    Valida en el servidor las palabras clave que el niño escribe para pedir
    una historia generada por IA, antes de tocar la API.

    Aplica una allowlist estricta de caracteres (letras con tildes/ñ,
    espacios y comas) y un límite de longitud, para evitar inyección de
    instrucciones hacia el LLM (backticks, llaves, símbolos de control,
    etc. quedan rechazados).

    Args:
        palabras_clave (str): texto crudo recibido del cliente.

    Returns:
        tuple[bool, str]: `(es_valido, mensaje_error)`. Si `es_valido` es
            `True`, `mensaje_error` es una cadena vacía.
    """
    if not palabras_clave or not palabras_clave.strip():
        return False, 'Escribe algunas palabras para crear tu historia.'

    palabras_clave = palabras_clave.strip()

    if len(palabras_clave) > LONGITUD_MAXIMA_PALABRAS_CLAVE:
        return False, 'Las palabras clave son demasiado largas.'

    if not PATRON_PALABRAS_CLAVE_VALIDAS.match(palabras_clave):
        return False, 'Usa solo letras, espacios y comas para tus palabras clave.'

    return True, ''


def _usuario_alcanzo_limite_diario(usuario):
    """Indica si `usuario` ya creó `LIMITE_HISTORIAS_GENERADAS_POR_USUARIO_24H` historias generadas en las últimas 24h."""
    desde = timezone.now() - datetime.timedelta(hours=24)
    cantidad = HistoriaGenerada.objects.filter(usuario=usuario, fecha_creacion__gte=desde).count()
    return cantidad >= LIMITE_HISTORIAS_GENERADAS_POR_USUARIO_24H


def _se_alcanzo_tope_global_diario():
    """Indica si, entre todos los usuarios, ya se alcanzó `TOPE_GLOBAL_HISTORIAS_GENERADAS_24H` en las últimas 24h."""
    desde = timezone.now() - datetime.timedelta(hours=24)
    cantidad = HistoriaGenerada.objects.filter(fecha_creacion__gte=desde).count()
    return cantidad >= TOPE_GLOBAL_HISTORIAS_GENERADAS_24H


def crear_historia_generada_desde_ia(usuario, palabras_clave):
    """
    Valida los límites de uso y las palabras clave del niño, genera una
    historia corta vía IA y la persiste como `HistoriaGenerada` efímera
    (con sus `FragmentoGenerado` y `OpcionGenerada`).

    Orden de validaciones (todas antes de llamar a la API, para no gastar
    presupuesto de IA en peticiones que de todos modos se van a rechazar):
    1. Palabras clave válidas (longitud + allowlist de caracteres).
    2. Límite por usuario (`LIMITE_HISTORIAS_GENERADAS_POR_USUARIO_24H` en 24h).
    3. Tope global (`TOPE_GLOBAL_HISTORIAS_GENERADAS_24H` en 24h).

    El conteo de los límites y la creación posterior se hacen dentro de una
    transacción atómica con `select_for_update()` sobre las filas recientes
    del propio usuario, para reducir (sin sobre-ingeniería) la ventana de
    condición de carrera ante doble clic o doble pestaña.

    Args:
        usuario: instancia de `UsuarioCustom` (estudiante autenticado).
        palabras_clave (str): palabras clave crudas escritas por el niño.

    Returns:
        dict: `{'status': 'success', 'historia_generada_id': int}` si todo
            salió bien, o `{'status': 'error', 'message': str}` con un
            mensaje genérico si la validación, los límites o la generación
            fallaron.
    """
    es_valido, mensaje_error = validar_palabras_clave(palabras_clave)
    if not es_valido:
        return {'status': 'error', 'message': mensaje_error}

    palabras_clave = palabras_clave.strip()

    try:
        with transaction.atomic():
            desde = timezone.now() - datetime.timedelta(hours=24)
            # Bloquea las filas recientes del usuario para acotar la
            # condición de carrera entre el conteo y la creación.
            list(
                HistoriaGenerada.objects.select_for_update()
                .filter(usuario=usuario, fecha_creacion__gte=desde)
            )

            if _usuario_alcanzo_limite_diario(usuario):
                return {
                    'status': 'error',
                    'message': 'Ya creaste muchas historias hoy. Vuelve a intentarlo mañana.',
                }

            if _se_alcanzo_tope_global_diario():
                return {
                    'status': 'error',
                    'message': 'Por hoy ya no se pueden crear más historias, vuelve mañana.',
                }

            resultado_ia = generar_historia_completa_ia(
                tema=palabras_clave,
                nivel_dificultad=NIVEL_DIFICULTAD_HISTORIA_GENERADA,
                cantidad_fragmentos=CANTIDAD_FRAGMENTOS_HISTORIA_GENERADA,
            )

            if resultado_ia['status'] != 'success':
                return resultado_ia

            historia_generada = HistoriaGenerada.objects.create(
                usuario=usuario,
                palabras_clave=palabras_clave,
                # El primer fragmento se crea con `orden=1`: se inicializa
                # aquí (en vez de dejar el `default=0` del modelo) para que
                # el progreso apunte de entrada al primer fragmento real.
                fragmento_actual=1,
            )

            for indice, datos_fragmento in enumerate(resultado_ia['fragmentos'], start=1):
                fragmento = FragmentoGenerado.objects.create(
                    historia_generada=historia_generada,
                    orden=indice,
                    texto_narracion=datos_fragmento['texto_narracion'],
                    pregunta_interactiva=datos_fragmento.get('pregunta_interactiva') or '',
                    tipo_respuesta=datos_fragmento.get('tipo_respuesta') or '',
                )

                for datos_opcion in datos_fragmento.get('opciones') or []:
                    OpcionGenerada.objects.create(
                        fragmento=fragmento,
                        texto=datos_opcion.get('texto', ''),
                        es_correcta=bool(datos_opcion.get('es_correcta')),
                    )

        return {'status': 'success', 'historia_generada_id': historia_generada.id}
    except Exception:
        logger.error(
            'Error al crear una historia generada por IA (usuario=%s)',
            getattr(usuario, 'id', None), exc_info=True,
        )
        return {
            'status': 'error',
            'message': 'No se pudo crear tu historia. Intenta de nuevo.',
        }


def obtener_historia_generada_vigente(usuario, historia_generada_id):
    """
    Obtiene una `HistoriaGenerada` verificando que pertenezca a `usuario` y
    que no esté expirada.

    No distingue en el mensaje de error entre "no existe", "es de otro
    usuario" o "expiró": en los tres casos se trata igual para no filtrar
    información sobre historias de otros usuarios.

    Args:
        usuario: instancia de `UsuarioCustom` (estudiante autenticado).
        historia_generada_id: identificador (`pk`) de la `HistoriaGenerada`.

    Returns:
        HistoriaGenerada | None: la instancia si es válida y vigente, o
            `None` si no existe, no es del usuario o ya expiró.
    """
    try:
        return HistoriaGenerada.objects.get(
            pk=historia_generada_id,
            usuario=usuario,
            fecha_expiracion__gt=timezone.now(),
        )
    except HistoriaGenerada.DoesNotExist:
        return None


def _serializar_fragmento_generado(fragmento):
    """Convierte un `FragmentoGenerado` en un diccionario apto para JSON."""
    return {
        'id': fragmento.id,
        'orden': fragmento.orden,
        'texto_narracion': fragmento.texto_narracion,
        'audio_narracion_url': None,
        'pregunta_interactiva': fragmento.pregunta_interactiva,
        'tipo_respuesta': fragmento.tipo_respuesta,
        'opciones': [
            _serializar_opcion(opcion)
            for opcion in fragmento.opciones.all()
        ] if fragmento.tipo_respuesta == 'elegir' else [],
    }


def construir_estado_lectura_generada(historia_generada):
    """
    Construye el estado de lectura de una `HistoriaGenerada`, con la misma
    forma que `construir_estado_lectura` para que el frontend pueda
    reutilizar el mismo renderizado.

    A diferencia de `construir_estado_lectura`, el progreso aquí es el
    campo simple `HistoriaGenerada.fragmento_actual` (orden, sin FK), ya que
    el modelo efímero no usa un `ProgresoHistoria` separado.

    Args:
        historia_generada (HistoriaGenerada): historia ya verificada como
            vigente y del usuario autenticado (ver
            `obtener_historia_generada_vigente`).

    Returns:
        dict: con las claves `historia` (datos básicos), `fragmentos`
            (lista serializada en orden), `fragmento_actual_id` y
            `completada`.
    """
    fragmentos = list(
        historia_generada.fragmentos.prefetch_related('opciones').order_by('orden')
    )

    fragmento_actual = next(
        (fragmento for fragmento in fragmentos if fragmento.orden == historia_generada.fragmento_actual),
        fragmentos[0] if fragmentos else None,
    )

    return {
        'historia': {
            'id': historia_generada.id,
            'titulo': historia_generada.palabras_clave,
            'recompensa_monedas': 0,
        },
        'fragmentos': [_serializar_fragmento_generado(fragmento) for fragmento in fragmentos],
        'fragmento_actual_id': fragmento_actual.id if fragmento_actual else None,
        'completada': historia_generada.completada,
    }


def procesar_respuesta_fragmento_generado(usuario, historia_generada, fragmento_id, opcion_id=None, texto_respuesta=None, archivo_audio=None):
    """
    Equivalente a `procesar_respuesta_fragmento` pero para `HistoriaGenerada`.

    Reutiliza los mismos helpers de evaluación genéricos
    (`_evaluar_elegir`, `_evaluar_escribir`, `_evaluar_pronunciar`,
    `_siguiente_fragmento_por_orden`). Condición bloqueante de arquitectura:
    NO otorga monedas, NO otorga insignias y NO registra actividad en
    `RegistroActividad`/`estadisticas` — las historias generadas son
    efímeras y de un solo uso, otorgar recompensas permitiría farmeo
    infinito. Al no haber más fragmentos, únicamente marca
    `HistoriaGenerada.completada = True`.

    Args:
        usuario: instancia de `UsuarioCustom` (estudiante autenticado).
        historia_generada (HistoriaGenerada): historia ya verificada como
            vigente y del usuario autenticado.
        fragmento_id: identificador (`pk`) del `FragmentoGenerado` respondido.
        opcion_id: identificador de la `OpcionGenerada` elegida (tipo 'elegir').
        texto_respuesta (str, optional): texto escrito por el estudiante (tipo 'escribir').
        archivo_audio: archivo de audio subido (tipo 'pronunciar').

    Returns:
        dict: `{'status': 'error', 'message': str}` si la validación falla,
            o `{'status': 'success', 'correcta': bool|None,
            'siguiente_fragmento': dict|None, 'completada': bool,
            'completada_ahora': bool, 'reaccion_avatar': dict|None}`. No
            incluye claves de monedas/insignias: nunca se otorgan en este
            flujo.
    """
    try:
        try:
            fragmento = historia_generada.fragmentos.get(pk=fragmento_id)
        except FragmentoGenerado.DoesNotExist:
            return {'status': 'error', 'message': 'El fragmento solicitado no existe.'}

        if historia_generada.completada:
            return {'status': 'error', 'message': 'Esta historia ya está completada.'}

        if historia_generada.fragmento_actual != fragmento.orden:
            return {'status': 'error', 'message': 'Este fragmento no corresponde a tu progreso actual.'}

        correcta = None
        if fragmento.tipo_respuesta == 'elegir':
            correcta, siguiente, mensaje_error = _evaluar_elegir(fragmento, opcion_id)
        elif fragmento.tipo_respuesta == 'escribir':
            correcta, siguiente, mensaje_error = _evaluar_escribir(fragmento, texto_respuesta)
        elif fragmento.tipo_respuesta == 'pronunciar':
            correcta, siguiente, mensaje_error = _evaluar_pronunciar_sin_registro(usuario, fragmento, archivo_audio)
        else:
            siguiente, mensaje_error = _siguiente_fragmento_por_orden(fragmento), None

        if mensaje_error:
            return {'status': 'error', 'message': mensaje_error}

        completada_ahora = False

        if siguiente is None:
            historia_generada.completada = True
            historia_generada.save()
            completada_ahora = True
        else:
            historia_generada.fragmento_actual = siguiente.orden
            historia_generada.save()

        return {
            'status': 'success',
            'correcta': correcta,
            'siguiente_fragmento': _serializar_fragmento_generado(siguiente) if siguiente else None,
            'completada': historia_generada.completada,
            'completada_ahora': completada_ahora,
            'reaccion_avatar': _construir_reaccion_avatar(completada_ahora, correcta),
        }
    except Exception:
        logger.error(
            'Error inesperado al procesar la respuesta de un fragmento de historia generada',
            exc_info=True,
        )
        raise


def _evaluar_pronunciar_sin_registro(usuario, fragmento, archivo_audio):
    """
    Igual que `_evaluar_pronunciar`, pero sin escribir en `RegistroActividad`.

    Las historias generadas por IA son efímeras y no deben dejar rastro en
    estadísticas (condición bloqueante de arquitectura, evita farmeo
    infinito de actividad/progreso mediante regeneración indefinida de
    historias).

    Args:
        usuario: instancia de `UsuarioCustom` (estudiante autenticado),
            recibido solo por simetría con `_evaluar_pronunciar` (no se usa
            para registrar actividad).
        fragmento (FragmentoGenerado): fragmento con la pregunta de pronunciación.
        archivo_audio: archivo de audio subido por el estudiante.

    Returns:
        tuple: `(correcta, siguiente_fragmento, mensaje_error)`.
    """
    opcion = fragmento.opciones.filter(es_correcta=True).first()
    if not opcion:
        return None, None, 'Este fragmento no tiene una palabra de referencia configurada.'

    ruta_audio_temporal = None
    try:
        ruta_audio_temporal = procesar_audio_subido(archivo_audio)
        resultado_azure = evaluar_pronunciacion_azure(ruta_audio_temporal, opcion.texto)
    except ValueError as error:
        return None, None, str(error)
    finally:
        if ruta_audio_temporal and os.path.exists(ruta_audio_temporal):
            os.remove(ruta_audio_temporal)

    if resultado_azure['status'] != 'success':
        return None, None, resultado_azure['message']

    correcta = resultado_azure['score_global'] >= UMBRAL_SUPERACION_NIVEL
    siguiente = _siguiente_fragmento_por_orden(fragmento)
    return correcta, siguiente, None


def obtener_historias_generadas_vivas(usuario):
    """
    Lista las `HistoriaGenerada` vigentes (no expiradas) del usuario, para
    la pestaña "Crear mi historia".

    Args:
        usuario: instancia de `UsuarioCustom` (estudiante autenticado).

    Returns:
        list[dict]: una entrada por cada `HistoriaGenerada` vigente, con las
            claves `id`, `palabras_clave`, `fecha_creacion`,
            `fecha_expiracion` y `completada`, ordenadas de la más reciente
            a la más antigua.
    """
    historias = HistoriaGenerada.objects.filter(
        usuario=usuario, fecha_expiracion__gt=timezone.now(),
    )

    return [
        {
            'id': historia.id,
            'palabras_clave': historia.palabras_clave,
            'fecha_creacion': historia.fecha_creacion.isoformat(),
            'fecha_expiracion': historia.fecha_expiracion.isoformat(),
            'completada': historia.completada,
        }
        for historia in historias
    ]
