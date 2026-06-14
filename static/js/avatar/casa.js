/**
 * DysPlay - Casa del Avatar
 * Gestiona la compra de ítems de la tienda de la casa y la colocación de
 * ítems ya posedidos en los distintos espacios (slots) de la habitación.
 */

(() => {
    // --- Configuración inyectada desde Django ---
    const configElement = document.getElementById('casa-config-data');
    const config = configElement ? JSON.parse(configElement.textContent) : {};
    const URL_COMPRAR_ITEM = config.urlComprarItem || '';
    const URL_COLOCAR_ITEM = config.urlColocarItem || '';
    const CSRF_TOKEN = config.csrfToken || '';

    const mensajeElement = document.getElementById('casa-mensaje');
    const monedasElement = document.getElementById('casa-monedas-valor');

    /**
     * Muestra un mensaje accesible de éxito o error en la parte superior
     * de la página y lo oculta automáticamente tras unos segundos.
     * @param {string} texto - Texto del mensaje a mostrar.
     * @param {boolean} esExito - `true` para estilo de éxito, `false` para error.
     * @returns {void}
     */
    function mostrarMensaje(texto, esExito) {
        if (!mensajeElement) return;

        mensajeElement.textContent = texto;
        mensajeElement.classList.remove('hidden', 'bg-green-50', 'border-green-300', 'text-green-800', 'bg-red-50', 'border-red-300', 'text-red-800');

        if (esExito) {
            mensajeElement.classList.add('bg-green-50', 'border-green-300', 'text-green-800');
        } else {
            mensajeElement.classList.add('bg-red-50', 'border-red-300', 'text-red-800');
        }

        clearTimeout(mensajeElement._timeoutId);
        mensajeElement._timeoutId = setTimeout(() => {
            mensajeElement.classList.add('hidden');
        }, 5000);
    }

    /**
     * Actualiza el saldo de monedas mostrado en la cabecera de la página.
     * @param {number} monedas - Nuevo saldo de monedas del usuario.
     * @returns {void}
     */
    function actualizarMonedas(monedas) {
        if (monedasElement && typeof monedas === 'number') {
            monedasElement.textContent = monedas;
        }
    }

    /**
     * Envía una solicitud de compra de ítem (tienda) al backend.
     * @param {string} itemId - Identificador del ítem a comprar.
     * @param {string|null} slot - Slot de la casa donde colocar el ítem comprado (cama, cuadro, alfombra, lampara) o null.
     * @returns {Promise<Object>} Respuesta JSON del servidor con las claves `exito`, `mensaje` y `monedas`.
     */
    async function comprarItem(itemId, slot) {
        const formData = new FormData();
        formData.append('item_id', itemId);
        if (slot) {
            formData.append('slot', slot);
        }
        formData.append('csrfmiddlewaretoken', CSRF_TOKEN);

        const response = await fetch(URL_COMPRAR_ITEM, {
            method: 'POST',
            body: formData,
            headers: {
                'X-Requested-With': 'XMLHttpRequest'
            }
        });

        return response.json();
    }

    /**
     * Envía una solicitud para colocar un ítem ya posedido en un espacio
     * de la casa, sin realizar ningún cobro.
     * @param {string} itemId - Identificador del ítem a colocar.
     * @param {string} slot - Slot de la casa donde colocar el ítem (cama, cuadro, alfombra, lampara).
     * @returns {Promise<Object>} Respuesta JSON del servidor con las claves `exito`, `mensaje` y `monedas`.
     */
    async function colocarItem(itemId, slot) {
        const formData = new FormData();
        formData.append('item_id', itemId);
        formData.append('slot', slot);
        formData.append('csrfmiddlewaretoken', CSRF_TOKEN);

        const response = await fetch(URL_COLOCAR_ITEM, {
            method: 'POST',
            body: formData,
            headers: {
                'X-Requested-With': 'XMLHttpRequest'
            }
        });

        return response.json();
    }

    /**
     * Gestiona el clic en un botón "Comprar" de la tienda: envía la compra
     * sin asignar slot (los ítems comprados quedan en el inventario) y
     * recarga la página para reflejar el nuevo estado.
     * @param {HTMLElement} boton - Botón "Comprar" pulsado.
     * @returns {Promise<void>}
     */
    async function manejarCompra(boton) {
        const itemId = boton.dataset.itemId;
        const itemNombre = boton.dataset.itemNombre;

        boton.disabled = true;

        try {
            const resultado = await comprarItem(itemId, null);

            if (resultado.exito) {
                actualizarMonedas(resultado.monedas);
                mostrarMensaje(`¡Compraste "${itemNombre}"! Ya está en "Mis ítems de habitación".`, true);
                setTimeout(() => window.location.reload(), 1200);
            } else {
                mostrarMensaje(resultado.mensaje || 'No se pudo completar la compra.', false);
                boton.disabled = false;
            }
        } catch (error) {
            console.error('Error al comprar ítem:', error);
            mostrarMensaje('Ocurrió un error de conexión. Inténtalo de nuevo.', false);
            boton.disabled = false;
        }
    }

    /**
     * Gestiona el clic en un botón "Colocar" de "Mis ítems de habitación":
     * usa el selector de slot asociado para asignar el ítem (ya posedido)
     * a un espacio de la casa.
     * @param {HTMLElement} boton - Botón "Colocar" pulsado.
     * @returns {Promise<void>}
     */
    async function manejarColocacion(boton) {
        const itemId = boton.dataset.itemId;
        const itemNombre = boton.dataset.itemNombre;
        const selector = document.getElementById(`slot-select-${itemId}`);
        const slot = selector ? selector.value : null;

        boton.disabled = true;

        try {
            const resultado = await colocarItem(itemId, slot);

            if (resultado.exito) {
                actualizarMonedas(resultado.monedas);
                mostrarMensaje(`¡"${itemNombre}" colocado en tu habitación!`, true);
                setTimeout(() => window.location.reload(), 1200);
            } else {
                mostrarMensaje(resultado.mensaje || 'No se pudo colocar el ítem.', false);
                boton.disabled = false;
            }
        } catch (error) {
            console.error('Error al colocar ítem:', error);
            mostrarMensaje('Ocurrió un error de conexión. Inténtalo de nuevo.', false);
            boton.disabled = false;
        }
    }

    document.addEventListener('DOMContentLoaded', () => {
        document.querySelectorAll('.btn-comprar').forEach((boton) => {
            boton.addEventListener('click', () => manejarCompra(boton));
        });

        document.querySelectorAll('.btn-colocar').forEach((boton) => {
            boton.addEventListener('click', () => manejarColocacion(boton));
        });
    });
})();
