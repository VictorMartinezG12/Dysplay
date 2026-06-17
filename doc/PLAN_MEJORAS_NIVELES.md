# 🗺️ PLAN DE MEJORAS — MÓDULO NIVELES
> **Para Claude Code** · Instrucciones de implementación módulo por módulo
> **Regla de seguridad:** No modificar `base.html`, archivos de configuración global de diseño (colores/tipografía/tokens), ni otros módulos fuera de `niveles/` sin mostrarme el plan primero y esperar mi aprobación explícita.

---

## Contexto

Este es el primer módulo de una revisión que se hará módulo por módulo. El objetivo de esta pasada es doble:

1. **Auditoría técnica**: verificar que el módulo `niveles` use las funcionalidades de Django de forma completa y correcta (ORM optimizado, signals, forms, seguridad, estructura), y reportar hallazgos antes de tocar nada.
2. **Mejoras funcionales y visuales**: aplicar los cambios listados abajo, respetando el flujo de actividad ya definido en los templates existentes salvo donde se indique explícitamente lo contrario.

**Antes de escribir código:** Claude Code debe leer todos los archivos de `niveles/` (`models.py`, `views.py`, `services.py` si existe, templates, JS asociado) y presentar un resumen de la auditoría técnica (sección A) antes de proceder a las mejoras (sección B). No avanzar a la sección B sin mi confirmación.

---

## SECCIÓN A — Auditoría técnica (hacer primero, solo reportar, no modificar)

Revisar y reportar en una lista corta:

- [ ] ¿Las vistas usan `@login_required` consistentemente?
- [ ] ¿Hay queries N+1 que se beneficiarían de `select_related` / `prefetch_related`?
- [ ] ¿La vista `guardar_progreso` (o equivalente) tiene lógica de negocio mezclada que debería estar en un `services.py`?
- [ ] ¿Los errores se loguean con `logging` o se exponen directamente al cliente con `str(e)`?
- [ ] ¿Se usan `ModelForm` donde corresponde, o hay `request.POST.get()` manual sin validar?
- [ ] ¿El modelo `Nivel` tiene los campos `zona` y `orden_en_zona` ya creados (según Master Plan Módulo D)?
- [ ] ¿Existen tests en `niveles/tests.py`? ¿Cubren modelos, vistas y servicios?

**Output esperado de esta sección:** una lista de hallazgos con severidad (crítico/medio/bajo) — sin aplicar fixes todavía.

---

## SECCIÓN B — Mejoras a implementar

### B.1 — 🔴 CRÍTICO: Bug de monedas duplicadas al repetir nivel

**Síntoma reportado:** Al repetir un nivel ya completado anteriormente, el sistema vuelve a otorgar la recompensa completa en el último ejercicio del nivel, como si fuera la primera vez.

**Causa probable a verificar:** La lógica de otorgar recompensa está atada al evento "se completó el último ejercicio del nivel" en lugar de a "es la primera vez que este usuario completa este nivel".

**Solución a implementar:**
1. Separar dos conceptos de recompensa en el modelo o en la lógica de servicio:
   - `recompensa_primera_vez(estrellas)` → según la tabla de la sección B.2
   - `recompensa_repeticion` → monto fijo pequeño (2 a 5 monedas), independiente de las estrellas obtenidas en la repetición
2. Antes de otorgar la recompensa, verificar contra `ProgresoEstudiante` si el usuario ya tiene este nivel marcado como completado:
   - Si es la **primera vez** → otorgar `recompensa_primera_vez` según estrellas obtenidas
   - Si **ya estaba completado** → otorgar solo `recompensa_repeticion`, sin importar cuántas estrellas saque esta vez
3. Actualizar el campo de mejor resultado histórico (estrellas máximas alcanzadas) si la repetición supera el resultado anterior, pero esto es independiente de las monedas.

**Criterio de aceptación:** Repetir un nivel ya completado 10 veces seguidas otorga 10 veces la recompensa de repetición (pequeña), nunca la recompensa completa de primera vez.

---

### B.2 — Sistema de 3 estrellas con repetición ilimitada

**Comportamiento deseado:**
- El niño puede repetir cualquier nivel desbloqueado las veces que quiera, sin límite.
- Resultado por intento, según pronunciación:
  - Pronunciación deficiente → 1 estrella
  - Pronunciación buena → 2 estrellas
  - Pronunciación excelente → 3 estrellas
- Tabla de recompensa de **primera vez** (sujeta a ajuste posterior, usar como base):

| Estrellas | Monedas (primera vez) |
|---|---|
| 1 ⭐ | 25 |
| 2 ⭐⭐ | 50 |
| 3 ⭐⭐⭐ | 100 |

- Recompensa de **repetición** (nivel ya completado antes): 2 a 5 monedas fijas, sin importar las estrellas del intento actual.

**Nota para Claude Code:** Esta tabla es un punto de partida razonable, no un valor final cerrado — dejar el mapeo estrellas→monedas en una constante o configuración fácil de ajustar (diccionario en `services.py` o campo en modelo de configuración), no hardcodeado disperso en el código.

**Tarea pendiente relacionada (no bloqueante):** Definir cómo se traduce el score crudo de Azure Speech (0-100%) a 1/2/3 estrellas, considerando una curva más generosa para usuarios principiantes. Esto se resolverá en una iteración posterior — por ahora dejar un único punto de conversión (una función `score_a_estrellas(score, es_principiante=False)`) para no tener que reescribir lógica dispersa después.

---

### B.3 — Orden automático de niveles al crear uno nuevo

**Problema actual:** Al crear un nivel nuevo, hay que asignar manualmente su posición/orden dentro del mapa.

**Decisión (confirmada, no requiere debate adicional):** El orden debe asignarse automáticamente. Al crear un nivel nuevo sin especificar `orden_en_zona`, el sistema debe asignarle automáticamente `último_orden_de_esa_zona + 1`.

**Implementación sugerida:** Sobreescribir el método `save()` del modelo `Nivel`, o usar una señal `pre_save`:

```python
# En niveles/models.py, dentro de la clase Nivel
def save(self, *args, **kwargs):
    if self.orden_en_zona is None:
        ultimo = Nivel.objects.filter(zona=self.zona).order_by('-orden_en_zona').first()
        self.orden_en_zona = (ultimo.orden_en_zona + 1) if ultimo else 1
    super().save(*args, **kwargs)
```

**Razón de esta recomendación (para que el usuario la entienda):** Asignar el orden manualmente es propenso a error humano (números repetidos, huecos) y va a ser tedioso una vez que se use el admin de Django para agregar niveles con frecuencia. La automatización resuelve esto de raíz y es el patrón estándar en Django para este tipo de secuencias.

**Criterio de aceptación:** Crear un nivel nuevo sin especificar orden lo coloca automáticamente al final de su zona. Sigue siendo posible asignar un orden manual si se especifica explícitamente (para reordenar casos especiales).

---

### B.4 — Botón de salir disponible en todo el flujo

**Problema actual:** Dentro del flujo de un nivel (pantalla de ejercicio, grabación, espera de resultado), no existe forma de salir sin completar el ejercicio.

**Comportamiento deseado:** En cualquier pantalla del flujo del módulo de niveles debe existir un botón de salida visible (ej. una "X" en una esquina fija) que:
1. Detenga cualquier grabación de audio en curso (liberar el micrófono correctamente).
2. Cancele cualquier petición fetch/AJAX pendiente sin que quede un error visible al usuario.
3. Regrese al mapa de niveles sin guardar un progreso parcial corrupto.
4. No otorgue ni descuente monedas por la salida.

**Criterio de aceptación:** Es posible salir desde cualquier pantalla del flujo de niveles en cualquier momento, sin que el sistema quede en un estado inconsistente (audio grabándose en segundo plano, progreso a medias guardado, etc.).

---

### B.5 — Ocultar puntuación numérica y datos crudos al completar un ejercicio/nivel

**Comportamiento deseado (modo actual / modo fácil):**
- Al completar un ejercicio o nivel, **no mostrar** números de puntuación, porcentajes de Azure, ni listado de palabras específicas falladas.
- Mostrar en su lugar una pantalla de resultado puramente visual y motivadora: estrellas obtenidas, animación de celebración, frase del sistema (o del avatar cuando esté integrado).
- Si la pronunciación no fue buena, mostrar igualmente algo motivador (nunca negativo), no un mensaje de "fallaste".

**Implementación como feature flag (para escalar después a un modo difícil):**
- Agregar una variable de configuración `mostrar_puntuacion_detallada` (booleano, default `False`).
- Toda la lógica de cálculo de score, palabras falladas, etc. debe **seguir calculándose y guardándose en la base de datos** como hasta ahora (esto no se elimina, solo se oculta en la interfaz).
- El template de resultado debe envolver la sección de datos detallados en una condición: `{% if mostrar_puntuacion_detallada %}`.

**Criterio de aceptación:** Con el flag en `False` (estado actual deseado), el niño nunca ve números, porcentajes ni palabras específicas falladas — solo estrellas y mensajes motivadores. Los datos detallados siguen existiendo en la base de datos para uso futuro (modo difícil, panel de estadísticas para tutores, etc.).

---

### B.6 — Rediseño visual del mapa de niveles estilo "Candy Crush"

**Comportamiento deseado:**
- Mapa visual de progresión por mundos/zonas (ya definidos en el Master Plan: Bosque Encantado, Montaña de las Letras, Valle de las Sílabas, Castillo de las Palabras, Reino de la Lectura).
- Navegación por scroll/deslizamiento vertical dentro de cada mundo.
- Los niveles bloqueados (que aún no corresponden según el progreso) no son clickeables, aunque sean visibles al deslizar.
- Al completar todos los niveles de un mundo, se desbloquea el acceso al siguiente mundo.
- Mantener el flujo de entrada actual (clic en nivel desbloqueado → pantalla de ejercicio) sin cambios de fondo, solo el rediseño visual del mapa en sí.

**Tecnología sugerida para animaciones:** Lottie (`lottie-web` vía CDN o npm) para animaciones vectoriales ligeras en transiciones, celebraciones y posiblemente personajes/decoraciones del mapa. Confirmado como seguro de usar.

**Nota sobre ambientación por evento (Navidad, Año Nuevo, etc.):** Esto ya está contemplado en el Master Plan general (sistema de `EventoEspecial`). En esta pasada del módulo niveles, dejar la estructura visual preparada para aceptar un tema/skin alternativo del mapa (ej. una clase CSS condicional `mapa-tema-navidad`), pero la implementación completa del sistema de eventos se hará en su propio módulo más adelante.

**Criterio de aceptación:** El mapa se ve y se comporta de forma similar a Candy Crush (mundos separados, navegación vertical, niveles bloqueados no clickeables). El sistema de zonas ya definido en el Master Plan se usa tal cual, sin inventar una estructura nueva.

---

## Orden de implementación sugerido

1. Sección A (auditoría — reportar antes de tocar código)
2. B.1 (bug crítico de monedas) — más urgente porque es un bug, no una mejora
3. B.3 (orden automático de niveles) — pequeño, bajo riesgo, mejora inmediata de tu flujo de trabajo
4. B.2 (sistema de estrellas) — depende de B.1 estar resuelto
5. B.4 (botón de salir) — independiente, se puede hacer en paralelo
6. B.5 (ocultar puntuación) — independiente, feature flag simple
7. B.6 (rediseño visual del mapa) — el más grande, dejar para el final una vez la lógica esté estable

---

## Recordatorio de alcance

Esta pasada es **únicamente sobre el módulo `niveles`**. No tocar:
- `base.html`
- Archivo de configuración global de diseño (colores, tipografía, tokens)
- Otros módulos (avatar, historias, camara_inteligente, etc.)

Si en el proceso de implementar algo de esta lista se detecta que es necesario tocar algo fuera de este alcance (por ejemplo, el sistema de recompensas si todavía no existe como módulo separado), **detenerse y preguntar antes de proceder**, explicando por qué es necesario.
