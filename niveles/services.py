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

from .models import Nivel, MisionVocabulario, ProgresoEstudiante, ProgresoNivel
from avatar.reactions import obtener_reaccion
from estadisticas.models import RegistroActividad
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

# Recompensas de primera vez según estrellas obtenidas (estrellas → monedas).
# Definir aquí para poder ajustar sin tocar lógica dispersa.
RECOMPENSA_PRIMERA_VEZ = {1: 25, 2: 50, 3: 100}

# Monedas fijas por repetir un nivel ya completado, independiente de las estrellas.
RECOMPENSA_REPETICION = 3


def score_a_estrellas(score, es_principiante=False):
    """
    Convierte el score de Azure Speech (0-100) a 1, 2 o 3 estrellas.

    Punto de conversión único para que la lógica de estrellas no quede dispersa.
    `es_principiante` está reservado para una curva más generosa en el futuro.
    """
    if score >= 85:
        return 3
    elif score >= UMBRAL_SUPERACION_NIVEL:
        return 2
    return 1


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
    puntos del nivel, se avanza al siguiente nivel disponible (si existe) y
    se actualiza `ProgresoNivel.mejores_estrellas` (para el mapa) si el
    resultado de este intento superó el mejor anterior.

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

    # Un nivel está ya completado si existe un ProgresoNivel previo para él.
    ya_completado = ProgresoNivel.objects.filter(progreso=progreso, nivel=nivel).exists()

    score_global = resultado_evaluacion.get('score_global', 0)
    avanzo_de_nivel = False

    if score_global >= UMBRAL_SUPERACION_NIVEL:
        progreso.puntos_acumulados += nivel.puntos_recompensa

        # Guardamos el mejor resultado en estrellas de este nivel (para el
        # mapa), sin afectar las monedas: si ya tenía un resultado mejor en
        # un intento anterior, no se baja al repetir con peor puntaje.
        estrellas_obtenidas = score_a_estrellas(score_global)
        progreso_nivel, _creado_pn = ProgresoNivel.objects.get_or_create(progreso=progreso, nivel=nivel)
        if estrellas_obtenidas > progreso_nivel.mejores_estrellas:
            progreso_nivel.mejores_estrellas = estrellas_obtenidas
            progreso_nivel.save()

        # Avanzamos dentro de la misma zona (orden_en_zona siguiente).
        # nivel_actual queda apuntando al nivel recién completado (cosmético).
        siguiente_en_zona = Nivel.objects.filter(
            zona=nivel.zona,
            orden_en_zona=nivel.orden_en_zona + 1,
        ).first()
        if siguiente_en_zona and not ya_completado:
            avanzo_de_nivel = True

        progreso.nivel_actual = nivel
        progreso.save()

    return progreso, avanzo_de_nivel, ya_completado


def calcular_recompensas(usuario, score, ya_completado=False):
    """
    Calcula y otorga las recompensas (monedas) según si el nivel es primera vez o repetición.

    - Primera vez (ya_completado=False) y score >= UMBRAL: monedas según RECOMPENSA_PRIMERA_VEZ
      por las estrellas obtenidas (1/2/3).
    - Repetición (ya_completado=True) y score > 0: RECOMPENSA_REPETICION fija, sin importar
      las estrellas del intento actual.
    - Intento fallido sin completar por primera vez: 0 monedas.

    Args:
        usuario: instancia de `UsuarioCustom` (estudiante autenticado).
        score (float): puntaje global obtenido en la evaluación de pronunciación.
        ya_completado (bool): True si el nivel ya había sido superado anteriormente.

    Returns:
        dict: `monedas_ganadas` (int) y `monedas_totales` (int).
    """
    monedas_ganadas = 0
    monedas_totales = usuario.monedas

    if ya_completado and score > 0:
        monedas_ganadas = RECOMPENSA_REPETICION
        monedas_totales = otorgar_monedas(usuario, monedas_ganadas, concepto='nivel_repeticion')
    elif not ya_completado and score >= UMBRAL_SUPERACION_NIVEL:
        estrellas = score_a_estrellas(score)
        monedas_ganadas = RECOMPENSA_PRIMERA_VEZ.get(estrellas, 25)
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
        'dificultad': 'facil',
        'emoji': '🌳',
    },
    {
        'clave': Nivel.ZONA_MONTANA,
        'nombre': 'Montaña de las Letras',
        'descripcion': 'Consonantes y combinaciones',
        'dificultad': 'facil',
        'emoji': '⛰️',
    },
    {
        'clave': Nivel.ZONA_VALLE,
        'nombre': 'Valle de las Sílabas',
        'descripcion': 'Sílabas y ritmo',
        'dificultad': 'medio',
        'emoji': '🌾',
    },
    {
        'clave': Nivel.ZONA_CASTILLO,
        'nombre': 'Castillo de las Palabras',
        'descripcion': 'Palabras completas',
        'dificultad': 'medio',
        'emoji': '🏰',
    },
    {
        'clave': Nivel.ZONA_REINO,
        'nombre': 'Reino de la Lectura',
        'descripcion': 'Frases y comprensión',
        'dificultad': 'dificil',
        'emoji': '📖',
    },
]


# Posiciones X para cada índice de nivel dentro de una zona (serpentina izq↔der).
_X_POSICIONES = [295, 78, 205, 318, 72]

# Emojis de escenario por zona, usados solo como decoración de fondo del mapa.
_DECORACIONES_POR_ZONA = {
    'bosque_encantado': ['🌲', '🦋', '🌸', '🍄'],
    'montana_letras': ['⛰️', '❄️', '🪨', '🦅'],
    'valle_silabas': ['🌾', '🌻', '🐝', '🌼'],
    'castillo_palabras': ['🏰', '🚩', '🦢', '✨'],
    'reino_lectura': ['📖', '🕊️', '✨', '🌟'],
}

# Subconjunto de los emojis anteriores que "vuelan": reciben animación de
# flotación/deriva en vez de quedar estáticos como el resto del escenario.
_EMOJIS_VOLADORES = {'🦋', '🦅', '🐝', '🦢', '✨', '🌟', '🕊️', '❄️'}

# Ilustraciones reales (SVG en static/images/<zona_clave>/) para las zonas que
# ya cuentan con arte propio. Si una zona aparece aquí, sus decoraciones usan
# estas imágenes en vez de los emojis de _DECORACIONES_POR_ZONA.
# 'ancho'/'alto' son el tamaño de despliegue en px (no el nativo del archivo).
# 'tipo' decide la posición/capa (suelo y personaje quedan apoyados en el
# camino con sombra; vuelo flota cerca del borde, sin sombra de apoyo).
# 'anim' selecciona la microanimación CSS (ver niveles.html): sway (balanceo
# de árbol), bob (vaivén floral), pulso (brillo leve), idle (parpadeo de
# personaje posado), vuelo/vuelo-hada (flotación + aleteo), quieto (sin animar).
# El orden de la lista intercala suelo/personaje/vuelo a propósito, para que
# al rotar por ella las criaturas que vuelan aparezcan repartidas entre la
# vegetación en vez de quedar todas juntas.
_ILUSTRACIONES_POR_ZONA = {
    'bosque_encantado': [
        {'archivo': 'arbol.svg', 'ancho': 92, 'alto': 95, 'tipo': 'suelo', 'anim': 'sway'},
        {'archivo': 'mariposa.svg', 'ancho': 34, 'alto': 34, 'tipo': 'vuelo', 'anim': 'vuelo'},
        {'archivo': 'flores.svg', 'ancho': 130, 'alto': 82, 'tipo': 'suelo', 'anim': 'bob'},
        {'archivo': 'hada.svg', 'ancho': 46, 'alto': 34, 'tipo': 'vuelo', 'anim': 'vuelo-hada'},
        {'archivo': 'piedras.svg', 'ancho': 100, 'alto': 80, 'tipo': 'suelo', 'anim': 'quieto'},
        {'archivo': 'buho.svg', 'ancho': 56, 'alto': 64, 'tipo': 'personaje', 'anim': 'idle'},
        {'archivo': 'casa.svg', 'ancho': 112, 'alto': 108, 'tipo': 'suelo', 'anim': 'quieto'},
        {'archivo': 'hongo.svg', 'ancho': 70, 'alto': 58, 'tipo': 'suelo', 'anim': 'pulso'},
    ],
}

# Duración base (segundos) de cada microanimación. 0 = sin animar (estático).
_DURACION_ANIM = {
    'sway': 7.0,
    'bob': 4.0,
    'pulso': 3.2,
    'idle': 5.0,
    'vuelo': 4.5,
    'vuelo-hada': 4.0,
    'quieto': 0,
}

# Razón áurea: usada para generar una secuencia determinística de baja
# discrepancia (siempre el mismo resultado para el mismo índice, pero sin
# patrón visible) que separa el desfase de animación, la escala y la
# opacidad de cada decoración — así ninguna se ve sincronizada o "clonada".
_FASE_AUREA = 0.6180339887


def _fase_determinista(indice, semilla=_FASE_AUREA):
    """Devuelve un valor en [0, 1) determinista pero sin patrón aparente."""
    return (indice * semilla) % 1


def _calcular_posiciones_zona(num_niveles):
    """
    Calcula la geometría del camino SVG para una zona según su cantidad de niveles.

    Returns:
        dict con canvas_height (int, px), polyline_points (str para SVG),
        posiciones (list de dicts {x, y}), y estrellas (list de dicts {x, y}
        con las posiciones intermedias para las decoraciones del camino).
    """
    espacio_por_nivel = 120   # px entre filas de niveles
    padding_top = 100         # espacio para el ribbon de zona
    padding_bottom = 60

    canvas_height = num_niveles * espacio_por_nivel + padding_top + padding_bottom

    posiciones = []
    for i in range(num_niveles):
        x = _X_POSICIONES[i % len(_X_POSICIONES)]
        y = canvas_height - padding_bottom - i * espacio_por_nivel
        posiciones.append({'x': x, 'y': y})

    polyline_points = ' '.join(f"{p['x']},{p['y']}" for p in posiciones)

    estrellas = []
    for i in range(len(posiciones) - 1):
        estrellas.append({
            'x': (posiciones[i]['x'] + posiciones[i + 1]['x']) // 2,
            'y': (posiciones[i]['y'] + posiciones[i + 1]['y']) // 2,
        })

    return {
        'canvas_height': canvas_height,
        'polyline_points': polyline_points,
        'posiciones': posiciones,
        'estrellas': estrellas,
    }


def obtener_mapa_unico(zonas):
    """
    Toma la lista devuelta por obtener_mapa_aventura() y calcula la geometría
    de UN ÚNICO canvas continuo con todos los niveles de todas las zonas.

    Returns:
        dict con canvas_height (int, px — el CSS lo usa también como
        relación de aspecto para escalar el mapa de forma responsiva sin
        distorsión), polyline_points (str para el SVG), estrellas (list de
        {x,y} en midpoints), ribbons (list de {zona_clave, zona_nombre,
        desbloqueada, y}), decoraciones (list de {x, y, tipo: 'suelo'|
        'vuelo'|'personaje', anim, escala, opacidad, duracion, delay} de
        escenario por zona, con 'emoji' o, para zonas con arte propio,
        'imagen' + 'ancho' + 'alto'), nubes (list de {x, y, variante} para
        la capa de fondo animada), y niveles (list plana de todos los
        niveles con {x, y, float_delay, zona_clave, zona_nombre,
        zona_desbloqueada} + los campos originales del nivel).
    """
    ESPACIO_POR_NIVEL = 125
    PADDING_TOP = 80
    PADDING_BOTTOM = 100
    X_POSICIONES = [295, 75, 205, 318, 72]

    niveles_planos = []
    primer_indice_por_zona = []
    for zona in zonas:
        primer_indice_por_zona.append(len(niveles_planos))
        for nv in zona['niveles']:
            entrada = dict(nv)
            entrada['zona_clave'] = zona['clave']
            entrada['zona_nombre'] = zona['nombre']
            entrada['zona_desbloqueada'] = zona['desbloqueada']
            niveles_planos.append(entrada)

    total = len(niveles_planos)
    canvas_height = max(total * ESPACIO_POR_NIVEL + PADDING_TOP + PADDING_BOTTOM, 400)

    for i, nv in enumerate(niveles_planos):
        nv['x'] = X_POSICIONES[i % len(X_POSICIONES)]
        nv['y'] = canvas_height - PADDING_BOTTOM - i * ESPACIO_POR_NIVEL
        # Desfase para la flotación sutil de los nodos completado/bloqueado
        # (ver .lvl-completado/.lvl-bloqueado en niveles.html): evita que
        # todos los nodos suban y bajen exactamente al mismo tiempo.
        nv['float_delay'] = round(_fase_determinista(i) * 4.5, 2)

    polyline_points = ' '.join(f"{nv['x']},{nv['y']}" for nv in niveles_planos)

    estrellas = []
    for i in range(len(niveles_planos) - 1):
        estrellas.append({
            'x': (niveles_planos[i]['x'] + niveles_planos[i + 1]['x']) // 2,
            'y': (niveles_planos[i]['y'] + niveles_planos[i + 1]['y']) // 2,
        })

    # Ribbon de cada zona: justo debajo del primer (más antiguo) nivel de la zona.
    ribbons = []
    for zona_idx, zona in enumerate(zonas):
        idx = primer_indice_por_zona[zona_idx]
        oldest_y = canvas_height - PADDING_BOTTOM - idx * ESPACIO_POR_NIVEL
        ribbons.append({
            'zona_clave': zona['clave'],
            'zona_nombre': zona['nombre'],
            'dificultad': zona.get('dificultad', 'facil'),
            'emoji': zona.get('emoji', '⭐'),
            'desbloqueada': zona['desbloqueada'],
            'y': oldest_y + 52,
        })

    # Decoraciones de escenario: una cada dos niveles, en el borde opuesto al
    # nodo (puramente visual, no afecta la lógica del camino). Si la zona
    # tiene ilustraciones reales (_ILUSTRACIONES_POR_ZONA) se usan esas;
    # si no, se cae a los emojis de _DECORACIONES_POR_ZONA (donde los
    # marcados como _EMOJIS_VOLADORES reciben animación de vuelo/deriva y
    # el resto queda fijo como elemento de fondo).
    # Contador independiente del índice de nivel: como solo se decora uno de
    # cada dos niveles (i impar), usar `i % len(lista)` directamente dejaría
    # siempre el mismo resto y la mitad de las imágenes/emojis de cada zona
    # jamás se mostraría. Este contador sí rota por todas. La misma fase
    # determinista que elige la imagen también fija su escala, opacidad y
    # desfase de animación, para que ninguna decoración se vea "clonada" ni
    # sincronizada con las demás.
    decoraciones = []
    contador = 0
    for i, nv in enumerate(niveles_planos):
        if i % 2 == 0:
            continue

        fase = _fase_determinista(contador)
        escala = round(0.92 + fase * 0.18, 3)
        opacidad = round(0.86 + _fase_determinista(contador, 0.3819660113) * 0.14, 3)

        ilustraciones = _ILUSTRACIONES_POR_ZONA.get(nv['zona_clave'])
        if ilustraciones:
            item = ilustraciones[contador % len(ilustraciones)]
            es_vuelo = item['tipo'] == 'vuelo'
            duracion = _DURACION_ANIM.get(item['anim'], 0)
            decoraciones.append({
                'x': (28 if nv['x'] > 195 else 362) if es_vuelo else (58 if nv['x'] > 195 else 332),
                'y': (nv['y'] - 35) if es_vuelo else (nv['y'] - 30),
                'imagen': f"{nv['zona_clave']}/{item['archivo']}",
                'ancho': item['ancho'],
                'alto': item['alto'],
                'tipo': item['tipo'],
                'anim': item['anim'],
                'escala': escala,
                'opacidad': opacidad,
                'duracion': duracion,
                'delay': round(fase * duracion, 2),
            })
            contador += 1
            continue

        emojis = _DECORACIONES_POR_ZONA.get(nv['zona_clave'], ['✨'])
        emoji = emojis[contador % len(emojis)]
        es_vuelo = emoji in _EMOJIS_VOLADORES
        anim = 'vuelo' if es_vuelo else 'quieto'
        duracion = _DURACION_ANIM.get(anim, 0)
        decoraciones.append({
            'x': 28 if nv['x'] > 195 else 362,
            'y': nv['y'] - 35,
            'emoji': emoji,
            'tipo': 'vuelo' if es_vuelo else 'suelo',
            'anim': anim,
            'escala': escala,
            'opacidad': opacidad,
            'duracion': duracion,
            'delay': round(fase * duracion, 2),
        })
        contador += 1

    # Nubes decorativas: distribuidas uniformemente en altura, alternando de
    # lado, cada una con su propia variante de tamaño/velocidad (CSS) para
    # que no se muevan todas en sincronía. Capa más profunda del mapa.
    nubes = []
    num_nubes = max(canvas_height // 280, 2)
    paso_y = canvas_height / num_nubes
    for i in range(num_nubes):
        nubes.append({
            'x': 70 if i % 2 == 0 else 250,
            'y': int(paso_y * i + paso_y / 2),
            'variante': i % 3,
        })

    return {
        'canvas_height': canvas_height,
        'polyline_points': polyline_points,
        'estrellas': estrellas,
        'ribbons': ribbons,
        'decoraciones': decoraciones,
        'nubes': nubes,
        'niveles': niveles_planos,
    }


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
            `titulo`, `orden_en_zona`, `narrativa_intro`, `estado`, `frase_historia`,
            `palabra_objetivo` — estos últimos permiten repetir niveles completados
            — y `mejores_estrellas`, 1 a 3 para niveles completados, según el
            mejor resultado histórico en `ProgresoNivel`; 3 si el nivel está
            completado pero no hay registro guardado, por ejemplo datos de
            antes de que existiera este seguimiento).
    """
    progreso, _creado = ProgresoEstudiante.objects.get_or_create(usuario=usuario)

    niveles_por_zona = {}
    for nivel in Nivel.objects.all().order_by('zona', 'orden_en_zona', 'numero'):
        niveles_por_zona.setdefault(nivel.zona, []).append(nivel)

    # Primera misión por nivel (en una sola query) para habilitar repetición.
    primera_mision_por_nivel = {}
    for mision in MisionVocabulario.objects.order_by('nivel_id', 'id'):
        if mision.nivel_id not in primera_mision_por_nivel:
            primera_mision_por_nivel[mision.nivel_id] = mision

    # IDs de niveles completados (con ProgresoNivel) y sus mejores estrellas.
    completados_map = dict(
        ProgresoNivel.objects.filter(progreso=progreso).values_list('nivel_id', 'mejores_estrellas')
    )

    zonas = []
    for zona_info in ZONAS_MAPA_AVENTURA:
        niveles_zona = []
        # El primer nivel sin completar en la zona es el 'actual'.
        # El nivel 1 de cada zona (orden_en_zona=1) siempre está desbloqueado.
        nivel_actual_zona_marcado = False

        for nivel in niveles_por_zona.get(zona_info['clave'], []):
            if nivel.id in completados_map:
                estado = 'completado'
            elif not nivel_actual_zona_marcado:
                estado = 'actual'
                nivel_actual_zona_marcado = True
            else:
                estado = 'bloqueado'

            mision = primera_mision_por_nivel.get(nivel.id)
            niveles_zona.append({
                'numero': nivel.numero,
                'titulo': nivel.titulo,
                'orden_en_zona': nivel.orden_en_zona,
                'narrativa_intro': nivel.narrativa_intro,
                'estado': estado,
                'frase_historia': mision.frase_historia if mision else '',
                'palabra_objetivo': mision.palabra_objetivo if mision else '',
                'mejores_estrellas': completados_map.get(nivel.id, 3) if estado == 'completado' else 0,
            })

        # Todas las zonas siempre desbloqueadas (nivel 1 de cada zona accesible).
        desbloqueada = True

        # Geometría del camino SVG (coordenadas de nodos y puntos del polyline).
        geo = _calcular_posiciones_zona(len(niveles_zona)) if niveles_zona else {
            'canvas_height': 220,
            'polyline_points': '',
            'posiciones': [],
            'estrellas': [],
        }
        for i, nodo in enumerate(niveles_zona):
            nodo['x'] = geo['posiciones'][i]['x']
            nodo['y'] = geo['posiciones'][i]['y']

        zonas.append({
            'clave': zona_info['clave'],
            'nombre': zona_info['nombre'],
            'descripcion': zona_info['descripcion'],
            'dificultad': zona_info['dificultad'],
            'emoji': zona_info['emoji'],
            'desbloqueada': desbloqueada,
            'canvas_height': geo['canvas_height'],
            'polyline_points': geo['polyline_points'],
            'estrellas': geo['estrellas'],
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

        progreso, avanzo_de_nivel, ya_completado = guardar_progreso_estudiante(usuario, nivel_id, resultado_azure)
        recompensas = calcular_recompensas(usuario, resultado_azure['score_global'], ya_completado)
        reaccion_avatar = construir_reaccion_avatar(resultado_azure['score_global'], avanzo_de_nivel)

        zona_nivel = Nivel.objects.filter(numero=nivel_id).values_list('zona', flat=True).first() or ''
        RegistroActividad.objects.registrar(
            usuario, RegistroActividad.TIPO_NIVEL, resultado_azure['score_global'], zona=zona_nivel,
        )

        return {
            'status': 'success',
            'score': resultado_azure['score_global'],
            'score_exactitud': resultado_azure.get('score_exactitud'),
            'palabras': resultado_azure.get('palabras', []),
            'avanzo_de_nivel': avanzo_de_nivel,
            'monedas_ganadas': recompensas['monedas_ganadas'],
            'monedas_totales': recompensas['monedas_totales'],
            'reaccion_avatar': reaccion_avatar,
            'estrellas': score_a_estrellas(resultado_azure['score_global']),
        }
    except Exception:
        logger.error("Error inesperado al procesar el intento de nivel", exc_info=True)
        raise
    finally:
        if ruta_audio_temporal and os.path.exists(ruta_audio_temporal):
            os.remove(ruta_audio_temporal)
