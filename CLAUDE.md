# CLAUDE.md — DysPlay

Plataforma web gamificada (Django + Tailwind + Vanilla JS) de apoyo a niños con
dislexia. Contexto completo en `doc/auditoria_tecnica_dysplay.md` (estado actual)
y `doc/DysPlay_MasterPlan_IA.docx` (plan de módulos A-K). Guía del avatar en
`doc/AVATAR_INTEGRATION_GUIDE.md`.

## Stack
- Backend: Python 3.12 + Django. DB: SQLite (dev) → PostgreSQL (prod).
- Frontend: Tailwind CSS (build pipeline, NO CDN) + Vanilla JS modular.
- IA: Azure Speech (pronunciación), Google Cloud Vision (cámara).
- Auth: django-allauth (Google OAuth 2.0).

## Estado de módulos
| Módulo | Estado | Tier riesgo | Notas |
|---|---|---|---|
| A - Infraestructura crítica | Completado | Alto | Ver Actualizaciones en auditoria_tecnica_dysplay.md (2026-06-13) |
| B - Recompensas unificado | Completado | Alto | Ver Actualizaciones en auditoria_tecnica_dysplay.md (2026-06-13) |
| C - Avatar avanzado | Completado | Medio | Ver Actualizaciones en auditoria_tecnica_dysplay.md (2026-06-14) |
| D - Mapa de niveles | Completado | Alto | Ver Actualizaciones en auditoria_tecnica_dysplay.md (2026-06-14) |
| E - Desafío diario | Completado | Medio | Ver Actualizaciones en auditoria_tecnica_dysplay.md (2026-06-14) |
| F - Historias | Completado | Bajo | Ver Actualizaciones en auditoria_tecnica_dysplay.md (2026-06-14) |
| G - Cámara inteligente | Completado | Medio | Ver Actualizaciones en auditoria_tecnica_dysplay.md (2026-06-14) |
| H - Estadísticas | Completado | Bajo | Ver Actualizaciones en auditoria_tecnica_dysplay.md (2026-06-14) |
| I - Configuración accesibilidad | Completado | Medio | Ver Actualizaciones en auditoria_tecnica_dysplay.md (2026-06-14) |
| J - Reportes email | Completado | Bajo | Ver Actualizaciones en auditoria_tecnica_dysplay.md (2026-06-14) |
| K - Celebraciones | Completado | Bajo | Ver Actualizaciones en auditoria_tecnica_dysplay.md (2026-06-14) |

(El agente `documentador-dysplay` actualiza esta tabla al cerrar cada módulo)

## Reglas de codificación (obligatorias)
- Variables, funciones y comentarios en ESPAÑOL.
- snake_case en Python, camelCase en JavaScript.
- Docstrings en todas las funciones de `services.py` y `utils.py`.
- Nunca `print()` — usar `logging`.
- Nunca hardcodear credenciales — variables de entorno (python-decouple/django-environ).
- Toda query que pueda lanzar `DoesNotExist` va en `try/except`.
- Endpoints que reciben archivos: validar tipo real (python-magic) y tamaño antes de procesar.
- Vistas delgadas: orquestan servicios, no contienen lógica de negocio (máx ~15 líneas).
- Errores internos: `logging.error(..., exc_info=True)`; el cliente recibe solo mensaje genérico.

## Análisis antes de modificar (obligatorio, en este orden)
1. Leer la sección correspondiente del Master Plan y de la Auditoría técnica.
2. Leer los templates HTML existentes del módulo — son la fuente de verdad del
   flujo UX. No cambiar el flujo sin aprobación explícita.
3. Mapear modelos/vistas/servicios/urls existentes relacionados antes de tocar código.
4. Verificar dependencias con otros módulos, en especial `recompensas`, `avatar`,
   `usuarios`, `configuracion` (todos usan context processors compartidos).

## Reglas para no romper módulos existentes
- No renombrar/eliminar campos de `UsuarioCustom`, `Avatar`, `ConfiguracionGlobal`,
  `ProgresoEstudiante` sin aprobación explícita + plan de migración de datos.
- No quitar ni renombrar claves devueltas por context processors existentes
  (`avatar_context`, `configuracion`) — solo agregar nuevas.
- Mantener URLs y nombres de templates existentes salvo indicación del Master Plan.
- Ejecutar `python manage.py test` antes y después de cualquier cambio.

## Criterios de calidad por módulo (checklist de cierre)
- [ ] Modelos con migraciones aplicadas
- [ ] Vistas con `@login_required`, sin exponer errores internos al cliente
- [ ] JS en archivos `.js` separados (sin inline, excepto `json_script` para config)
- [ ] >= 3 tests (modelos, vistas, servicios) y suite completa en verde
- [ ] Modelos registrados en admin con `list_display` básico
- [ ] Flujo UX de los templates existentes respetado
- [ ] Recompensas (monedas/insignias) otorgadas y validadas en servidor

## Cuándo detenerse y pedir revisión humana
- Cambios a modelos compartidos o migraciones destructivas.
- Nueva dependencia pip/npm.
- Conflicto Master Plan vs. UX existente sin solución obvia.
- Código de seguridad (auth, uploads, monedas/recompensas).
- Criterios de aceptación no cumplidos tras 2 intentos.

## Cómo documentar cambios importantes
- Actualizar la tabla "Estado de módulos" en este archivo.
- Agregar entrada en `doc/auditoria_tecnica_dysplay.md`, sección "Actualizaciones",
  con: módulo, fecha, resumen (3-5 líneas), archivos tocados, checklist cumplido.
- Commits en español: "Módulo X: descripción breve".

## Equipo de agentes (.claude/agents/)
- `arquitecto-dysplay` (opus): checkpoints de arquitectura y riesgo, decisiones críticas.
- `explorador-dysplay` (haiku): mapeo de contexto, solo lectura.
- `documentador-dysplay` (haiku): changelog y estado de módulos.
- `backend-django` (sonnet): modelos, services.py, vistas, signals, migraciones.
- `frontend-ui` (sonnet): Tailwind, templates, JS estático, temas/accesibilidad.
- `qa-tester` (sonnet): tests.py, validación de criterios de aceptación.

### Flujo de trabajo por módulo (orden A→K del Master Plan)
1. **Kickoff** (`explorador-dysplay`): mapa de contexto del módulo (archivos relacionados).
2. **Validación de alcance** (`arquitecto-dysplay`, solo tiers Alto/Medio): aprueba plan,
   detecta dependencias y riesgos. Si requiere tocar modelos compartidos → escalar a humano.
3. **Implementación** (`backend-django` y/o `frontend-ui`): trabajo en paralelo si hay
   tracks independientes; contexto acotado al módulo.
4. **Pruebas** (`qa-tester`): tests + `python manage.py test` completo + checklist de
   criterios de aceptación. Si falla → vuelve al paso 3 (máx. 2 ciclos).
5. **Revisión final** (`arquitecto-dysplay`, solo tier Alto): aprueba con resumen + resultados de tests.
6. **Documentación** (`documentador-dysplay`): changelog + tabla de estado.
