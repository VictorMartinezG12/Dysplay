"""
Señales (signals) del módulo `recompensas`.

Conecta eventos del sistema (progreso del estudiante, inicio de sesión) con
las funciones de la capa de servicios para mantener el sistema de
recompensas siempre actualizado sin que cada módulo tenga que invocarlo
manualmente.
"""

import logging

from django.contrib.auth.signals import user_logged_in
from django.db.models.signals import post_save
from django.dispatch import receiver

from niveles.models import ProgresoEstudiante

from .services import actualizar_racha, verificar_y_otorgar_insignias

logger = logging.getLogger(__name__)


@receiver(post_save, sender=ProgresoEstudiante)
def manejar_progreso_guardado(sender, instance, **kwargs):
    """
    Verifica y otorga insignias cada vez que se guarda el progreso de un estudiante.

    Se ejecuta tras cada `post_save` de `ProgresoEstudiante`. Delega en
    `verificar_y_otorgar_insignias`, que no realiza `.save()` sobre el
    progreso ni sobre el usuario, evitando así una recursión de signals.

    DESVÍO APROBADO respecto al Master Plan: el Master Plan sugiere disparar
    también `actualizar_racha` desde este mismo signal de `post_save` en
    `ProgresoEstudiante`. El arquitecto decidió que la racha se actualice
    ÚNICAMENTE en el signal `user_logged_in`, ya que es el evento
    semánticamente correcto ("el usuario se conectó hoy") y evita escrituras
    repetidas de `ultima_fecha_conexion`/`racha_dias` cada vez que se guarda
    el progreso dentro de una misma sesión.

    Args:
        sender: clase del modelo que emitió la señal (`ProgresoEstudiante`).
        instance: instancia de `ProgresoEstudiante` que fue guardada.
        **kwargs: argumentos adicionales de la señal `post_save`.
    """
    try:
        verificar_y_otorgar_insignias(instance.usuario)
    except Exception:
        logger.error(
            "Error al verificar insignias para el usuario %s tras guardar progreso.",
            instance.usuario_id,
            exc_info=True,
        )


@receiver(user_logged_in)
def manejar_inicio_sesion(sender, request, user, **kwargs):
    """
    Actualiza la racha de días consecutivos cuando un usuario inicia sesión.

    Se conecta a la señal `user_logged_in` de Django (disparada también por
    los flujos de autenticación de allauth). Delega en `actualizar_racha`.

    Args:
        sender: clase que emitió la señal.
        request: objeto `HttpRequest` de la petición que originó el login.
        user: instancia de `UsuarioCustom` que inició sesión.
        **kwargs: argumentos adicionales de la señal `user_logged_in`.
    """
    try:
        actualizar_racha(user)
    except Exception:
        logger.error(
            "Error al actualizar la racha para el usuario %s al iniciar sesión.",
            user.pk,
            exc_info=True,
        )
