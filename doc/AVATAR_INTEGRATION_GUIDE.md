# 🦁 GUÍA DE INTEGRACIÓN DEL AVATAR — DysPlay
> **Para el equipo de desarrollo** · Versión 1.0 · Junio 2026

---

## ¿Qué es el Avatar en DysPlay?

El avatar **no es una imagen decorativa**. Es el compañero de viaje del niño, el guía del sistema y el portavoz de todas las interacciones importantes. Piénsalo como el personaje que "vive" dentro de la app y acompaña al usuario en cada momento: cuando acierta, cuando falla, cuando entra al sistema, cuando gana una insignia, cuando lleva varios días sin entrar.

**El avatar tiene tres roles simultáneos:**
1. **Compañero emocional** — reacciona a lo que hace el niño
2. **Guía del sistema** — explica cómo funciona cada módulo
3. **Mascota persistente** — está presente en todas las pantallas

---

## Estado actual y decisión de diseño temporal

**Actualización (2026-06-14):** El Módulo C (Avatar avanzado) ya está completado. La
personalización del avatar (ropa, calzado, cabello, accesorios, mascotas y la Casa del
Avatar con muebles/decoración) está implementada de punta a punta: modelos `Item`,
`InventarioAvatar` y `CasaAvatar`, tienda y sistema de equipar/desequipar (`avatar/casa.html`
+ `static/js/avatar/casa.js`), reacciones (`avatar/reactions.py`) y el context processor
`avatar_global` con las claves descritas en este documento.

Lo único que sigue pendiente son los **assets visuales finales** (sprites/ilustraciones del
cuerpo, ropa, accesorios y expresiones). El código ya referencia las rutas `/static/avatar/...`
con fallbacks a placeholders (ver `Item.imagen_url_segura` en `avatar/models.py` y
`avatar/templates/avatar/personalizar.html`), siguiendo la misma decisión de diseño que ya
estaba prevista:

**Cuando los assets estén listos, el equipo solo necesita:**
- Colocar los archivos de imagen en las rutas `/static/avatar/...` ya referenciadas por el código
- Conectar las imágenes de cada emoción según la convención de nombres definida abajo
- No tocar ningún código de lógica, vistas ni templates

---

## Convención de nombres de archivos (preparar desde ya)

Crear la carpeta `/static/img/avatar/` con los siguientes archivos. Por ahora pueden ser placeholders de color sólido:

```
/static/img/avatar/
├── avatar_base.png          ← imagen neutral / reposo
├── avatar_feliz.png         ← pronunciación correcta, nivel completo
├── avatar_eufórico.png      ← score perfecto, racha nueva, insignia
├── avatar_animando.png      ← cuando el niño está intentando / grabando
├── avatar_pensando.png      ← cuando el sistema procesa
├── avatar_triste.png        ← pronunciación muy mala (nunca mostrar enojo)
├── avatar_sorprendido.png   ← desbloqueo de coleccionable, evento especial
├── avatar_durmiendo.png     ← inactividad de varios días
└── avatar_saludando.png     ← bienvenida diaria
```

**Para la fase temporal:** usar un solo archivo `avatar_base.png` y un único CSS/clase que cambie de estado visualmente (opacidad, border-color, animación CSS) hasta que existan los sprites reales.

---

## Cómo integrar el avatar en `base.html`

El avatar debe vivir en el layout principal. Toda pantalla que extienda `base.html` lo hereda automáticamente.

### Estructura sugerida en `base.html`

```html
<!-- BLOQUE DEL AVATAR — va en el sidebar o esquina inferior derecha -->
<div id="avatar-companion" class="avatar-widget {{ avatar_estado }}">
  
  <!-- Imagen del avatar (cambia según el estado) -->
  <div class="avatar-imagen">
    {% if avatar_estado == 'feliz' %}
      <img src="{% static 'img/avatar/avatar_feliz.png' %}" alt="Tu compañero feliz">
    {% elif avatar_estado == 'eufórico' %}
      <img src="{% static 'img/avatar/avatar_euforico.png' %}" alt="Tu compañero emocionado">
    {% elif avatar_estado == 'animando' %}
      <img src="{% static 'img/avatar/avatar_animando.png' %}" alt="Tu compañero animándote">
    {% elif avatar_estado == 'durmiendo' %}
      <img src="{% static 'img/avatar/avatar_durmiendo.png' %}" alt="Tu compañero te extraña">
    {% else %}
      <img src="{% static 'img/avatar/avatar_base.png' %}" alt="Tu compañero de aventura">
    {% endif %}
  </div>

  <!-- Burbuja de diálogo del avatar -->
  {% if avatar_frase %}
  <div class="avatar-burbuja" id="avatar-burbuja">
    <p>{{ avatar_frase }}</p>
  </div>
  {% endif %}

  <!-- Insignias pendientes de mostrar -->
  {% for insignia in insignias_pendientes %}
  <div class="insignia-nueva-notif" data-insignia="{{ insignia.id }}">
    🏆 {{ insignia.tipo_insignia.nombre }}
  </div>
  {% endfor %}

</div>
```

### Lo que el context processor inyecta (ya preparar el context processor)

En `avatar/context_processors.py` asegurarse de que el diccionario devuelto incluya:

```python
def avatar_context(request):
    if not request.user.is_authenticated:
        return {}
    return {
        'avatar_estado': obtener_estado_avatar(request.user),   # str: 'feliz', 'base', etc.
        'avatar_frase': obtener_frase_avatar(request.user),     # str o None
        'avatar_nombre': obtener_nombre_avatar(request.user),   # str: 'León', etc.
        'insignias_pendientes': obtener_insignias_pendientes(request.user),  # queryset
        'monedas_usuario': request.user.monedas,                # int
        'racha_dias': request.user.racha_dias,                  # int
        'evento_activo': get_evento_activo(),                   # objeto o None
    }
```

---

## Sistema de frases y estados del avatar

### Estados disponibles

| Estado | Cuándo se usa | Imagen |
|---|---|---|
| `base` | Estado neutro / navegando | `avatar_base.png` |
| `saludando` | Primera carga del día | `avatar_saludando.png` |
| `feliz` | Pronunciación correcta, nivel completado | `avatar_feliz.png` |
| `eufórico` | Score > 90%, racha nueva, insignia | `avatar_euforico.png` |
| `animando` | Niño está grabando audio | `avatar_animando.png` |
| `pensando` | Sistema procesando respuesta | `avatar_pensando.png` |
| `triste` | Score < 50% (nunca enojo, solo empatía) | `avatar_triste.png` |
| `sorprendido` | Coleccionable desbloqueado, evento especial | `avatar_sorprendido.png` |
| `durmiendo` | El niño no ha entrado en 3+ días | `avatar_durmiendo.png` |

### Banco de frases por contexto

Implementar en `avatar/reactions.py` como un diccionario con listas (se elige aleatoriamente):

```python
import random

FRASES_AVATAR = {
    'bienvenida_diaria': [
        "¡Hola! ¡Te estaba esperando! ¿Listo para practicar?",
        "¡Buenos días, aventurero! ¡El reino te necesita hoy!",
        "¡Llegaste! ¡Sabía que vendrías! Empecemos.",
    ],
    'bienvenida_regreso': [  # Más de 2 días sin entrar
        "¡Volviste! ¡Te extrañé muchísimo! ¿Seguimos la aventura?",
        "¡Oye! ¡Qué bueno que regresaste! Tu racha te espera.",
    ],
    'pronunciacion_correcta': [
        "¡Exacto! ¡Eso fue perfecto!",
        "¡Lo lograste! ¡Eres un crack de las palabras!",
        "¡Sí! ¡Esa pronunciación fue increíble!",
        "¡Genial! ¡Sigue así!",
    ],
    'pronunciacion_casi': [  # Score 70-89%
        "¡Casi perfecto! Un poquito más despacio y lo tienes.",
        "¡Muy bien! Solo ajusta un poco el ritmo.",
        "¡Vas muy bien! Escucha de nuevo y repítelo.",
    ],
    'pronunciacion_incorrecta': [  # Score < 50%
        "No te rindas. Escucha cómo suena y vuelve a intentarlo.",
        "¡Tú puedes! Tómate tu tiempo, sin apuro.",
        "Está bien, los campeones practican mucho. ¡Inténtalo de nuevo!",
    ],
    'nivel_completado': [
        "¡NIVEL SUPERADO! ¡Eres una ESTRELLA!",
        "¡Increíble! ¡Conquistaste este nivel! ¡El mapa avanza!",
        "¡Lo hiciste! ¡El reino está más cerca de ser salvo!",
    ],
    'racha_activa': [
        "🔥 ¡{dias} días seguidos! ¡No pares ahora!",
        "¡Llevas {dias} días! ¡Eres imparable!",
    ],
    'insignia_nueva': [
        "¡¡CONSIGUISTE UNA INSIGNIA NUEVA!! Mírala en tu panel.",
        "¡Logro desbloqueado! ¡Eres cada vez más poderoso!",
    ],
    'historia_completada': [
        "¡Historia terminada! ¡Eres todo un lector aventurero!",
        "¡Increíble! ¡Terminaste la historia! ¡El reino agradece tu ayuda!",
    ],
    'desafio_completado': [
        "¡Desafío del día superado! ¡Monedas ganadas!",
        "¡Lo hiciste! ¡Mañana hay un nuevo desafío esperándote!",
    ],
    'camara_objeto_reconocido': [
        "¡Lo vi! ¡Es un {objeto}! ¡Ahora pronúncialo!",
        "¡Eso es un {objeto}! ¡A ver cómo suena!",
    ],
    'guia_niveles': [
        "En este módulo practicas pronunciando palabras. ¡Pulsa grabar y habla!",
    ],
    'guia_camara': [
        "¡Apunta la cámara a cualquier objeto de tu cuarto y yo lo reconozco!",
    ],
    'guia_historias': [
        "Elige una historia y yo te la cuento. ¡Tú decides cómo termina!",
    ],
    'guia_avatar': [
        "¡Aquí puedes vestirme! Con las monedas que ganas puedes comprar cosas nuevas.",
    ],
    'monedas_ganadas': [
        "¡+{cantidad} monedas! ¡Sigue así y podrás comprar cosas nuevas!",
    ],
    'sin_actividad': [  # 3+ días sin entrar
        "¡Te extrañé! El reino necesita tu ayuda. ¿Jugamos un poco?",
        "¡Hola! ¡Hace días que no te veo! ¡Volvamos a practicar!",
    ],
}

def obtener_frase(contexto, **kwargs):
    """
    Retorna una frase aleatoria del contexto dado.
    Los kwargs se usan para formatear variables en la frase (ej: dias=7, objeto='lápiz').
    """
    frases = FRASES_AVATAR.get(contexto, [])
    if not frases:
        return None
    frase = random.choice(frases)
    return frase.format(**kwargs) if kwargs else frase
```

---

## Cómo cada módulo dispara una reacción del avatar

Cada módulo, al completar una acción, debe **pasar el estado y la frase al contexto** del template o al JSON de respuesta (si es AJAX). El avatar se actualiza en consecuencia.

### En vistas que devuelven HTML (render)

```python
from avatar.reactions import obtener_frase

def completar_nivel(request, nivel_id):
    # ... lógica del nivel ...
    
    contexto = {
        'nivel': nivel,
        'resultado': resultado,
        # 👇 Así se le dice al avatar qué hacer
        'avatar_estado_override': 'eufórico',
        'avatar_frase_override': obtener_frase('nivel_completado'),
    }
    return render(request, 'niveles/resultado.html', contexto)
```

En `base.html`, priorizar el `_override` sobre el valor del context processor:

```html
{% with estado=avatar_estado_override|default:avatar_estado %}
{% with frase=avatar_frase_override|default:avatar_frase %}
```

### En vistas que devuelven JSON (AJAX / fetch)

```python
return JsonResponse({
    'status': 'ok',
    'score': score,
    'avatar': {
        'estado': 'feliz',
        'frase': obtener_frase('pronunciacion_correcta'),
    }
})
```

En el JavaScript del módulo, al recibir la respuesta:

```javascript
// En cualquier módulo JS que reciba respuesta del servidor
fetch('/niveles/guardar-progreso/', { ... })
  .then(res => res.json())
  .then(data => {
    if (data.avatar) {
      actualizarAvatar(data.avatar.estado, data.avatar.frase);
    }
  });
```

La función `actualizarAvatar()` debe definirse en `/static/js/avatar.js` como función global:

```javascript
// /static/js/avatar.js — incluir en base.html siempre
function actualizarAvatar(estado, frase) {
  const widget = document.getElementById('avatar-companion');
  const burbuja = document.getElementById('avatar-burbuja');
  
  // Cambiar estado CSS (para cuando no hay imágenes múltiples aún)
  widget.className = `avatar-widget estado-${estado}`;
  
  // Mostrar frase con animación
  if (frase && burbuja) {
    burbuja.textContent = frase;
    burbuja.classList.add('visible');
    // Ocultar después de 5 segundos
    clearTimeout(window._avatarTimeout);
    window._avatarTimeout = setTimeout(() => {
      burbuja.classList.remove('visible');
    }, 5000);
  }
}

// Función de guía contextual — llamar al entrar a cada módulo
function mostrarGuiaModulo(modulo) {
  const guias = {
    'niveles': '¡Pulsa grabar y pronuncia la palabra que ves!',
    'camara': '¡Apunta la cámara a un objeto y yo lo reconozco!',
    'historias': '¡Elige una historia y yo te la cuento!',
    'desafio': '¡Tu desafío de hoy te está esperando!',
    'estadisticas': '¡Aquí puedes ver todo lo que has logrado!',
    'avatar': '¡Con las monedas que ganas puedes comprarme ropa nueva!',
  };
  if (guias[modulo]) {
    actualizarAvatar('base', guias[modulo]);
  }
}
```

---

## Regla de oro del avatar: jamás usar lenguaje negativo

| ❌ NUNCA mostrar | ✅ Usar en su lugar |
|---|---|
| "Incorrecto" | "¡Casi! Inténtalo de nuevo" |
| "Fallaste" | "Tómate tu tiempo, tú puedes" |
| "Error" | "Escucha de nuevo y repítelo" |
| "Mal" | "¡Un poquito más y lo tienes!" |
| Cara de enojo | Cara de empatía / animando |
| Número de score bajo | Estrellas o emoji (nunca el % si es bajo) |

---

## Checklist de implementación para el equipo

### Fase 1 — Temporal (hacer AHORA, sin los assets finales)
- [x] Crear carpeta `/static/img/avatar/` con un único `avatar_base.png` placeholder (puede ser un círculo de color con el logo)
- [x] Implementar `avatar/reactions.py` con el diccionario de frases completo
- [x] Extender `avatar/context_processors.py` para incluir `insignias_pendientes`, `mascota_usuario`, `monedas_usuario`, `racha_dias`, `evento_activo`, `avatar_frase_contextual` (Módulos B y C)
- [x] Agregar el bloque del avatar en `base.html` (imagen + burbuja de diálogo)
- [x] Crear `static/js/avatar_events.js` con la clase `AvatarSystem` (reacciones + frase contextual)
- [x] Incluir `avatar_events.js` en `base.html` para que esté disponible en todos los módulos
- [x] En cada módulo JS (niveles.js, camara.js, etc.), disparar `AVATAR_EVENT` en los eventos clave

### Fase 2 — Cuando estén los assets visuales finales (conectar sin tocar lógica)
- [ ] Reemplazar `avatar_base.png` con el sprite del personaje en estado neutro
- [ ] Agregar `avatar_feliz.png`, `avatar_euforico.png`, etc. con los sprites reales
- [ ] Actualizar el bloque condicional de imagen en `base.html` si se agregan estados nuevos
- [ ] Si el personaje es animado (CSS/SVG), reemplazar el `<img>` por el componente SVG animado
- [x] Conectar el módulo de personalización (ropa, accesorios) al sistema existente (Módulo C, `avatar/personalizar.html`)

### Fase 3 — Personalización completa (Módulo C, completado)
- [x] Módulo de tienda de ítems funcional
- [x] Sistema de equipar/desequipar por categoría
- [x] Casa del avatar
- [x] Mascotas virtuales adoptables

---

## Nota para el equipo

> Todo el sistema está diseñado para que el avatar sea un **punto de conexión central** entre módulos. Cuando se termina un nivel, el avatar reacciona. Cuando se gana una insignia, el avatar lo anuncia. Cuando el niño no ha entrado en días, el avatar lo extraña. Esto no requiere que los assets existan — la lógica, las frases y los estados deben estar programados desde el inicio. El día que lleguen los sprites finales, el sistema simplemente los mostrará. El código no cambia.

---

*DysPlay · Guía de Avatar · v1.0 · Junio 2026*
