"""Catálogo declarativo de qué modelo administra el panel y cómo.

Cada `RecursoPanel` describe un modelo administrable: en qué grupo del
sidebar aparece, qué campos se muestran en la lista, y si es de solo
lectura (logs/históricos) o singleton (un único registro, sin lista).

Las vistas genéricas (`panel_admin/views.py`) leen este registro para
servir Lista/Crear/Editar/Eliminar sin necesitar una vista por modelo.

Avatar no está acá: tiene pantallas a medida (Fase 2, previsualización en
vivo) en vez del CRUD genérico — ver doc/PANEL_ADMIN.md.

Lo que NO se incluye a propósito: modelos que son datos de progreso/estado
de un estudiante (Insignia, MascotaUsuario, ColeccionableUsuario,
ProgresoDesafio, ProgresoEstudiante, ProgresoNivel, ProgresoHistoria,
HistoriaGenerada y sus hijos). Esos no son "contenido" que un administrador
edite a mano, son el historial real de cada usuario.
"""

from dataclasses import dataclass, field

from avatar.models import CaraAvatar, Item
from camara_inteligente.models import ConfiguracionCamara, FraseTemplate
from desafio.models import ConfiguracionDesafio, DesafioDiario
from estadisticas.models import RegistroActividad
from historias.models import FragmentoHistoria, Historia, OpcionRespuesta
from niveles.models import MisionVocabulario, Nivel, Zona
from recompensas.models import Coleccionable, EventoEspecial, Mascota, TipoInsignia
from reportes.models import ReporteEnviado


@dataclass
class RecursoPanel:
    slug: str
    modelo: type
    grupo: str
    icono: str
    nombre_plural: str
    campos_lista: list = field(default_factory=list)
    campos_form: list | None = None  # None = todos los campos editables del modelo
    singleton: bool = False          # un único registro (pk=1), sin lista ni alta/baja
    solo_lectura: bool = False       # log/histórico: sin crear/editar/borrar
    template_form: str = 'panel_admin/recurso_form.html'  # override para pantallas a medida (Avatar)


REGISTRO = [
    # --- Avatar (Fase 2: pantallas a medida con previsualización en vivo) ---
    RecursoPanel('items-avatar', Item, 'Avatar', '👕', 'Ítems de avatar',
                 ['nombre', 'categoria', 'activo', 'precio_monedas'],
                 template_form='panel_admin/avatar_item_form.html'),
    RecursoPanel('caras-avatar', CaraAvatar, 'Avatar', '😊', 'Caras del avatar',
                 ['estado'],
                 template_form='panel_admin/avatar_cara_form.html'),

    # --- Recompensas ---
    RecursoPanel('insignias-tipo', TipoInsignia, 'Recompensas', '🏅', 'Tipos de insignia',
                 ['nombre', 'criterio', 'valor_umbral']),
    RecursoPanel('mascotas', Mascota, 'Recompensas', '🐉', 'Mascotas',
                 ['nombre', 'especie', 'precio_monedas']),
    RecursoPanel('coleccionables', Coleccionable, 'Recompensas', '🎴', 'Coleccionables',
                 ['nombre', 'tipo', 'precio_monedas']),
    RecursoPanel('eventos-especiales', EventoEspecial, 'Recompensas', '🎉', 'Eventos especiales',
                 ['nombre', 'tipo', 'fecha_inicio', 'fecha_fin', 'activo']),

    # --- Desafío diario ---
    RecursoPanel('config-desafio', ConfiguracionDesafio, 'Desafío diario', '⚙️', 'Configuración',
                 ['zona_activa', 'palabras_meta_hoy', 'recompensa_monedas_base'], singleton=True),
    RecursoPanel('desafios-diarios', DesafioDiario, 'Desafío diario', '🔥', 'Desafíos diarios',
                 ['fecha', 'recompensa_monedas', 'recompensa_coleccionable']),

    # --- Cámara inteligente ---
    RecursoPanel('frases-camara', FraseTemplate, 'Cámara', '📷', 'Frases plantilla',
                 ['objeto_keyword', 'nivel_dificultad', 'recompensa_monedas', 'creada_automaticamente']),
    RecursoPanel('config-camara', ConfiguracionCamara, 'Cámara', '⚙️', 'Configuración',
                 ['modo_economico'], singleton=True),

    # --- Niveles ---
    RecursoPanel('niveles', Nivel, 'Niveles', '🗺️', 'Niveles',
                 ['numero', 'titulo', 'zona', 'puntos_recompensa']),
    RecursoPanel('zonas', Zona, 'Niveles', '🏔️', 'Zonas',
                 ['nombre', 'clave', 'orden', 'cerrada']),
    RecursoPanel('misiones', MisionVocabulario, 'Niveles', '📝', 'Misiones de vocabulario',
                 ['palabra_objetivo', 'tipo', 'nivel']),

    # --- Historias ---
    RecursoPanel('historias', Historia, 'Historias', '📖', 'Historias',
                 ['titulo', 'nivel_dificultad', 'activa', 'orden']),
    RecursoPanel('fragmentos-historia', FragmentoHistoria, 'Historias', '📄', 'Fragmentos de historia',
                 ['historia', 'orden', 'tipo_respuesta']),
    RecursoPanel('opciones-respuesta', OpcionRespuesta, 'Historias', '🔀', 'Opciones de respuesta',
                 ['fragmento', 'texto', 'es_correcta']),

    # --- Solo lectura: logs/históricos ---
    RecursoPanel('registros-actividad', RegistroActividad, 'Estadísticas', '📊', 'Registros de actividad',
                 ['usuario', 'tipo_actividad', 'zona', 'score', 'fecha'], solo_lectura=True),
    RecursoPanel('reportes-enviados', ReporteEnviado, 'Reportes', '✉️', 'Reportes enviados',
                 ['usuario', 'correo_destino', 'tipo_envio', 'exitoso', 'fecha_envio'], solo_lectura=True),
]

REGISTRO_POR_SLUG = {recurso.slug: recurso for recurso in REGISTRO}


def grupos_para_sidebar():
    """Agrupa el registro por `grupo`, preservando el orden de declaración arriba."""
    grupos = {}
    for recurso in REGISTRO:
        grupos.setdefault(recurso.grupo, []).append(recurso)
    return grupos
