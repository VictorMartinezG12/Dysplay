"""
Capa de servicios del módulo `reportes` (Módulo J del Master Plan).

Construye el resumen de progreso de un estudiante a partir de
`estadisticas.services.construir_contexto_estadisticas` y lo envía por
correo al tutor configurado en `UsuarioCustom.correo_tutor`.
"""

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from estadisticas.services import construir_contexto_estadisticas

from .models import ReporteEnviado

logger = logging.getLogger(__name__)

# Número máximo de insignias recientes que se incluyen en el reporte.
CANTIDAD_INSIGNIAS_REPORTE = 3


def construir_resumen_reporte(usuario):
    """
    Construye un resumen reducido del progreso del estudiante, apto para
    incluirse en el correo de reporte al tutor.

    Reutiliza `estadisticas.services.construir_contexto_estadisticas` como
    fuente de datos y selecciona solo los campos relevantes para el email.

    Args:
        usuario: instancia de `UsuarioCustom` (estudiante).

    Returns:
        dict: resumen con `nombre_usuario`, `nivel_actual_numero`,
            `nivel_actual_titulo`, `racha_dias`, `puntuacion_total`,
            `lecciones_completadas`, `progreso_general_porcentaje`,
            `historias_completadas`, `palabras_pronunciadas`,
            `areas_mejora` (lista) e `insignias` (las 3 más recientes).
    """
    contexto = construir_contexto_estadisticas(usuario)

    return {
        'nombre_usuario': usuario.username,
        'nivel_actual_numero': contexto['nivel_actual_numero'],
        'nivel_actual_titulo': contexto['nivel_actual_titulo'],
        'racha_dias': contexto['racha_dias'],
        'puntuacion_total': contexto['puntuacion_total'],
        'lecciones_completadas': contexto['lecciones_completadas'],
        'progreso_general_porcentaje': contexto['progreso_general_porcentaje'],
        'historias_completadas': contexto['historias_completadas'],
        'palabras_pronunciadas': contexto['palabras_pronunciadas'],
        'areas_mejora': contexto['areas_mejora'],
        'insignias': contexto['insignias'][:CANTIDAD_INSIGNIAS_REPORTE],
    }


def enviar_reporte_progreso(usuario, tipo_envio):
    """
    Envía un correo con el resumen de progreso del estudiante al correo
    de su tutor (`usuario.correo_tutor`) y registra el resultado.

    Si el usuario no tiene `correo_tutor` configurado, no se envía nada ni
    se crea un `ReporteEnviado`.

    Args:
        usuario: instancia de `UsuarioCustom` (estudiante).
        tipo_envio (str): `ReporteEnviado.TIPO_MANUAL` o
            `ReporteEnviado.TIPO_AUTOMATICO`.

    Returns:
        dict: `{'status': 'sin_correo' | 'success' | 'error'}`.
    """
    correo_tutor = usuario.correo_tutor
    if not correo_tutor:
        return {'status': 'sin_correo'}

    resumen = construir_resumen_reporte(usuario)
    asunto = f"Reporte de progreso de {usuario.username} en DysPlay"

    cuerpo_texto = render_to_string('reportes/email_reporte.txt', resumen)
    cuerpo_html = render_to_string('reportes/email_reporte.html', resumen)

    try:
        correo = EmailMultiAlternatives(
            subject=asunto,
            body=cuerpo_texto,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[correo_tutor],
        )
        correo.attach_alternative(cuerpo_html, "text/html")
        correo.send()
    except Exception:
        logger.error("Error al enviar el reporte de progreso por correo", exc_info=True)
        ReporteEnviado.objects.create(
            usuario=usuario,
            correo_destino=correo_tutor,
            tipo_envio=tipo_envio,
            exitoso=False,
        )
        return {'status': 'error'}

    ReporteEnviado.objects.create(
        usuario=usuario,
        correo_destino=correo_tutor,
        tipo_envio=tipo_envio,
        exitoso=True,
    )
    return {'status': 'success'}
