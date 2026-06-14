"""
Capa de servicios del módulo `recompensas`.

Contiene la lógica de negocio del sistema de recompensas unificado:
otorgamiento de monedas, verificación de insignias, gestión de la racha
diaria y consulta del evento especial activo.

Las vistas y los signals deben delegar siempre en estas funciones para que
el sistema de recompensas sea consistente y validado en el servidor.
"""

import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import EventoEspecial, Insignia, TipoInsignia

logger = logging.getLogger(__name__)


class SaldoInsuficienteError(Exception):
    """Se lanza cuando un usuario no tiene suficientes monedas para una compra."""
    pass


def otorgar_monedas(usuario, cantidad, concepto):
    """
    Otorga (o resta) monedas a un usuario de forma atómica.

    Actualiza `UsuarioCustom.monedas` usando una expresión `F()` dentro de
    una transacción atómica, evitando condiciones de carrera cuando varias
    operaciones intentan modificar el saldo del mismo usuario al mismo tiempo.

    Args:
        usuario: instancia de `UsuarioCustom` a la que se otorgan las monedas.
        cantidad (int): cantidad de monedas a otorgar (puede ser negativa
            para descontar monedas, por ejemplo al comprar un ítem).
        concepto (str): descripción breve del motivo del movimiento, usada
            únicamente para el registro en el log.

    Returns:
        int: saldo de monedas actualizado del usuario.
    """
    UsuarioCustom = usuario.__class__

    with transaction.atomic():
        # select_for_update bloquea la fila del usuario hasta el final de la
        # transacción para evitar lecturas/escrituras concurrentes inconsistentes.
        usuario_actualizado = UsuarioCustom.objects.select_for_update().get(pk=usuario.pk)
        usuario_actualizado.monedas = F('monedas') + cantidad
        usuario_actualizado.save(update_fields=['monedas'])
        usuario_actualizado.refresh_from_db(fields=['monedas'])

    # Reflejamos el nuevo saldo en la instancia recibida para que el
    # llamador no necesite recargarla manualmente.
    usuario.monedas = usuario_actualizado.monedas

    logger.info(
        "Movimiento de monedas: usuario=%s cantidad=%s concepto=%s saldo_final=%s",
        usuario.pk, cantidad, concepto, usuario_actualizado.monedas,
    )

    return usuario_actualizado.monedas


def cobrar_monedas(usuario, cantidad, concepto):
    """
    Descuenta monedas a un usuario de forma atómica, validando saldo.

    Bloquea la fila del usuario con `select_for_update` dentro de una
    transacción atómica, verifica que `usuario.monedas >= cantidad` y, si
    es así, descuenta `cantidad` usando una expresión `F()` para evitar
    condiciones de carrera. Si el saldo es insuficiente, no modifica nada
    y lanza `SaldoInsuficienteError`.

    Args:
        usuario: instancia de `UsuarioCustom` al que se le cobran monedas.
        cantidad (int): cantidad de monedas a descontar (debe ser positiva).
        concepto (str): descripción breve del motivo del cobro, usada
            únicamente para el registro en el log.

    Returns:
        int: saldo de monedas actualizado del usuario tras el cobro.

    Raises:
        SaldoInsuficienteError: si el usuario no tiene monedas suficientes.
    """
    UsuarioCustom = usuario.__class__

    with transaction.atomic():
        # select_for_update bloquea la fila del usuario hasta el final de la
        # transacción para evitar lecturas/escrituras concurrentes inconsistentes.
        usuario_actualizado = UsuarioCustom.objects.select_for_update().get(pk=usuario.pk)

        if usuario_actualizado.monedas < cantidad:
            logger.info(
                "Cobro rechazado por saldo insuficiente: usuario=%s cantidad=%s "
                "concepto=%s saldo_actual=%s",
                usuario.pk, cantidad, concepto, usuario_actualizado.monedas,
            )
            raise SaldoInsuficienteError(
                f"Saldo insuficiente para el usuario {usuario.pk}"
            )

        usuario_actualizado.monedas = F('monedas') - cantidad
        usuario_actualizado.save(update_fields=['monedas'])
        usuario_actualizado.refresh_from_db(fields=['monedas'])

    # Reflejamos el nuevo saldo en la instancia recibida para que el
    # llamador no necesite recargarla manualmente.
    usuario.monedas = usuario_actualizado.monedas

    logger.info(
        "Cobro de monedas: usuario=%s cantidad=%s concepto=%s saldo_final=%s",
        usuario.pk, cantidad, concepto, usuario_actualizado.monedas,
    )

    return usuario_actualizado.monedas


def verificar_y_otorgar_insignias(usuario):
    """
    Evalúa los criterios de todos los `TipoInsignia` y otorga las insignias
    nuevas que el usuario haya alcanzado.

    Recorre los tipos de insignia definidos en el sistema y, para cada uno
    que el usuario aún no posea, evalúa su criterio (`primer_nivel`,
    `racha_7`, `palabras_100`, etc.) contra el progreso actual del usuario.
    Si el criterio se cumple, crea un registro `Insignia` con `mostrada=False`.

    Importante: esta función NO debe llamar `.save()` sobre
    `ProgresoEstudiante` ni sobre `UsuarioCustom` para evitar disparar de
    nuevo el signal `post_save` y entrar en recursión.

    Args:
        usuario: instancia de `UsuarioCustom` cuyo progreso se evalúa.

    Returns:
        list[Insignia]: lista de las insignias nuevas otorgadas (puede
            estar vacía si no se cumplió ningún criterio nuevo).
    """
    # Import local para evitar dependencias circulares entre apps al cargarse.
    from niveles.models import ProgresoEstudiante

    try:
        progreso = ProgresoEstudiante.objects.get(usuario=usuario)
    except ProgresoEstudiante.DoesNotExist:
        logger.info("Usuario %s sin progreso registrado; no se evalúan insignias.", usuario.pk)
        return []

    # Insignias que el usuario ya posee, para no duplicar.
    tipos_obtenidos = set(
        Insignia.objects.filter(usuario=usuario).values_list('tipo_insignia_id', flat=True)
    )

    insignias_nuevas = []

    for tipo in TipoInsignia.objects.exclude(pk__in=tipos_obtenidos):
        criterio_cumplido = False

        if tipo.criterio == 'primer_nivel':
            criterio_cumplido = progreso.nivel_actual is not None and progreso.nivel_actual.numero >= 2

        elif tipo.criterio == 'nivel_5':
            criterio_cumplido = progreso.nivel_actual is not None and progreso.nivel_actual.numero >= 5

        elif tipo.criterio == 'nivel_10':
            criterio_cumplido = progreso.nivel_actual is not None and progreso.nivel_actual.numero >= 10

        elif tipo.criterio == 'palabras_100':
            criterio_cumplido = progreso.puntos_acumulados >= tipo.valor_umbral

        elif tipo.criterio in ('racha_7', 'racha_30'):
            criterio_cumplido = usuario.racha_dias >= tipo.valor_umbral

        elif tipo.criterio == 'historias_10':
            # El módulo de historias todavía no expone un contador; se deja
            # preparado para cuando dicho módulo registre el progreso.
            criterio_cumplido = False

        elif tipo.criterio == 'desafio_diario':
            # Import local para evitar dependencias circulares: `desafio`
            # depende de `recompensas` a nivel de modelos.
            from desafio.models import ProgresoDesafio
            criterio_cumplido = ProgresoDesafio.objects.filter(usuario=usuario, completado=True).exists()

        if criterio_cumplido:
            insignia = Insignia.objects.create(usuario=usuario, tipo_insignia=tipo, mostrada=False)
            insignias_nuevas.append(insignia)
            logger.info(
                "Insignia otorgada: usuario=%s tipo_insignia=%s", usuario.pk, tipo.criterio,
            )

    return insignias_nuevas


def obtener_insignias_pendientes(usuario):
    """
    Obtiene las insignias no mostradas de un usuario y las marca como mostradas.

    Pensada para ser usada explícitamente desde una vista (por ejemplo, un
    endpoint que la UI consulta para disparar la animación de desbloqueo).
    No debe llamarse desde el context processor, ya que este se ejecuta en
    cada request y marcaría las insignias como mostradas antes de que el
    usuario llegue a verlas.

    Args:
        usuario: instancia de `UsuarioCustom` cuyas insignias pendientes se consultan.

    Returns:
        list[Insignia]: insignias que estaban pendientes de mostrar (ya
            actualizadas con `mostrada=True` en la base de datos).
    """
    pendientes = list(
        Insignia.objects.filter(usuario=usuario, mostrada=False).select_related('tipo_insignia')
    )

    if pendientes:
        ids_pendientes = [insignia.pk for insignia in pendientes]
        Insignia.objects.filter(pk__in=ids_pendientes).update(mostrada=True)
        logger.info(
            "Insignias marcadas como mostradas: usuario=%s cantidad=%s",
            usuario.pk, len(ids_pendientes),
        )

    return pendientes


def actualizar_racha(usuario):
    """
    Actualiza la racha de días consecutivos de conexión de un usuario.

    Compara `ultima_fecha_conexion` con la fecha actual:
    - Si nunca se registró una conexión, inicia la racha en 1.
    - Si la última conexión fue ayer, incrementa `racha_dias` en 1.
    - Si la última conexión fue hoy, no modifica la racha (ya contabilizada).
    - Si la última conexión fue hace más de un día, reinicia `racha_dias` a 1.

    En todos los casos (excepto cuando ya se registró hoy) actualiza
    `ultima_fecha_conexion` a la fecha actual y persiste los cambios.

    Args:
        usuario: instancia de `UsuarioCustom` que inició sesión.

    Returns:
        bool: `True` si la racha o la fecha de conexión cambiaron, `False`
            si no hubo cambios (el usuario ya se había conectado hoy).
    """
    hoy = timezone.localdate()
    ultima_conexion = usuario.ultima_fecha_conexion

    if ultima_conexion == hoy:
        # Ya se registró la conexión de hoy, no hay nada que actualizar.
        return False

    if ultima_conexion == hoy - timedelta(days=1):
        usuario.racha_dias += 1
    else:
        usuario.racha_dias = 1

    usuario.ultima_fecha_conexion = hoy
    usuario.save(update_fields=['racha_dias', 'ultima_fecha_conexion'])

    logger.info(
        "Racha actualizada: usuario=%s racha_dias=%s ultima_fecha_conexion=%s",
        usuario.pk, usuario.racha_dias, usuario.ultima_fecha_conexion,
    )

    return True


def get_evento_activo():
    """
    Obtiene el evento especial actualmente activo, si existe.

    Un evento se considera activo si su bandera `activo` está en `True` y
    la fecha actual está dentro del rango `fecha_inicio`/`fecha_fin`.

    Returns:
        EventoEspecial | None: el primer evento especial activo encontrado,
            o `None` si no hay ninguno vigente.
    """
    hoy = timezone.localdate()

    try:
        return EventoEspecial.objects.filter(
            activo=True,
            fecha_inicio__lte=hoy,
            fecha_fin__gte=hoy,
        ).first()
    except EventoEspecial.DoesNotExist:
        return None
