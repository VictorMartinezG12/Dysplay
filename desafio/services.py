"""
Capa de servicios del módulo `desafio` (Módulo E del Master Plan).

Contiene la lógica de negocio del Desafío Diario: generación del desafío del
día, narrativa continua, evaluación de los ejercicios (reutilizando Azure
Speech vía `niveles.services`), y otorgamiento de recompensas (monedas,
coleccionables e insignias) al completar el desafío completo.
"""

import logging
import os
import random

from django.utils import timezone

from avatar.reactions import obtener_reaccion
from estadisticas.models import RegistroActividad
from niveles.models import MisionVocabulario, Nivel, ProgresoEstudiante
from niveles.services import (
    UMBRAL_SUPERACION_NIVEL,
    evaluar_pronunciacion_azure,
    procesar_audio_subido,
)
from recompensas.models import Coleccionable, ColeccionableUsuario
from recompensas.services import otorgar_monedas, verificar_y_otorgar_insignias

from .models import ConfiguracionDesafio, DesafioDiario, ProgresoDesafio

logger = logging.getLogger(__name__)

# Narrativa continua del desafío (E.2): arco general común a todos los días,
# más un fragmento específico según la zona/arco activo.
NARRATIVA_ARCO_GENERAL = (
    'Las letras mágicas desaparecieron del reino. Cada día recuperas una pieza del reino.'
)

NARRATIVAS_POR_ZONA = {
    Nivel.ZONA_BOSQUE: 'Hoy estás recuperando las vocales del Bosque Encantado.',
    Nivel.ZONA_MONTANA: 'Hoy estás restaurando las consonantes de la Montaña de las Letras.',
    Nivel.ZONA_VALLE: 'Hoy estás reuniendo las sílabas del Valle de las Sílabas.',
    Nivel.ZONA_CASTILLO: 'Hoy estás reconstruyendo las palabras del Castillo de las Palabras.',
    Nivel.ZONA_REINO: 'Hoy estás iluminando los libros del Reino de la Lectura.',
}

# Máximo de ejercicios opcionales que se muestran en el desafío (E.4: "3 tarjetas").
MAXIMO_EJERCICIOS_OPCIONALES = 3


def obtener_narrativa_del_dia(configuracion):
    """
    Construye el párrafo narrativo del desafío de hoy (E.2).

    Si `configuracion.texto_narrativa_actual` fue definido manualmente desde
    el admin, se usa tal cual. De lo contrario, se compone con el arco
    general más el fragmento correspondiente a `zona_activa`.

    Args:
        configuracion (ConfiguracionDesafio): configuración global vigente.

    Returns:
        str: párrafo narrativo a mostrar en el banner del desafío.
    """
    if configuracion.texto_narrativa_actual:
        return configuracion.texto_narrativa_actual

    fragmento_zona = NARRATIVAS_POR_ZONA.get(configuracion.zona_activa, '')
    return f'{NARRATIVA_ARCO_GENERAL} {fragmento_zona}'.strip()


def obtener_o_crear_desafio_de_hoy(configuracion=None):
    """
    Obtiene el `DesafioDiario` de la fecha actual, creándolo si no existe.

    Al crearlo, toma `recompensa_monedas_base` de la configuración global.
    Ya NO asigna ejercicios automáticamente al crearse: los ejercicios se
    determinan por usuario en `_obtener_ejercicios_desafio` (ver ese
    docstring), salvo que el administrador haya definido manualmente
    `ejercicios_obligatorios`/`ejercicios_opcionales` desde el admin.

    Args:
        configuracion (ConfiguracionDesafio, optional): configuración ya
            obtenida, para evitar una consulta extra. Si no se provee, se
            obtiene internamente.

    Returns:
        DesafioDiario: el desafío correspondiente a hoy.
    """
    configuracion = configuracion or ConfiguracionDesafio.obtener_configuracion()
    fecha_hoy = timezone.localdate()

    desafio, _creado = DesafioDiario.objects.get_or_create(
        fecha=fecha_hoy,
        defaults={'recompensa_monedas': configuracion.recompensa_monedas_base},
    )

    return desafio


def _nivel_numero_usuario(usuario):
    """
    Devuelve el nivel actual (entero) de progreso de un estudiante.

    Se usa para acotar la selección de ejercicios del desafío diario al
    nivel que el estudiante ya tiene desbloqueado (mismo patrón que
    `camara_inteligente.services._nivel_dificultad_usuario`).

    Args:
        usuario: instancia de `UsuarioCustom` (estudiante autenticado).

    Returns:
        int: `ProgresoEstudiante.nivel_actual.numero`, o 1 si el estudiante
            no tiene progreso o nivel asignado.
    """
    progreso = ProgresoEstudiante.objects.filter(usuario=usuario).first()
    if progreso and progreso.nivel_actual:
        return progreso.nivel_actual.numero
    return 1


def _seleccionar_ejercicios_para_usuario(usuario, desafio):
    """
    Elige un ejercicio obligatorio y hasta `MAXIMO_EJERCICIOS_OPCIONALES`
    opcionales para `usuario` en el `desafio` de hoy, acotados a su nivel.

    El pool de selección se limita a las `MisionVocabulario` de nivel menor
    o igual al nivel actual del estudiante (`_nivel_numero_usuario`), para
    que el desafío escale con su progreso real en vez de sortear entre todo
    el catálogo. Si el estudiante no tiene ninguna misión disponible en su
    rango (por ejemplo, recién empieza y aún no hay contenido en nivel 1),
    se cae al catálogo completo como respaldo, para que el flujo nunca se
    quede sin ejercicios.

    La selección es determinista por `(usuario, fecha)`: se siembra un
    `random.Random` propio con esa combinación, así que dentro del mismo
    día el estudiante siempre ve el mismo conjunto, sin necesidad de
    persistir nada nuevo en base de datos.

    Args:
        usuario: instancia de `UsuarioCustom` (estudiante autenticado).
        desafio (DesafioDiario): desafío de la fecha actual.

    Returns:
        tuple[list[MisionVocabulario], list[MisionVocabulario]]:
            `(ejercicios_obligatorios, ejercicios_opcionales)`.
    """
    nivel_usuario = _nivel_numero_usuario(usuario)
    misiones = list(MisionVocabulario.objects.filter(nivel__numero__lte=nivel_usuario))
    if not misiones:
        misiones = list(MisionVocabulario.objects.all())
    if not misiones:
        logger.warning('No hay MisionVocabulario disponibles para generar el desafío del %s', desafio.fecha)
        return [], []

    generador_aleatorio = random.Random(f'{usuario.pk}-{desafio.fecha.isoformat()}')
    generador_aleatorio.shuffle(misiones)

    obligatorio, *resto = misiones
    return [obligatorio], resto[:MAXIMO_EJERCICIOS_OPCIONALES]


def _obtener_ejercicios_desafio(usuario, desafio):
    """
    Devuelve los ejercicios obligatorios y opcionales vigentes para
    `usuario` en `desafio`.

    Si el administrador definió manualmente `ejercicios_obligatorios`/
    `ejercicios_opcionales` en `DesafioDiario` (override editorial,
    compartido por todos los estudiantes ese día), se usan esos tal cual.
    De lo contrario, se calculan de forma personalizada según el nivel del
    usuario (`_seleccionar_ejercicios_para_usuario`).

    Args:
        usuario: instancia de `UsuarioCustom` (estudiante autenticado).
        desafio (DesafioDiario): desafío de la fecha actual.

    Returns:
        tuple[list[MisionVocabulario], list[MisionVocabulario]]:
            `(ejercicios_obligatorios, ejercicios_opcionales)`.
    """
    obligatorios_admin = list(desafio.ejercicios_obligatorios.all())
    opcionales_admin = list(desafio.ejercicios_opcionales.all())
    if obligatorios_admin or opcionales_admin:
        return obligatorios_admin, opcionales_admin

    return _seleccionar_ejercicios_para_usuario(usuario, desafio)


def obtener_o_crear_progreso(usuario, desafio):
    """
    Obtiene el `ProgresoDesafio` de `usuario` para `desafio`, creándolo si no existe.

    Args:
        usuario: instancia de `UsuarioCustom` (estudiante autenticado).
        desafio (DesafioDiario): desafío sobre el que se consulta el progreso.

    Returns:
        ProgresoDesafio: progreso del usuario sobre el desafío indicado.
    """
    progreso, _creado = ProgresoDesafio.objects.get_or_create(usuario=usuario, desafio=desafio)
    return progreso


def calcular_segundos_hasta_reinicio():
    """
    Calcula los segundos restantes hasta la medianoche (hora local), momento
    en que se habilita un nuevo desafío diario.

    Returns:
        int: cantidad de segundos restantes hasta el próximo desafío.
    """
    ahora = timezone.localtime()
    medianoche_siguiente = (ahora + timezone.timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    return int((medianoche_siguiente - ahora).total_seconds())


def _serializar_ejercicios(misiones, ids_completados):
    """Convierte un queryset de `MisionVocabulario` en una lista de diccionarios para el template."""
    return [
        {
            'id': mision.id,
            'palabra_objetivo': mision.palabra_objetivo,
            'frase_historia': mision.frase_historia,
            'completado': mision.id in ids_completados,
        }
        for mision in misiones
    ]


def construir_estado_desafio(usuario):
    """
    Construye todo el estado necesario para renderizar la pantalla del desafío diario (E.4).

    Args:
        usuario: instancia de `UsuarioCustom` (estudiante autenticado).

    Returns:
        dict: con las claves `desafio`, `progreso`, `narrativa`,
            `obligatorios` y `opcionales` (listas de ejercicios
            serializados), `bloqueado` (bool, si el desafío de hoy ya está
            completado) y `segundos_restantes` (int o None).
    """
    configuracion = ConfiguracionDesafio.obtener_configuracion()
    desafio = obtener_o_crear_desafio_de_hoy(configuracion)
    progreso = obtener_o_crear_progreso(usuario, desafio)

    ids_completados = set(progreso.ejercicios_completados.values_list('id', flat=True))
    ejercicios_obligatorios, ejercicios_opcionales = _obtener_ejercicios_desafio(usuario, desafio)

    return {
        'desafio': desafio,
        'progreso': progreso,
        'narrativa': obtener_narrativa_del_dia(configuracion),
        'obligatorios': _serializar_ejercicios(ejercicios_obligatorios, ids_completados),
        'opcionales': _serializar_ejercicios(ejercicios_opcionales, ids_completados),
        'bloqueado': progreso.completado,
        'segundos_restantes': calcular_segundos_hasta_reinicio() if progreso.completado else None,
    }


def otorgar_coleccionable_aleatorio(usuario, desafio):
    """
    Otorga un coleccionable al completar el desafío diario (E.3).

    Si `desafio.recompensa_coleccionable` está definido y el usuario aún no
    lo posee, se otorga ese. En caso contrario, se elige al azar entre los
    `Coleccionable` que el usuario todavía no tenga. Si el usuario ya posee
    todos los coleccionables existentes, no se otorga nada.

    Args:
        usuario: instancia de `UsuarioCustom` (estudiante autenticado).
        desafio (DesafioDiario): desafío recién completado.

    Returns:
        ColeccionableUsuario | None: el registro creado, o `None` si no
            había ningún coleccionable disponible para otorgar.
    """
    ids_poseidos = set(
        ColeccionableUsuario.objects.filter(usuario=usuario).values_list('coleccionable_id', flat=True)
    )
    candidatos = list(Coleccionable.objects.exclude(pk__in=ids_poseidos))

    if not candidatos:
        return None

    if desafio.recompensa_coleccionable and desafio.recompensa_coleccionable.pk not in ids_poseidos:
        elegido = desafio.recompensa_coleccionable
    else:
        elegido = random.choice(candidatos)

    return ColeccionableUsuario.objects.create(usuario=usuario, coleccionable=elegido)


def _construir_reaccion_avatar(ejercicio_superado, desafio_completado_ahora):
    """Construye los datos planos `{tipo, mensaje}` de la reacción del avatar para un intento del desafío."""
    if desafio_completado_ahora:
        tipo = 'desafio_completado'
    elif ejercicio_superado:
        tipo = 'pronunciacion_correcta'
    else:
        tipo = 'pronunciacion_incorrecta'

    return {'tipo': tipo, 'mensaje': obtener_reaccion(tipo)}


def procesar_intento_desafio(usuario, archivo_audio, mision_id):
    """
    Orquesta un intento de pronunciación dentro del desafío diario.

    Valida y procesa el audio recibido, lo evalúa contra Azure Speech y, si
    el estudiante supera el umbral, marca el ejercicio como completado. Si
    con esto se completan todos los ejercicios (obligatorios + opcionales)
    del desafío de hoy, marca `ProgresoDesafio.completado`, otorga las
    monedas configuradas, un coleccionable aleatorio y evalúa la insignia
    diaria. El archivo temporal de audio se elimina siempre.

    Args:
        usuario: instancia de `UsuarioCustom` (estudiante autenticado).
        archivo_audio: archivo de audio subido (`request.FILES.get('audio')`).
        mision_id: identificador (`pk`) de la `MisionVocabulario` evaluada.

    Returns:
        dict: si la validación o la evaluación de Azure fallan,
            `{'status': 'error', 'message': str}`. Si todo sale bien, un
            diccionario con `status='success'` y las claves `score`,
            `score_exactitud`, `palabras`, `ejercicio_superado`, `mision_id`,
            `desafio_completado`, `desafio_completado_ahora`,
            `monedas_ganadas`, `coleccionable_obtenido` (dict o None),
            `insignia_nueva` (bool) y `reaccion_avatar` (`{'tipo', 'mensaje'}`).

    Raises:
        Exception: cualquier error inesperado se loguea con
            `logging.error(..., exc_info=True)` y se relanza; la vista que
            invoca esta función es responsable de convertirlo en una
            respuesta HTTP genérica.
    """
    ruta_audio_temporal = None
    try:
        try:
            mision_id = int(mision_id)
        except (TypeError, ValueError):
            return {'status': 'error', 'message': 'Ejercicio no válido.'}

        configuracion = ConfiguracionDesafio.obtener_configuracion()
        desafio = obtener_o_crear_desafio_de_hoy(configuracion)
        progreso = obtener_o_crear_progreso(usuario, desafio)

        if progreso.completado:
            return {'status': 'error', 'message': 'El desafío de hoy ya está completado.'}

        ejercicios_obligatorios, ejercicios_opcionales = _obtener_ejercicios_desafio(usuario, desafio)
        ids_ejercicios_desafio = {
            mision.id for mision in ejercicios_obligatorios + ejercicios_opcionales
        }

        if mision_id not in ids_ejercicios_desafio:
            return {'status': 'error', 'message': 'Este ejercicio no pertenece al desafío de hoy.'}

        try:
            mision = MisionVocabulario.objects.get(pk=mision_id)
        except MisionVocabulario.DoesNotExist:
            logger.error('Misión inexistente referenciada en el desafío diario (id=%s)', mision_id, exc_info=True)
            return {'status': 'error', 'message': 'No se encontró el ejercicio solicitado.'}

        ruta_audio_temporal = procesar_audio_subido(archivo_audio)
        resultado_azure = evaluar_pronunciacion_azure(ruta_audio_temporal, mision.palabra_objetivo)

        if resultado_azure['status'] != 'success':
            return {'status': 'error', 'message': resultado_azure['message']}

        score_global = resultado_azure['score_global']
        ejercicio_superado = score_global >= UMBRAL_SUPERACION_NIVEL

        RegistroActividad.objects.registrar(
            usuario, RegistroActividad.TIPO_DESAFIO, score_global, zona=mision.nivel.zona,
        )

        if ejercicio_superado:
            progreso.ejercicios_completados.add(mision)

        monedas_ganadas = 0
        coleccionable_obtenido = None
        insignias_nuevas = []
        desafio_completado_ahora = False

        ids_completados = set(progreso.ejercicios_completados.values_list('id', flat=True))
        if ids_ejercicios_desafio and ids_ejercicios_desafio.issubset(ids_completados):
            progreso.completado = True
            progreso.fecha_completado = timezone.now()
            progreso.monedas_ganadas = desafio.recompensa_monedas
            progreso.save()

            otorgar_monedas(usuario, desafio.recompensa_monedas, concepto='desafio_diario_completado')
            monedas_ganadas = desafio.recompensa_monedas

            coleccionable_obtenido = otorgar_coleccionable_aleatorio(usuario, desafio)

            # Asegura que exista ProgresoEstudiante antes de evaluar insignias
            # (verificar_y_otorgar_insignias no evalúa nada si no existe).
            ProgresoEstudiante.objects.get_or_create(usuario=usuario)
            insignias_nuevas = verificar_y_otorgar_insignias(usuario)

            desafio_completado_ahora = True

        reaccion_avatar = _construir_reaccion_avatar(ejercicio_superado, desafio_completado_ahora)

        return {
            'status': 'success',
            'score': score_global,
            'score_exactitud': resultado_azure.get('score_exactitud'),
            'palabras': resultado_azure.get('palabras', []),
            'ejercicio_superado': ejercicio_superado,
            'mision_id': mision_id,
            'desafio_completado': progreso.completado,
            'desafio_completado_ahora': desafio_completado_ahora,
            'monedas_ganadas': monedas_ganadas,
            'coleccionable_obtenido': (
                {
                    'nombre': coleccionable_obtenido.coleccionable.nombre,
                    'tipo': coleccionable_obtenido.coleccionable.get_tipo_display(),
                }
                if coleccionable_obtenido else None
            ),
            'insignia_nueva': bool(insignias_nuevas),
            'reaccion_avatar': reaccion_avatar,
        }
    except Exception:
        logger.error('Error inesperado al procesar el intento del desafío diario', exc_info=True)
        raise
    finally:
        if ruta_audio_temporal and os.path.exists(ruta_audio_temporal):
            os.remove(ruta_audio_temporal)
