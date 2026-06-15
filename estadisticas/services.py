"""
Capa de servicios del módulo `estadisticas` (Módulo H del Master Plan).

Construye, con datos reales (sin valores hardcodeados), el contexto del
panel de Estadísticas: resumen de progreso (H.1), gráfico de actividad
semanal, progreso y áreas de mejora por zona del Mapa de Aventura,
calendario de progreso (H.2) y galería de coleccionables (H.3).
"""

import datetime
import logging

from django.db.models import Avg, Sum
from django.utils import timezone

from historias.models import ProgresoHistoria
from niveles.models import Nivel, ProgresoEstudiante
from niveles.services import ZONAS_MAPA_AVENTURA
from recompensas.models import Coleccionable, ColeccionableUsuario, Insignia

from .models import RegistroActividad

logger = logging.getLogger(__name__)

# Umbral de score promedio por zona por debajo del cual se considera un
# "área de mejora" (H.1, criterio de aceptación).
UMBRAL_AREA_MEJORA = 60

# Abreviaturas de los días de la semana en español (lunes=0 ... domingo=6),
# usadas en el gráfico de actividad semanal.
NOMBRES_DIAS_SEMANA = ['Lu', 'Ma', 'Mi', 'Ju', 'Vi', 'Sá', 'Do']

# Número de semanas mostradas en el calendario de progreso (H.2).
SEMANAS_CALENDARIO = 4


def _nivel_maximo_completado(progreso):
    """
    Calcula cuántos niveles del Mapa de Aventura ha completado el estudiante.

    Un nivel se considera completado si su `numero` es menor al del
    `nivel_actual` del progreso del estudiante (mismo criterio que
    `niveles.services.obtener_mapa_aventura`).

    Args:
        progreso (ProgresoEstudiante): progreso del estudiante.

    Returns:
        int: cantidad de niveles completados (0 si no tiene `nivel_actual`).
    """
    if progreso.nivel_actual is None:
        return 0
    return Nivel.objects.filter(numero__lt=progreso.nivel_actual.numero).count()


def construir_datos_semana(usuario):
    """
    Cuenta las actividades (`RegistroActividad`) de los últimos 7 días.

    Args:
        usuario: instancia de `UsuarioCustom` (estudiante autenticado).

    Returns:
        list[dict]: una entrada por día (de hace 6 días a hoy), cada una con
            `dia` (abreviatura en español), `fecha`, `cantidad` (número de
            evaluaciones exitosas ese día), `altura_porcentaje` (0-100, para
            la altura de la barra en el gráfico) y `es_hoy` (bool).
    """
    hoy = timezone.localdate()
    inicio = hoy - datetime.timedelta(days=6)

    registros = RegistroActividad.objects.filter(usuario=usuario, fecha__gte=inicio, fecha__lte=hoy)
    conteos = {}
    for registro in registros:
        conteos[registro.fecha] = conteos.get(registro.fecha, 0) + 1

    cantidades = [conteos.get(inicio + datetime.timedelta(days=i), 0) for i in range(7)]
    maximo = max(cantidades) or 1

    datos = []
    for i in range(7):
        fecha = inicio + datetime.timedelta(days=i)
        cantidad = cantidades[i]
        datos.append({
            'dia': NOMBRES_DIAS_SEMANA[fecha.weekday()],
            'fecha': fecha,
            'cantidad': cantidad,
            'altura_porcentaje': round((cantidad / maximo) * 100),
            'es_hoy': fecha == hoy,
        })
    return datos


def construir_progreso_por_zona(progreso):
    """
    Calcula el porcentaje de niveles completados en cada zona del Mapa de Aventura.

    Args:
        progreso (ProgresoEstudiante): progreso del estudiante.

    Returns:
        list[dict]: una entrada por cada zona con al menos un `Nivel`, con
            `clave`, `nombre` y `porcentaje` (0-100).
    """
    nivel_actual_numero = progreso.nivel_actual.numero if progreso.nivel_actual else None

    resultado = []
    for zona_info in ZONAS_MAPA_AVENTURA:
        niveles_zona = Nivel.objects.filter(zona=zona_info['clave'])
        total = niveles_zona.count()
        if total == 0:
            continue

        completados = 0
        if nivel_actual_numero is not None:
            completados = niveles_zona.filter(numero__lt=nivel_actual_numero).count()

        resultado.append({
            'clave': zona_info['clave'],
            'nombre': zona_info['nombre'],
            'porcentaje': round((completados / total) * 100),
        })
    return resultado


def construir_areas_mejora(usuario):
    """
    Identifica las zonas del Mapa de Aventura donde el estudiante necesita más práctica.

    Una zona se considera un "área de mejora" si el score promedio de las
    evaluaciones (`RegistroActividad`) registradas para esa zona está por
    debajo de `UMBRAL_AREA_MEJORA`. Las zonas sin evaluaciones registradas no
    se incluyen (no hay datos suficientes para evaluarlas).

    Args:
        usuario: instancia de `UsuarioCustom` (estudiante autenticado).

    Returns:
        list[dict]: una entrada por cada zona a practicar, con `clave`,
            `nombre` y `score_promedio` (0-100).
    """
    areas = []
    for zona_info in ZONAS_MAPA_AVENTURA:
        promedio = RegistroActividad.objects.filter(
            usuario=usuario, zona=zona_info['clave'],
        ).aggregate(promedio=Avg('score'))['promedio']

        if promedio is not None and promedio < UMBRAL_AREA_MEJORA:
            areas.append({
                'clave': zona_info['clave'],
                'nombre': zona_info['nombre'],
                'score_promedio': round(promedio),
            })
    return areas


def construir_calendario_progreso(usuario):
    """
    Construye el calendario de progreso (H.2): un grid de 7 columnas por semana.

    Cubre las últimas `SEMANAS_CALENDARIO` semanas (de lunes a domingo,
    terminando en la semana actual) y marca cada día según si el estudiante
    tuvo al menos una actividad (`RegistroActividad`) registrada ese día.

    Args:
        usuario: instancia de `UsuarioCustom` (estudiante autenticado).

    Returns:
        list[list[dict]]: lista de semanas, cada una con 7 días (`fecha`,
            `dia_numero`, `tiene_actividad`, `es_hoy`, `es_futuro`).
    """
    hoy = timezone.localdate()
    inicio_semana_actual = hoy - datetime.timedelta(days=hoy.weekday())
    inicio_calendario = inicio_semana_actual - datetime.timedelta(weeks=SEMANAS_CALENDARIO - 1)

    fechas_con_actividad = set(
        RegistroActividad.objects.filter(
            usuario=usuario, fecha__gte=inicio_calendario, fecha__lte=hoy,
        ).values_list('fecha', flat=True)
    )

    semanas = []
    for semana in range(SEMANAS_CALENDARIO):
        dias = []
        for dia in range(7):
            fecha = inicio_calendario + datetime.timedelta(days=semana * 7 + dia)
            dias.append({
                'fecha': fecha,
                'dia_numero': fecha.day,
                'tiene_actividad': fecha in fechas_con_actividad,
                'es_hoy': fecha == hoy,
                'es_futuro': fecha > hoy,
            })
        semanas.append(dias)
    return semanas


def construir_galeria_coleccionables(usuario):
    """
    Agrupa los `Coleccionable` por tipo, marcando los que el usuario ya obtuvo (H.3).

    Args:
        usuario: instancia de `UsuarioCustom` (estudiante autenticado).

    Returns:
        list[dict]: una entrada por cada tipo de coleccionable con al menos
            un elemento, con `tipo`, `nombre_tipo` y `items` (lista de
            `{'nombre', 'imagen', 'obtenido'}`).
    """
    ids_obtenidos = set(
        ColeccionableUsuario.objects.filter(usuario=usuario).values_list('coleccionable_id', flat=True)
    )

    galeria = {}
    for coleccionable in Coleccionable.objects.all():
        grupo = galeria.setdefault(coleccionable.tipo, {
            'tipo': coleccionable.tipo,
            'nombre_tipo': coleccionable.get_tipo_display(),
            'items': [],
        })
        grupo['items'].append({
            'nombre': coleccionable.nombre,
            'imagen': coleccionable.imagen,
            'obtenido': coleccionable.id in ids_obtenidos,
        })

    return list(galeria.values())


def construir_insignias(usuario):
    """
    Lista las insignias obtenidas por el usuario con su tipo y fecha de obtención.

    Args:
        usuario: instancia de `UsuarioCustom` (estudiante autenticado).

    Returns:
        list[dict]: una entrada por insignia obtenida, con `nombre`,
            `descripcion`, `imagen` y `fecha_obtenida`, ordenadas de la más
            reciente a la más antigua.
    """
    return [
        {
            'nombre': insignia.tipo_insignia.nombre,
            'descripcion': insignia.tipo_insignia.descripcion,
            'imagen': insignia.tipo_insignia.imagen,
            'fecha_obtenida': insignia.fecha_obtenida,
        }
        for insignia in Insignia.objects.filter(usuario=usuario)
            .select_related('tipo_insignia').order_by('-fecha_obtenida')
    ]


def construir_contexto_estadisticas(usuario):
    """
    Construye el contexto completo del panel de Estadísticas (H.1, H.2, H.3).

    Todos los valores se calculan a partir de datos reales del usuario:
    `ProgresoEstudiante`, `ProgresoHistoria`, `Insignia`, `ColeccionableUsuario`
    y el historial de evaluaciones exitosas (`RegistroActividad`).

    Args:
        usuario: instancia de `UsuarioCustom` (estudiante autenticado).

    Returns:
        dict: contexto listo para `estadisticas/estadisticas.html`.
    """
    progreso, _creado = ProgresoEstudiante.objects.get_or_create(usuario=usuario)

    puntuacion_total = RegistroActividad.objects.filter(usuario=usuario).aggregate(
        total=Sum('score'),
    )['total'] or 0

    nivel_maximo_completado = _nivel_maximo_completado(progreso)
    total_niveles = Nivel.objects.count()
    progreso_general_porcentaje = (
        round((nivel_maximo_completado / total_niveles) * 100) if total_niveles else 0
    )

    return {
        'nivel_actual_numero': progreso.nivel_actual.numero if progreso.nivel_actual else 0,
        'nivel_actual_titulo': progreso.nivel_actual.titulo if progreso.nivel_actual else '',
        'puntuacion_total': round(puntuacion_total),
        'racha_dias': usuario.racha_dias,
        'lecciones_completadas': nivel_maximo_completado,
        'progreso_general_porcentaje': progreso_general_porcentaje,
        'palabras_pronunciadas': RegistroActividad.objects.filter(usuario=usuario).count(),
        'historias_completadas': ProgresoHistoria.objects.filter(usuario=usuario, completada=True).count(),
        'insignias': construir_insignias(usuario),
        'coleccionables': construir_galeria_coleccionables(usuario),
        'datos_semana': construir_datos_semana(usuario),
        'progreso_por_zona': construir_progreso_por_zona(progreso),
        'areas_mejora': construir_areas_mejora(usuario),
        'calendario': construir_calendario_progreso(usuario),
    }
