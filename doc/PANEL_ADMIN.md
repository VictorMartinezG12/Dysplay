# Panel de administración de DysPlay

Panel propio (mismo Tailwind/diseño infantil del resto de la app, no el
admin nativo de Django) para que Victor gestione contenido del sistema sin
tocar código: ítems del avatar, niveles, recompensas, historias, etc.

Construido por fases. Este documento se actualiza al cerrar cada fase.

## Por qué existe

Durante el rediseño del cuerpo del avatar (2026-06-21) se perdieron horas
ajustando a ojo, por shell y por archivo, por qué la ropa no calzaba con el
cuerpo. No había ningún lugar donde subir una prenda y ver de inmediato si
quedaba bien puesta. El panel resuelve eso para Avatar (Fase 2) y de paso le
da a Victor un único lugar para administrar el resto del sistema sin entrar
al admin nativo de Django ni editar la base de datos a mano.

## Decisiones de diseño

- **Panel propio, no el admin nativo de Django** (`/admin/` sigue
  existiendo y funcionando, no se tocó). El panel vive en `/panel/`.
- **Acceso**: se reutiliza el campo nativo `is_staff` de Django
  (`request.user.is_staff`) como "es administrador". No se creó ningún
  campo nuevo en `UsuarioCustom` — los campos `es_padre`/`es_profesor`/
  `es_estudiante` que ya existían ahí siguen sin uso y no están
  relacionados con este panel.
- Un usuario sin `is_staff=True` (incluyendo anónimo) recibe **404**, no un
  redirect a login ni un 403 — para no delatar que el panel existe.
- El link "Panel" en el nav principal (`templates/base.html`) solo se
  muestra si `user.is_staff` es verdadero.
- Arquitectura pensada para escalar a ~25 modelos sin repetir CRUD a mano:
  un "registro" declarativo (Fase 1) describirá qué modelo administrar y
  con qué campos, servido por vistas genéricas reutilizables. Solo Avatar
  (Fase 2) necesita pantallas a medida (previsualización en vivo).

## Estado por fase

| Fase | Contenido | Estado |
|---|---|---|
| 0 | Cimiento: app `panel_admin`, acceso por `is_staff`, layout con sidebar, link en el nav | **Completada** (2026-06-21) |
| 1 | CRUD genérico: Recompensas, Desafío diario, Cámara, Niveles, Historias; Estadísticas/Reportes de solo lectura | **Completada** (2026-06-22) |
| 2 | Avatar a medida: formulario de `Item` con previsualización en vivo (lienzo 500×500), modelo nuevo `CaraAvatar` (caras + parpadeo) | **Completada** (2026-06-22) |
| 3 | Permisos finos (si hace falta) + documentación final en `CLAUDE.md`/auditoría | **Completada** (2026-06-22) |

Plan completo original (las 4 fases con detalle de diseño, código de
ejemplo del registro, y criterios de verificación de cada fase): ver el
historial de conversación o pedir que se vuelva a generar — no se duplica
aquí para no desincronizarse; este archivo refleja **lo ya construido**, no
el plan a futuro.

## Fase 0 — qué se construyó

**App nueva**: `panel_admin/` (agregada a `INSTALLED_APPS` en
`core/settings.py`, montada en `core/urls.py` bajo `path('panel/', ...)`).

```
panel_admin/
  apps.py
  mixins.py               # StaffRequiredMixin: 404 si no es staff
  views.py                # PanelHomeView + MODULOS_PLANEADOS (lista estática
                           # de módulos para el sidebar/tarjetas; Fase 1 la
                           # reemplaza por panel_admin/registry.py)
  urls.py                 # app_name='panel_admin', name='home' -> /panel/
  context_processors.py   # modulos_panel: inyecta el sidebar en templates
                           # bajo /panel/ sin que cada vista lo repita
  templates/panel_admin/
    base_panel.html       # header propio (sin monedas/racha) + sidebar
    home.html              # tarjetas por módulo, todas "Próximamente"
  tests.py                 # 4 tests: 404 anónimo, 404 no-staff, 200 staff,
                            # link visible solo para staff en el nav
```

**Cambios en archivos existentes**:
- `core/settings.py`: `'panel_admin'` en `INSTALLED_APPS`;
  `panel_admin.context_processors.modulos_panel` en `TEMPLATES.context_processors`.
- `core/urls.py`: `path('panel/', include('panel_admin.urls'))`.
- `templates/base.html`: nuevo botón "Panel" en el nav, dentro de
  `{% if user.is_staff %}`, junto al botón de "Configuración" existente.

**Verificado** (ver memoria de sesión / este documento):
- `python manage.py test` completo: 297/297 OK.
- Navegador real (Playwright + Chrome del sistema): usuario `is_staff=True`
  ve el botón "Panel" y entra a `/panel/`; usuario normal no ve el botón y
  `/panel/` le responde 404.

## Fase 1 — qué se construyó

**Archivo nuevo clave**: `panel_admin/registry.py` — el catálogo declarativo
que reemplazó la lista estática `MODULOS_PLANEADOS` de la Fase 0. Cada
modelo administrable se declara una vez (`RecursoPanel`: slug, modelo,
grupo del sidebar, ícono, campos de la tabla, y dos flags — `singleton` y
`solo_lectura`).

**Vistas genéricas nuevas en `panel_admin/views.py`** (sirven a los ~16
modelos registrados sin código por modelo):
- `RecursoListView` — tabla con los `campos_lista` del registro. Si el
  recurso es `singleton`, redirige directo a editar el único registro
  (`get_or_create(pk=1)`) en vez de mostrar una lista de un solo elemento.
- `RecursoCreateView` / `RecursoUpdateView` — `ModelForm` generado con
  `modelform_factory(modelo, fields=campos_form or '__all__')`. Un
  `singleton` no puede "crearse" (404 explícito).
- `RecursoDeleteView` — confirmación simple antes de borrar. No disponible
  para `singleton` ni `solo_lectura`.

**Modelos registrados** (`panel_admin/registry.py`, `REGISTRO`):

| Grupo | Modelos | Notas |
|---|---|---|
| Recompensas | `TipoInsignia`, `Mascota`, `Coleccionable`, `EventoEspecial` | Catálogo. `Insignia`/`MascotaUsuario`/`ColeccionableUsuario` (progreso de usuario) quedan fuera a propósito |
| Desafío diario | `ConfiguracionDesafio` (singleton), `DesafioDiario` | `ProgresoDesafio` queda fuera (progreso de usuario) |
| Cámara | `FraseTemplate`, `ConfiguracionCamara` (singleton) | |
| Niveles | `Nivel`, `Zona`, `MisionVocabulario` | Ver nota sobre `NivelAdminForm` abajo |
| Historias | `Historia`, `FragmentoHistoria`, `OpcionRespuesta` | La generación de historias por IA (botón especial en `/admin/`) sigue solo en el admin nativo, no se portó |
| Estadísticas | `RegistroActividad` | Solo lectura (es un log) |
| Reportes | `ReporteEnviado` | Solo lectura (es un log) |

**Simplificación consciente**: `niveles/admin.py` tiene un
`NivelAdminForm` que oculta del selector las zonas marcadas `cerrada` al
crear un nivel (usabilidad). El panel usa el `ModelForm` genérico, que NO
oculta esas zonas en el desplegable — pero la protección real
(`Nivel.clean()`, que bloquea con un error si se intenta crear igual) sigue
activa porque vive en el modelo, no en el form. Si esto molesta en el uso
real, se puede agregar un `form_class` opcional al `RecursoPanel` en una
iteración futura.

**Otros cambios**:
- `templates/base.html`: el widget flotante del avatar (pensado para el
  niño) ahora vive en `{% block avatar_widget %}`, vacío en
  `panel_admin/base_panel.html` — se superponía con las tablas del panel.
- Mensajes de éxito (`django.contrib.messages`) al guardar/eliminar.

**Verificado**: 307/307 tests OK (14 nuevos en `panel_admin/tests.py`:
CRUD completo sobre un recurso normal, comportamiento de singleton,
comportamiento de solo lectura). Probado en navegador real: crear una
mascota nueva desde el formulario (con campos de imagen) y verla aparecer
en la lista.

## Fase 2 — qué se construyó

**Modelo nuevo**: `avatar.CaraAvatar` (migración `avatar/migrations/0005_caraavatar.py`,
aditiva) — un registro por emoción (`estado`, único), con `imagen` e
`imagen_parpadeo` (opcional). `_svg_personaje.html` ya no tiene las 9 caras
hardcodeadas a `feliz_1.svg`: usa el templatetag
`{% load avatar_tags %}{% caras_avatar %}` (`avatar/templatetags/avatar_tags.py`)
para traer la imagen real de cada emoción desde la base de datos, con
`neutral` como respaldo para cualquier emoción sin fila propia, y el viejo
`feliz_1.svg` estático como último respaldo si `CaraAvatar` está
completamente vacía (para no romper sitios que nunca usaron el panel).

El parpadeo (`imagen_parpadeo`) ya se renderiza en el DOM (oculto,
`display:none`, con `data-estado`) pero **no se anima todavía** — sigue
pausado a pedido del usuario (ver `project_avatar_pendientes` en memoria).
Cuando se reactive esa tarea, el JS solo necesita alternar la visibilidad
de `.dp-cara-parpadeo[data-estado="..."]`, el dato ya está disponible.

**`panel_admin/registry.py`**: se agregó el campo `template_form` a
`RecursoPanel` (antes no existía) para poder apuntar a una plantilla
distinta de la genérica. Dos recursos nuevos en el grupo "Avatar":
`items-avatar` (modelo `Item`) → `avatar_item_form.html`, y
`caras-avatar` (modelo `CaraAvatar`) → `avatar_cara_form.html`. La
lista/borrado de ambos sigue usando las plantillas genéricas de la Fase 1
— solo el formulario de alta/edición es a medida.

**Previsualización en vivo** (`panel_admin/static/panel_admin/avatar_preview.js`
+ las dos plantillas a medida): un lienzo de 288px con grilla de fondo que
representa el lienzo de referencia 500×500. Las piezas del cuerpo
(`avatar/static/avatar/cuerpo/partes/*.png`) se muestran siempre de fondo.
Al elegir un archivo en cualquier campo de imagen, se previsualiza al
instante con `URL.createObjectURL` — sin guardar ni recargar la página:
- Si la categoría es `ropa_superior` y se cargan las 4 mangas, la imagen
  principal se trata como pieza de lienzo completo (igual que el cuerpo) y
  las mangas se montan a pantalla completa (ya vienen pre-posicionadas).
- Para cualquier otra categoría, la imagen principal se posiciona en la
  caja porcentual de esa categoría (las mismas constantes que usa
  `personalizar.html`/`componente.html` en producción — están duplicadas
  a propósito en JS, JS no puede leer un template de Django).
- Los campos de manga se ocultan del formulario si la categoría no es
  `ropa_superior` (no tienen sentido ahí).

**Verificado**: 315/315 tests OK (8 nuevos: formularios a medida, ítem con
y sin mangas, validación de `estado` único en `CaraAvatar`, templatetag con
y sin datos). Probado en navegador real con Playwright: subí una chaqueta
con 4 mangas y un accesorio, ambos calzaron correctamente en la
previsualización; guardé una cara "feliz" y una "neutral" reales desde el
panel y confirmé que `/avatar/personalizar/` ya las usa en vez del
`feliz_1.svg` estático.

**Nota operativa**: hubo que correr `npm run build:css` después de crear
las plantillas nuevas (usan clases Tailwind — `w-72`, `lg:flex-row`, etc. —
que no existían en ningún template anterior) — si no, el lienzo de
previsualización se ve en blanco. Ver `feedback_tailwind_rebuild_tras_clases_nuevas`
en memoria.

## Fase 3 — qué se cerró

- **Permisos**: se decidió NO construir `Group`/`Permission` ni un campo
  nuevo en `UsuarioCustom` — `is_staff` nativo es suficiente porque solo
  Victor administra el panel hoy. Si en el futuro hace falta un rol más
  fino (ej. un profesor que solo vea Estadísticas), se evalúa entonces.
- **Bug encontrado y corregido antes de cerrar**: `avatar_cara_form.html`
  accedía a `object.imagen_parpadeo.url` sin guardia — Django lanza
  `ValueError` (500) cuando un `ImageField` está vacío, `|default` no lo
  intercepta porque la excepción ocurre al resolver la variable, antes de
  que el filtro corra. Se corrigió con `{% if object.imagen_parpadeo %}` y
  se agregó un test de regresión (`test_editar_cara_sin_parpadeo_no_revienta`).
- **Limpieza de checklist**: el JS inline de `avatar_cara_form.html` se
  movió a `panel_admin/static/panel_admin/avatar_cara_preview.js` (usando
  `json_script` para pasar el dato inicial, no `window.algo = '...'`), y
  `CaraAvatar` se registró en `avatar/admin.py` con `list_display` básico
  (gestión normal sigue siendo el panel; el admin nativo queda de respaldo).
- **Documentación final**: fila nueva en la tabla "Estado de módulos" de
  `CLAUDE.md` (después de K, aclarando que es una iniciativa fuera del
  Master Plan A-K) + entrada en `doc/auditoria_tecnica_dysplay.md`,
  sección "Actualizaciones" — vía el agente `documentador-dysplay`.

**Verificado**: 316/316 tests OK (24 en total para `panel_admin` + los
ajustes de `avatar`).

**Las 4 fases del plan original están completas.** Lo único que sigue
pausado a propósito es el parpadeo (animación) y 8 de las 9 caras de
emoción — ambos esperando que Victor suba el arte correspondiente desde
este mismo panel (ver [[project_avatar_pendientes]] en memoria).
