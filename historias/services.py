"""
Capa de servicios del módulo `historias` (Módulo F del Master Plan).

Contiene la lógica de negocio del flujo de Historias Interactivas: listado de
historias con su estado de desbloqueo, lectura/avance de fragmentos
(incluyendo ramificación vía `OpcionRespuesta.fragmento_siguiente`),
evaluación de la respuesta del estudiante (voz, texto u opción) y
otorgamiento de recompensas (monedas + insignia) al completar una historia.
"""

import logging
import os
import unicodedata

from django.utils import timezone

from avatar.reactions import obtener_reaccion
from niveles.services import (
    UMBRAL_SUPERACION_NIVEL,
    evaluar_pronunciacion_azure,
    procesar_audio_subido,
)
from recompensas.services import otorgar_monedas, verificar_y_otorgar_insignias

from .models import FragmentoHistoria, Historia, OpcionRespuesta, ProgresoHistoria

logger = logging.getLogger(__name__)

# Número de estrellas a mostrar en el carrusel según la dificultad (F.2/UX).
ESTRELLAS_POR_DIFICULTAD = {
    'facil': 3,
    'medio': 5,
    'dificil': 8,
}


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

    if progreso.fragmento_actual is None and not progreso.completada:
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
    """Devuelve el `FragmentoHistoria` con `orden` inmediatamente mayor dentro de la misma historia, o `None`."""
    return FragmentoHistoria.objects.filter(
        historia_id=fragmento.historia_id, orden__gt=fragmento.orden,
    ).order_by('orden').first()


def _evaluar_elegir(fragmento, opcion_id):
    """Evalúa una respuesta de tipo 'elegir'. Devuelve `(correcta, siguiente_fragmento, mensaje_error)`."""
    try:
        opcion = fragmento.opciones.get(pk=opcion_id)
    except OpcionRespuesta.DoesNotExist:
        return None, None, 'La opción seleccionada no es válida.'

    siguiente = opcion.fragmento_siguiente or _siguiente_fragmento_por_orden(fragmento)
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
            siguiente = opcion.fragmento_siguiente or _siguiente_fragmento_por_orden(fragmento)
            return opcion.es_correcta, siguiente, None

    return False, _siguiente_fragmento_por_orden(fragmento), None


def _evaluar_pronunciar(fragmento, archivo_audio):
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

    correcta = resultado_azure['score_global'] >= UMBRAL_SUPERACION_NIVEL
    siguiente = opcion.fragmento_siguiente or _siguiente_fragmento_por_orden(fragmento)
    return correcta, siguiente, None


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

        if progreso.completada:
            return {'status': 'error', 'message': 'Esta historia ya está completada.'}

        if progreso.fragmento_actual_id != fragmento.id:
            return {'status': 'error', 'message': 'Este fragmento no corresponde a tu progreso actual.'}

        correcta = None
        if fragmento.tipo_respuesta == 'elegir':
            correcta, siguiente, mensaje_error = _evaluar_elegir(fragmento, opcion_id)
        elif fragmento.tipo_respuesta == 'escribir':
            correcta, siguiente, mensaje_error = _evaluar_escribir(fragmento, texto_respuesta)
        elif fragmento.tipo_respuesta == 'pronunciar':
            correcta, siguiente, mensaje_error = _evaluar_pronunciar(fragmento, archivo_audio)
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
            'reaccion_avatar': _construir_reaccion_avatar(completada_ahora, correcta),
            'monedas_ganadas': monedas_ganadas,
            'monedas_totales': monedas_totales,
            'insignia_nueva': insignia_nueva,
        }
    except Exception:
        logger.error('Error inesperado al procesar la respuesta de un fragmento de historia', exc_info=True)
        raise
