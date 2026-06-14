# Auditoría Técnica y Arquitectónica - Proyecto DysPlay

## 1. Resumen Ejecutivo
DysPlay es un proyecto web desarrollado con el framework Django (Python) y un frontend integrado utilizando Tailwind CSS y Vanilla JavaScript. El objetivo principal es ofrecer una experiencia de aprendizaje gamificada para niños, centrándose en la superación de la dislexia. La aplicación cuenta con módulos de niveles, historias interactivas, personalización de avatar, cámara inteligente y configuraciones de accesibilidad.

El proyecto presenta una estructura base sólida orientada a aplicaciones de Django, con un diseño frontend sumamente pulido, accesible y reactivo a nivel de UI, que transmite una estética premium. Sin embargo, en el backend, varios módulos están implementados únicamente a nivel de plantillas estáticas (mockups funcionales) sin modelos de base de datos ni lógica de negocio robusta detrás, lo cual es típico de una fase inicial (MVP) pero representa una deuda técnica a solventar.

---

## 2. FASE 1: Descubrimiento (Estado Actual)

### Módulos y Responsabilidades
*   **`configuracion`**: Administra las preferencias globales de accesibilidad (tamaño de fuente, dislexia, colores, volumen). Posee un modelo `ConfiguracionGlobal` y un `context_processor` para inyectar configuración en todas las plantillas.
*   **`avatar`**: Maneja la personalización del avatar del usuario. Modelos: `Avatar`, `Item`, `InventarioAvatar`, `ReaccionAvatar`. Posee lógica real para equipar ítems y un sistema de eventos JS incipiente.
*   **`niveles`**: El núcleo de juego. Modelos: `Nivel`, `MisionVocabulario`, `ProgresoEstudiante`. En la vista, interactúa con Azure Speech Services (vía `servicios.utils.evaluar_pronunciacion`) para reconocimiento de voz y guarda el progreso.
*   **`usuarios`**: Modelo `UsuarioCustom` extendiendo `AbstractUser` para agregar campos como `monedas`, `racha_dias` y `correo_tutor`.
*   **`camara_inteligente`**: Vista simulada (`camara_view`) para jugar con gestos usando la cámara. Actualmente solo renderiza una UI sin lógica backend de reconocimiento de imagen.
*   **`historias`**: Vista simulada (`historias_view`) para cuentos interactivos. No posee modelos en base de datos. Toda la información está "quemada" (hardcoded) en el template.
*   **`estadisticas`**: Vista simulada (`estadisticas_view`). No posee modelos propios, pero debería cruzar datos de `ProgresoEstudiante`.
*   **`servicios`**: Módulo utilitario sin modelos. Contiene `utils.py` con la lógica para conectarse a Azure Speech.
*   **`desafio` / `core`**: `core` agrupa las configuraciones base de Django y `desafio` está vacío actualmente.

**Dependencias y Flujo de datos:**
Las apps están integradas principalmente en los templates a través de enlaces directos. El `context_processor` del avatar inyecta en el DOM el estado actual del personaje y las reacciones, permitiendo al frontend actualizar su UI basado en las preferencias sin consultar repetidamente la base de datos por Ajax.

---

## 3. FASE 2: Arquitectura

### Evaluación de Diseño
*   **Modularidad**: **Alta**. Django impone una separación por aplicaciones, y el proyecto la respeta. Cada funcionalidad está aislada en su propia app.
*   **Cohesión**: **Media-Alta**. Las apps como `avatar` y `configuracion` tienen responsabilidades claras y agrupadas.
*   **Acoplamiento**: **Bajo-Medio**. El acoplamiento más fuerte se da en los templates (UI unificada) y la dependencia global al usuario activo (`request.user`).
*   **SRP (Single Responsibility Principle)**: Bien aplicado a nivel de apps. Sin embargo, en `niveles/views.py`, la función `guardar_progreso` mezcla la recepción del archivo, la validación, la llamada al servicio externo (Azure) y la lógica de respuesta JSON/Redirect.

### ¿Qué está bien diseñado?
*   El uso de **Context Processors** para `configuracion` y `avatar` permite mantener la UI persistente del avatar sin tener que llamar a la base de datos en cada vista.
*   La encapsulación del servicio de IA en `servicios/utils.py` evita ensuciar las vistas con configuración de la API de Azure.
*   Personalización del modelo de usuario mediante `AbstractUser`.

### ¿Qué está mal diseñado o podría romperse?
*   Falta de serializadores o un API Framework estructurado (DRF). El frontend envía datos vía FormData y `niveles/views.py` devuelve `JsonResponse`. Esto es difícil de escalar si se desea separar completamente el frontend.
*   Dependencias fuertes de UI (Mockups). Las apps de `historias`, `camara_inteligente` y `estadisticas` tienen código HTML masivo que simula bases de datos.
*   En `configuracion/views.py`, los cambios se procesan mediante `request.POST.get()` manual y exhaustivo, en lugar de usar Django Forms (`ModelForm`).

---

## 4. FASE 3: Base de Datos

### Relaciones y Modelos
*   `Avatar` tiene un `OneToOneField` con `User`. Correcto.
*   `InventarioAvatar` usa una relación intermedia `ForeignKey` a `Avatar` e `Item`, actuando como una relación ManyToMany explícita con campos adicionales (`equipado`, `desbloqueado`). Muy bien estructurado.
*   `ConfiguracionGlobal` tiene un `OneToOneField` con `User`. Correcto.
*   `ProgresoEstudiante` se relaciona mediante `OneToOneField` a `User`, pero el nombre `Usuario` es muy genérico, podría ser confuso.
*   `MisionVocabulario` tiene un `ForeignKey` hacia `Nivel`. Correcto.

### Riesgos y Posibles Cuellos de Botella
*   **Duplicación de datos implícita**: El saldo del usuario (`monedas`) y la `racha_dias` se guardan en el modelo `UsuarioCustom`. Si el proyecto crece, es mejor tener un modelo `PerfilEstudiante` / `ProgresoGlobal` o similar para separar la lógica de autenticación de las métricas de gamificación.
*   **Falta de modelos**: Las historias interactivas y estadísticas no existen en DB. Al crecer el proyecto, habrá que migrar todo el texto hardcodeado a modelos relacionales.

---

## 5. FASE 4: Frontend

*   **TailwindCSS**: Utilizado vía CDN (`<script src="https://cdn.tailwindcss.com"></script>`). Esto está bien para desarrollo, pero en producción es lento y no está optimizado. Debería integrarse mediante Node.js/PostCSS para generar un bundle minimizado.
*   **Diseño UI/UX**: Excepcional. Cumple de sobra con el requerimiento de tener un diseño "premium", amigable, infantil y enfocado a accesibilidad. Se usan animaciones fluidas, paletas de colores adecuadas y Lucide Icons.
*   **JavaScript**: El uso de Vanilla JS es funcional, pero el código de grabación de audio en `niveles.html` (`toggleRecording`) mezcla lógica de Audio API de bajo nivel, DOM manipulación y peticiones Fetch. Esto puede ser propenso a errores en navegadores de móviles no estandarizados (iOS Safari).
*   **Reutilización**: Se está repitiendo mucho "boilerplate" de Tailwind y layouts (`<header>`, navegación lateral) dentro de plantillas individuales en vez de aprovechar completamente los bloques dinámicos del `base.html`.

---

## 6. FASE 5: Seguridad

*   **Login Required**: Todas las vistas funcionales usan el decorador `@login_required`. Excelente.
*   **Validaciones Backend**: Faltan validaciones de tipo y saneamiento riguroso. En `guardar_progreso`, no se valida si el archivo enviado es efectivamente un `.wav` real o malicioso, o si excede el tamaño máximo permitido. Solo se confía en la extensión temporal.
*   **File Uploads**: `Item.imagen` utiliza `ImageField`. Está bien, pero sería recomendable restringir formatos y pesos.
*   **Exposición de Logs**: En `niveles/views.py` se captura `Exception as e` y se devuelve el mensaje de error directamente en un `JsonResponse` `({'status': 'error', 'message': str(e)})`. Esto podría exponer información sensible del servidor (ej: rutas del sistema operativo) al cliente.

---

## 7. FASE 6: Escalabilidad

*   **Facilidad para nuevas apps**: Muy alta. Django permite añadir módulos rápidamente.
*   **Nuevas vistas/modelos**: Facilidad alta por la naturaleza monolítica y modular actual.
*   **Escalabilidad Frontend**: Media. Debido al uso extensivo de clases CSS en línea y JavaScript mezclado en HTML, el código frontend se está volviendo espagueti. Migrar a React/Vue o un sistema de componentes más formal (Alpine.js, HTMX) ayudaría mucho en el futuro.
*   **Procesamiento Asíncrono**: Azure Speech es llamado sincrónicamente dentro de una petición HTTP (`recognize_once_async().get()`). Bajo carga de muchos usuarios concurrentes, esto congelará workers del servidor web (Gunicorn/WSGI). Debe moverse a tareas en background (Celery) o usar WebSockets/Asgi.

---

## 8. FASE 7: Matriz de Riesgos

| Riesgo | Impacto | Probabilidad | Prioridad |
| ------ | ------- | ------------ | --------- |
| Tailwind cargado por CDN en Producción | Medio | Alta | Alta |
| Bloqueo del servidor web por peticiones sincrónicas a Azure (Azure Timeout) | Crítico | Media | Alta |
| Exposición de errores del backend vía JSON (StackTrace leak) | Alto | Media | Alta |
| Código JS y plantillas inmanejables por excesiva longitud y repetición | Medio | Alta | Media |
| Archivos de audio subidos sin validación de tipo real o peso máximo | Alto | Baja | Media |
| Datos dinámicos estáticos (hardcodeados) en Historias y Estadísticas | Bajo | Alta | Baja |

---

## 9. FASE 8: Roadmap Técnico Propuesto

### 1. Correcciones Críticas (Inmediato)
1.  **Migrar Tailwind CDN a Build Pipeline**: Configurar Node.js y compilar el archivo CSS estático oficial para producción.
2.  **Sanitización de Errores y Seguridad de Archivos**: Limitar el tamaño de archivos subidos en Azure Speech y devolver mensajes de error genéricos al frontend, registrando los errores reales en logs (`logging`).
3.  **Refactor de `niveles/views.py`**: Separar la lógica de subida y conexión a Azure en servicios independientes; no dejar que la vista maneje limpieza temporal de OS si no es estrictamente necesario, o usar `InMemoryUploadedFile`.

### 2. Mejoras Recomendadas (A corto plazo)
1.  **Refactor Frontend (Django Templates + JS)**: Separar el código JS en archivos `.js` ubicados en la carpeta estática (`/static/js/`), y usar bloques modulares para los layouts (Header, Footer) de forma de no repetir el código en las vistas HTML.
2.  **Uso de Django Forms**: En `configuracion/views.py`, implementar un `ConfiguracionForm(forms.ModelForm)` para aprovechar las validaciones de Django al actualizar la base de datos.
3.  **Modelado de Módulos Faltantes**: Diseñar y crear `models.py` para `historias`, `estadisticas` y `camara_inteligente` para abandonar la etapa Mockup.

### 3. Mejoras Opcionales (A medio plazo)
1.  **Framework de API (Django Rest Framework o Ninja API)**: Exponer la comunicación de Reactividad del Frontend (Guardar Progreso, Cambiar Ropa del Avatar) a través de un API estandarizado en vez de endpoints construidos "a mano" con `JsonResponse`.
2.  **Integración de HTMX / AlpineJS**: Para lograr interactividad compleja (como el caso del Avatar) sin escribir tanto Vanilla JS engorroso.

### 4. Refactorizaciones Futuras (A largo plazo)
1.  **Desacople Arquitectónico (Frontend SPA)**: Migrar el frontend a Next.js / Vue.js conectándose al backend de Django vía APIs REST o GraphQL, aprovechando todo el diseño logrado.
2.  **Celery y Redis**: Para tareas pesadas de IA, enviar el audio al servidor, devolver un "Task ID" al cliente, y hacer polling o WebSockets para recibir la respuesta de Azure de forma asincrónica real y no bloquear el request principal.

---
*Fin del reporte de Auditoría.*

## Actualizaciones

Esta sección registra cambios relevantes posteriores al reporte original.
El agente `documentador-dysplay` agrega una entrada nueva al cerrar cada
módulo del Master Plan, con el formato:

```
### Módulo <X> — <nombre del módulo> (<fecha YYYY-MM-DD>)
- Resumen: <3-5 líneas de lo implementado>
- Archivos tocados: <lista breve>
- Checklist de calidad: <cumplido / pendiente: detalle>
```

### Pre-Master Plan (sin fecha registrada)
- Se agregó la API de Google Cloud Vision (módulo de cámara inteligente).
- No se modificó nada más en esa actualización.

### Módulo A — Correcciones Críticas de Infraestructura (2026-06-13)
- Resumen: A.1 — Tailwind migrado de CDN a build pipeline (tailwind.config.js, postcss.config.js, static/css/output.css ~46KB, CDN eliminado de 6 templates, Lucide intacto). A.2 — niveles/views.py refactorizado: nuevo niveles/services.py (procesar_audio_subido con validación python-magic, evaluar_pronunciacion_azure, guardar_progreso_estudiante, calcular_recompensas); vista guardar_progreso reducida a ~8 líneas, sin exponer str(e), logging con exc_info; CASO B ahora persiste progreso real. A.3 — JS de niveles.html (208 líneas) extraído a static/js/niveles.js (JSDoc, pipeline WAV preservado), datos Django→JS vía json_script y data-* attributes.
- Archivos tocados: package.json, tailwind.config.js, postcss.config.js, static/css/input.css, static/css/output.css, templates/base.html, camara_inteligente/templates/camara_inteligente/camara.html, avatar/templates/avatar/avatar.html, historias/templates/historias/historias.html, estadisticas/templates/estadisticas/estadisticas.html, niveles/templates/niveles/niveles.html, niveles/views.py, niveles/services.py (nuevo), niveles/tests.py, static/js/niveles.js (nuevo), requirements.txt (+python-magic==0.4.27).
- Checklist de calidad: cumplido (14/14 tests OK, makemigrations sin cambios, @login_required sin fugas, JS sin inline salvo json_script, admin con list_display, flujo UX de niveles.html respetado).
- Veredicto arquitecto: APROBADO CON SEGUIMIENTOS.
- Deuda/seguimientos para módulos futuros:
  - 5 templates standalone (avatar, camara, estadisticas, niveles, historias) usan el token `primaryFijo` (#3B82F6, azul fijo que no sigue el tema dinámico). Revisión visual humana pendiente; decidir en Módulo I si deben migrar a `primary` dinámico.
  - Regla "monedas = nivel.puntos_recompensa si score>=70" vive en niveles/services.py:calcular_recompensas. El Módulo B debe centralizarla en el sistema de recompensas unificado y hacer que niveles la consuma, sin duplicar fuente de verdad.
  - racha_dias queda pendiente para el Módulo B, que deberá añadir el campo de fecha de última actividad necesario.
  - static/css/output.css pesa ~46.1KB de 50KB máximo. Vigilar tras el Módulo D (mapa de niveles) y considerar cssnano si se acerca al límite.
  - Preexistente (no de Módulo A): camara_inteligente/tests.py es un script con efectos de red real (Google Vision), no un TestCase Django; contamina la salida de manage.py test. Anotado para Módulo G.

### Módulo B — Sistema de Recompensas Unificado (2026-06-13)
- Resumen: Se creó la app `recompensas` con 7 modelos (TipoInsignia, Insignia, Mascota, MascotaUsuario, Coleccionable, ColeccionableUsuario, EventoEspecial). recompensas/services.py implementa otorgar_monedas (atómico con F()/select_for_update), verificar_y_otorgar_insignias, obtener_insignias_pendientes, actualizar_racha (usa el campo ultima_fecha_conexion ya existente en UsuarioCustom, sin cambios de esquema) y get_evento_activo. recompensas/signals.py conecta post_save de ProgresoEstudiante -> verificar_y_otorgar_insignias, y user_logged_in -> actualizar_racha (desvío aprobado respecto al Master Plan: la racha se actualiza al iniciar sesión, no al guardar progreso, para evitar escrituras repetidas; cubre también login vía Google OAuth/allauth). niveles/services.py:calcular_recompensas fue refactorizado para delegar el otorgamiento de monedas en recompensas.services.otorgar_monedas, conservando firma y retorno exactos. avatar/context_processors.py:avatar_global se extendió con 5 claves nuevas (insignias_pendientes sin marcar, mascota_usuario, monedas_usuario, racha_dias, evento_activo) sin modificar las 3 claves existentes (avatar_user, avatar_equipados, reacciones_json), maneja usuario anónimo. Se cargaron fixtures de ejemplo (insignias, mascotas, coleccionables). Iteración backend-only; UI de insignias/mascotas queda para Módulo C.
- Archivos tocados: recompensas/models.py (nuevo), recompensas/admin.py (nuevo), recompensas/apps.py (nuevo), recompensas/services.py (nuevo), recompensas/signals.py (nuevo), recompensas/views.py (nuevo, stub sin uso), recompensas/tests.py (nuevo, 23 tests), recompensas/migrations/0001_initial.py (nuevo), recompensas/fixtures/tipos_insignia.json (nuevo), recompensas/fixtures/mascotas.json (nuevo), recompensas/fixtures/coleccionables.json (nuevo), core/settings.py (INSTALLED_APPS), niveles/services.py (calcular_recompensas), avatar/context_processors.py (avatar_global).
- Checklist de calidad: cumplido (23 tests nuevos + 36 tests de suite completa OK excluyendo camara_inteligente, makemigrations --check limpio, admin con list_display en los 7 modelos, sin str(e) expuesto, monedas atómicas y server-side, insignias automáticas vía signal sin recursión, 13 tests preexistentes de niveles sin romper).
- Veredicto arquitecto: APROBADO CON SEGUIMIENTOS.
- Deuda/seguimientos para módulos futuros:
  - Módulo C (o el que implemente UI de avatar/insignias): invocar obtener_insignias_pendientes desde una vista para marcar mostrada=True y disparar animación; consumir las 5 claves nuevas del context processor (insignias_pendientes, mascota_usuario, monedas_usuario, racha_dias, evento_activo).
  - Módulo F (Historias): implementar el criterio de insignia "historias_10" (hoy placeholder con criterio_cumplido=False) cuando historias exponga un contador de historias completadas.
  - Lag menor conocido: las insignias de racha (racha_7/racha_30) se otorgan en la siguiente acción de progreso del día, no en el instante del login, porque se evalúan en el post_save de ProgresoEstudiante leyendo racha_dias ya actualizada por el login previo. Aceptable para la UX actual; reevaluar solo si se requiere feedback inmediato.
  - recompensas/views.py es un stub intencional sin uso, reservado para futuras vistas de insignias/mascotas/tienda.

### Módulo C — Avatar Avanzado — Compañero de Aventura (2026-06-14)
- Resumen: C.1 — Avatar extendido con frase_bienvenida y personalidad (animado/tranquilo/gracioso); Item ampliado con categoria 'habitacion'/'fondo' (sin tocar choices previos), precio_monedas y evento_especial (FK recompensas.EventoEspecial, SET_NULL); nuevo modelo CasaAvatar (OneToOne con Avatar, slots cama/cuadro/alfombra/lampara como FK a Item). C.2 — avatar/reactions.py con diccionario REACCIONES (7 tipos de evento) y obtener_reaccion(); context processor avatar_global agrega la clave nueva avatar_frase_contextual (las 8 claves previas intactas); avatar_events.js conectado por primera vez vía script tags JSON en base.html (reacciones_json y avatar_frase_contextual), con nuevo método mostrarFraseContextual(). C.3 — Casa del Avatar: avatar/casa.html rediseñado (habitación visual con 4 slots, sección "Mis ítems" y "Tienda"), static/js/avatar/casa.js para compra/colocación; nuevas vistas casa_avatar, comprar_item, colocar_item y rutas avatar:casa/comprar_item/colocar_item (avatar:personalizar intacta); compra de ítems usa recompensas.services.cobrar_monedas (nueva función atómica + SaldoInsuficienteError), reutilizando el sistema unificado de recompensas del Módulo B.
- Archivos tocados: avatar/models.py, avatar/admin.py, avatar/views.py, avatar/urls.py, avatar/context_processors.py, avatar/reactions.py (nuevo), avatar/services.py (nuevo), avatar/tests.py (nuevo, 31 tests), avatar/migrations/0003_avatar_frase_bienvenida_avatar_personalidad_and_more.py (nuevo), avatar/templates/avatar/casa.html, avatar/templates/avatar/personalizar.html, static/js/avatar_events.js, static/js/avatar/casa.js (nuevo), templates/base.html, recompensas/services.py.
- Checklist de calidad: cumplido (31 tests nuevos de avatar + 23 de recompensas = 54 OK, suite completa 68 tests OK sin regresiones; makemigrations sin pendientes; @login_required en las 4 vistas de avatar sin exponer str(e); JS externo (avatar_events.js, avatar/casa.js) sin inline; modelos nuevos/extendidos en admin con list_display; flujo UX existente de personalizar.html respetado, solo se agregó el botón "Mi Casa"; compra de ítems de habitación validada server-side vía cobrar_monedas atómico).
- Deuda/seguimientos para módulos futuros:
  - Item.categoria mantiene los choices preexistentes ('cabello','ropa_superior','ropa_inferior','calzado','accesorio','mascota','mueble','decoracion','trofeo') más los nuevos 'habitacion' y 'fondo' del Master Plan; no se migró/renombró la lista completa del Master Plan para evitar migración destructiva de datos (decisión del arquitecto). Revisar si en un módulo futuro conviene unificar nomenclatura.
  - No hay fixtures de ítems con categoria='habitacion'/'fondo' ni precio_monedas > 0 todavía; la Casa y la Tienda funcionan correctamente con listas vacías, pero se recomienda cargar fixtures de ejemplo en un módulo futuro (o antes de demo) para mostrar el flujo de compra real.
  - ReaccionAvatar (modelo BD, admin-editable) coexiste con avatar/reactions.py (dict de variantes en código); avatar_frase_contextual usa solo reactions.py. Si se desea que el admin controle también la frase contextual, evaluar unificación en un módulo futuro.

### Módulo D — Mapa de Niveles (2026-06-14)
- Resumen: D.1 — Reemplazó lista de niveles por Mapa de Aventura visual (SVG, 5 zonas temáticas: Bosque Encantado, Montaña de las Letras, Valle de las Sílabas, Castillo de las Palabras, Reino de la Lectura); data-driven vía obtener_mapa_aventura(usuario). Modelo Nivel ganó campos aditivos zona, orden_en_zona, narrativa_intro (migraciones 0003 esquema + 0004 backfill no destructivo de 3 niveles existentes, reverso noop). Por decisión de alcance, no se sembraron 17 niveles restantes del Master Plan: 4 zonas sin niveles muestran "Próximamente" (desbloqueadas) o "Bloqueada" (no), manteniendo mapa data-driven. D.2 — procesar_intento_nivel centraliza en services.py flujo evaluación (Azure → progreso → recompensas → reacción avatar); evaluar_pronunciacion ahora retorna desglose palabras (score por palabra, extraído de JSON Azure con granularity=Phoneme). UI resalta cada palabra verde/rojo según score >=70. Reacción avatar (construir_reaccion_avatar) se entrega como datos planos {tipo, mensaje} en JSON, renderizados en #resultado-mensaje-avatar sin depender de AvatarSystem/AVATAR_EVENT. D.3 — Cada zona/nivel puede tener narrativa_intro; si no vacío, muestra en modal #modal-narrativa antes de iniciar primer ejercicio. Solo nivel 1 (Bosque Encantado) tiene narrativa cargada por ahora.
- Archivos tocados: niveles/models.py, niveles/migrations/0003_nivel_narrativa_intro_nivel_orden_en_zona_nivel_zona.py, niveles/migrations/0004_datos_zona_mapa_aventura.py, niveles/admin.py, niveles/services.py, niveles/views.py, servicios/utils.py, niveles/templates/niveles/mapa.html (nuevo), niveles/templates/niveles/niveles.html, static/js/niveles.js, niveles/tests.py.
- Checklist de calidad: cumplido (83/83 tests OK incluyendo 15 nuevos de mapa/reacciones/progreso; migraciones aplicadas; @login_required sin fuga errores; JS sin inline; admin con list_display; flujo UX respetado; recompensas validadas server-side).

### Módulo E — Desafío Diario (2026-06-14)
- Resumen: Nueva app `desafio` (template standalone tipo niveles.html). Modelos: `ConfiguracionDesafio` (singleton pk=1, narrativa/zona activa/meta diaria/recompensa base), `DesafioDiario` (fecha única, M2M a `MisionVocabulario` para ejercicios obligatorios/opcionales, recompensa en monedas y coleccionable opcional) y `ProgresoDesafio` (progreso por usuario/día, unique_together). `services.obtener_o_crear_desafio_de_hoy` genera el desafío del día (1 obligatorio + hasta 3 opcionales al azar entre todas las `MisionVocabulario`); `obtener_narrativa_del_dia` compone el arco narrativo continuo ("Las letras mágicas desaparecieron del reino...") según la zona activa. `procesar_intento_desafio` reutiliza `niveles.services.procesar_audio_subido`/`evaluar_pronunciacion_azure` (mismo umbral `UMBRAL_SUPERACION_NIVEL`=70); al completar todos los ejercicios del día otorga monedas vía `recompensas.otorgar_monedas`, un coleccionable aleatorio no poseído (`otorgar_coleccionable_aleatorio`) y evalúa insignias. Se agregó el criterio `desafio_diario` a `TipoInsignia.CRITERIO_CHOICES` + insignia "Aventurero Diario" (migración de datos + fixture). `avatar/reactions.py` ganó el tipo `desafio_completado`. Frontend: `desafio.html` (vistas inicio/ejercicio/loading/resultado + resumen final con monedas/coleccionable/insignia, countdown de 24h cuando ya está completado) y `static/js/desafio/desafio.js` (grabación/codificación WAV reutilizada de niveles.js, CSRF vía `{% csrf_token %}` + `document.querySelector('[name=csrfmiddlewaretoken]')`). Se agregó la 6ª tarjeta "Desafío del Día" en `templates/home.html`. Migración de datos aditiva en `niveles` agrega 3 `MisionVocabulario` (niveles 1, 2 y 3) para que el desafío siempre tenga ejercicios suficientes.
- Archivos tocados: desafio/models.py, desafio/services.py, desafio/views.py, desafio/urls.py, desafio/admin.py, desafio/tests.py, desafio/migrations/0001_initial.py, desafio/templates/desafio/desafio.html, static/js/desafio/desafio.js, core/urls.py, templates/home.html, recompensas/models.py, recompensas/services.py, recompensas/migrations/0002_alter_tipoinsignia_criterio.py, recompensas/migrations/0003_datos_insignia_desafio_diario.py, recompensas/fixtures/tipos_insignia.json, avatar/reactions.py, avatar/tests.py, niveles/migrations/0005_datos_misiones_desafio_diario.py, static/css/output.css (rebuild).
- Checklist de calidad: cumplido (16 tests nuevos de `desafio` + suite completa 99/99 OK sin regresiones tras actualizar `avatar.tests.ReactionsTests` por el nuevo tipo de reacción; migraciones de esquema y de datos aplicadas; vista `evaluar_ejercicio` con `@login_required`, sin exponer `str(e)`; JS externo sin inline salvo `json_script`; los 3 modelos nuevos registrados en admin con `list_display`; flujo UX (vistas inicio/ejercicio/resultado, mic/WAV, reacciones del avatar) calcado del patrón de niveles.html; monedas/coleccionable/insignia otorgados y validados 100% server-side).
- Deuda/seguimientos para módulos futuros:
  - `desafio.html` usa el token `primaryFijo` (#3B82F6), consistente con las demás plantillas standalone (decisión heredada del Módulo A); revisar junto con el resto en el Módulo I si se unifica el theming dinámico.
  - El desafío del día elige ejercicios al azar entre *todas* las `MisionVocabulario` existentes, sin filtrar por nivel/zona del usuario. Cuando el Módulo D (o uno futuro) siembre los ~20 niveles restantes del Master Plan, conviene revisar si el desafío debe acotarse a niveles ya desbloqueados por el estudiante.
  - `DesafioDiario.recompensa_coleccionable` es opcional vía admin (no hay fixtures con uno asignado); por defecto se sortea entre todos los `Coleccionable` no poseídos. Cargar `recompensa_coleccionable` por fecha es una mejora editorial futura, no bloqueante.