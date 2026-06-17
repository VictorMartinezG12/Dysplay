# 🔒 PLAN DE IMPLEMENTACIÓN — BLOQUEO DE ZONAS EN MÓDULO NIVELES

> **Para Claude Code** · Alcance: únicamente `niveles/` (modelos, admin, migraciones, validaciones)
> **Regla de seguridad:** No modificar `base.html`, archivos de configuración global de diseño, ni otros módulos fuera de `niveles/`. No tocar el rediseño visual del mapa que está en progreso — esto es exclusivamente sobre la estructura de datos y validación.

---

## Contexto del problema

Actualmente, al crear un nivel nuevo, se puede asignar a cualquier zona existente (Bosque Encantado, Montaña de las Letras, etc.) sin restricción. Esto es un riesgo: una vez que una zona ya tiene su secuencia de niveles definida y el camino visual ya está diseñado para esa cantidad exacta de niveles, agregar un nivel nuevo a una zona "ya cerrada" rompería la coherencia del orden global del camino (el `orden_en_zona` automático calcularía una posición que ya no corresponde a un lugar libre real en el camino visual).

**Decisión de diseño confirmada (no requiere debate):** Una vez que el diseñador del proyecto considera que una zona está "completa" (su cantidad definitiva de niveles ya fue decidida), esa zona debe poder marcarse como **cerrada**, impidiendo que se agreguen niveles nuevos a ella — tanto desde el admin de Django como desde cualquier futuro panel de administración propio, y como garantía de integridad incluso si se intenta por otra vía (shell, API, etc.).

**Principio de capas de protección:** Esta restricción debe implementarse en DOS capas independientes:
1. **Capa de datos/validación** (modelo) → la protección real, a prueba de cualquier vía de acceso.
2. **Capa de interfaz** (admin) → ocultar la opción para evitar el error antes de que ocurra, como ayuda de usabilidad.

La capa 1 es la que garantiza la integridad. La capa 2 es solo conveniencia — nunca debe ser la única protección.

---

## Paso 0 — Diagnóstico previo (hacer primero, reportar antes de continuar)

Antes de implementar nada, verificar y reportar:

- [ ] ¿El campo `zona` en el modelo `Nivel` es un `CharField` con `choices`, o existe un modelo `Zona` separado con `ForeignKey`?
- [ ] ¿Dónde está implementada actualmente la lógica de orden automático (`orden_en_zona`) que se hizo en una iteración anterior? Confirmar el método `save()` actual del modelo `Nivel` antes de modificarlo, para no romper esa lógica ya funcionando.
- [ ] ¿Existen ya niveles guardados en la base de datos? Si es así, la migración debe contemplar un valor por defecto seguro (`cerrada=False`) para no afectar datos existentes.

**Reportar los hallazgos antes de proceder al Paso 1.**

---

## Paso 1 — Asegurar que `Zona` sea un modelo propio (si no lo es ya)

Si actualmente `zona` es un `CharField` con `choices` dentro del modelo `Nivel`, esto debe convertirse en un modelo independiente `Zona` con relación `ForeignKey` desde `Nivel`. Esto es necesario porque el estado "cerrada" es una propiedad de la zona misma, no de cada nivel individual.

```python
# niveles/models.py

class Zona(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    orden = models.PositiveSmallIntegerField(help_text="Posición de esta zona en la secuencia general del camino")
    cerrada = models.BooleanField(
        default=False,
        help_text="Si está marcada, no se pueden agregar niveles nuevos a esta zona."
    )
    descripcion = models.TextField(blank=True)
    # Mantener cualquier campo visual que ya exista relacionado a la zona (fondo, narrativa_intro, etc.)
    # No eliminar campos existentes sin antes confirmar conmigo que no se usan en otro lado.

    class Meta:
        ordering = ['orden']
        verbose_name = "Zona"
        verbose_name_plural = "Zonas"

    def __str__(self):
        return self.nombre
```

**Si ya existe un modelo `Zona` separado:** omitir este paso y solo agregar el campo `cerrada` mediante una migración, sin recrear el modelo completo.

**Si la conversión de `CharField` a `ForeignKey` es necesaria:** esto requiere una migración de datos cuidadosa (no solo de esquema) para no perder la información de zona de los niveles ya existentes. Mostrarme el plan de migración de datos antes de ejecutarla.

---

## Paso 2 — Validación a nivel de modelo (la protección real)

En el modelo `Nivel`, agregar la validación que impide la creación de niveles nuevos en zonas cerradas:

```python
# niveles/models.py

from django.core.exceptions import ValidationError

class Nivel(models.Model):
    zona = models.ForeignKey(Zona, on_delete=models.PROTECT, related_name='niveles')
    orden_en_zona = models.PositiveSmallIntegerField(null=True, blank=True)
    # ... resto de campos existentes, no modificar

    def clean(self):
        super().clean()
        # Solo bloquea la CREACIÓN de niveles nuevos, nunca la edición de uno ya existente
        if self.zona_id and self.zona.cerrada and self.pk is None:
            raise ValidationError({
                'zona': f"La zona '{self.zona.nombre}' está cerrada. No se pueden agregar niveles nuevos aquí."
            })

    def save(self, *args, **kwargs):
        self.full_clean()  # asegura que clean() se ejecute también fuera del admin (shell, scripts, etc.)
        if self.orden_en_zona is None:
            ultimo = Nivel.objects.filter(zona=self.zona).order_by('-orden_en_zona').first()
            self.orden_en_zona = (ultimo.orden_en_zona + 1) if ultimo else 1
        super().save(*args, **kwargs)
```

**Importante:** `full_clean()` dentro de `save()` asegura que esta validación se respete incluso si alguien crea un nivel directamente por código (`Nivel.objects.create(...)`) o desde el shell de Django, no solo desde formularios. Esto es lo que la convierte en una protección de verdad y no solo una validación de formulario.

**No romper la lógica de orden automático ya existente** — el bloque de `orden_en_zona` debe mantenerse exactamente como ya funciona, solo se le agrega la llamada a `full_clean()` antes.

---

## Paso 3 — Ocultar en el admin de Django (capa de usabilidad, no de seguridad)

```python
# niveles/admin.py

from django import forms
from django.contrib import admin
from .models import Nivel, Zona

class NivelAdminForm(forms.ModelForm):
    class Meta:
        model = Nivel
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Si se está EDITANDO un nivel existente, mostrar su zona actual aunque esté cerrada
        # (para no impedir la edición de niveles ya creados en esa zona)
        if self.instance and self.instance.pk:
            queryset_zonas = Zona.objects.filter(
                models.Q(cerrada=False) | models.Q(pk=self.instance.zona_id)
            )
        else:
            # Si se está CREANDO un nivel nuevo, solo mostrar zonas abiertas
            queryset_zonas = Zona.objects.filter(cerrada=False)
        self.fields['zona'].queryset = queryset_zonas


class NivelAdmin(admin.ModelAdmin):
    form = NivelAdminForm
    list_display = ['nombre', 'zona', 'orden_en_zona']  # ajustar según campos reales existentes
    list_filter = ['zona']


class ZonaAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'orden', 'cerrada']
    list_editable = ['cerrada']  # permite marcar/desmarcar cerrada directamente desde la lista


admin.site.register(Zona, ZonaAdmin)
admin.site.register(Nivel, NivelAdmin)
```

**Nota sobre `list_editable = ['cerrada']`:** esto permite, desde la vista de lista de zonas en el admin, marcar el checkbox de "cerrada" directamente sin entrar a editar cada zona individualmente — útil para el flujo de trabajo de "terminé de diseñar esta zona, la cierro".

---

## Paso 4 — Migración

Generar la migración correspondiente a los cambios del modelo:

```bash
python manage.py makemigrations niveles
python manage.py migrate
```

**Antes de ejecutar `migrate`:** mostrarme el contenido del archivo de migración generado para revisar que no haya pérdida de datos, especialmente si el Paso 1 implicó convertir un `CharField` a `ForeignKey`.

---

## Paso 5 — Verificación

Después de implementar, confirmar manualmente (reportar el resultado):

- [ ] Crear una zona de prueba, marcarla como `cerrada=True`, e intentar crear un nivel nuevo en ella desde el admin → debe rechazarse con el mensaje de error definido.
- [ ] Intentar lo mismo desde el shell de Django (`Nivel.objects.create(zona=zona_cerrada, ...)`) → debe lanzar la misma `ValidationError`.
- [ ] Editar un nivel ya existente que pertenece a una zona cerrada (sin cambiar su zona) → debe permitirse sin error.
- [ ] Confirmar que el selector de zona en el formulario de creación del admin ya no muestra las zonas cerradas como opción.
- [ ] Confirmar que la lógica de `orden_en_zona` automático sigue funcionando igual que antes para zonas abiertas.

---

## Recordatorio de alcance

Esta tarea es únicamente sobre la estructura de datos y validación del módulo `niveles`. No avanzar hacia:
- El rediseño visual del mapa (tarea separada, en progreso)
- El panel de administrador propio (tarea futura, no iniciar todavía)
- Otros módulos del proyecto

Si en el proceso se detecta que el campo `zona` actual tiene alguna dependencia inesperada en otro módulo (por ejemplo, si `estadisticas` o `desafio` ya hacen referencia directa al valor de zona), **detenerse y reportarlo antes de continuar**, sin modificar esos otros módulos.
