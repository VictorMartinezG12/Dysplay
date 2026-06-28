/**
 * DysPlay - Casa del Avatar
 * Gestiona los 8 hotspots de la habitación (armario + 7 slots de mueble),
 * sus modales y las acciones AJAX de compra/colocación/equipado, todo sin
 * recargar la página completa.
 */

(() => {
    // --- Configuración inyectada desde Django ---
    const configElement = document.getElementById('casa-config-data');
    const config = configElement ? JSON.parse(configElement.textContent) : {};
    const URL_COMPRAR_ITEM = config.urlComprarItem || '';
    const URL_COLOCAR_ITEM = config.urlColocarItem || '';
    const URL_EQUIPAR_ITEM = config.urlEquiparItem || '';
    const URL_COMPRAR_Y_EQUIPAR = config.urlComprarYEquipar || '';
    const URL_DESEQUIPAR_ITEM = config.urlDesequiparItem || '';
    const CSRF_TOKEN = config.csrfToken || '';
    const SLOT_CATEGORIAS = config.slotCategorias || {};

    const mensajeElement = document.getElementById('casa-mensaje');
    const monedasElement = document.getElementById('casa-monedas-valor');

    // Slot actualmente abierto en el modal pequeño ("modal-slot").
    let slotActivo = null;

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
     * Actualiza el saldo de monedas mostrado en la cabecera de la página
     * y, si existe, dentro del modal de armario.
     * @param {number} monedas - Nuevo saldo de monedas del usuario.
     * @returns {void}
     */
    function actualizarMonedas(monedas) {
        if (typeof monedas !== 'number') return;
        if (monedasElement) monedasElement.textContent = monedas;
        const monedasArmario = document.getElementById('armario-monedas-valor');
        if (monedasArmario) monedasArmario.textContent = monedas;
    }

    /**
     * Abre un modal por su id, gestionando el foco y el scroll del body.
     * @param {string} modalId - Id del contenedor del modal.
     * @returns {void}
     */
    function abrirModal(modalId) {
        const modal = document.getElementById(modalId);
        if (!modal) return;
        modal.classList.remove('hidden');
        document.body.classList.add('overflow-hidden');
        const botonCerrar = modal.querySelector('[data-cerrar-modal]');
        if (botonCerrar) botonCerrar.focus();

        // El widget flotante global queda detrás del overlay oscuro del modal,
        // visible pero atenuado (z-100 contra z-110) mientras el avatar de
        // dentro del modal se ve nítido y reacciona al equipar/comprar — da la
        // sensación de "dos personajes, uno congelado". Se oculta mientras
        // haya un modal abierto para que solo se vea el avatar interactivo.
        const widgetFlotante = document.getElementById('avatar-master-container');
        if (widgetFlotante) widgetFlotante.classList.add('hidden');
    }

    /**
     * Cierra un modal por su id y restaura el scroll del body.
     * @param {string} modalId - Id del contenedor del modal.
     * @returns {void}
     */
    function cerrarModal(modalId) {
        const modal = document.getElementById(modalId);
        if (!modal) return;
        modal.classList.add('hidden');
        document.body.classList.remove('overflow-hidden');

        // Solo se vuelve a mostrar el widget flotante si ya no queda ningún
        // otro modal de la habitación abierto.
        const otroModalAbierto = ['modal-armario', 'modal-slot'].some((id) => {
            const otro = document.getElementById(id);
            return otro && id !== modalId && !otro.classList.contains('hidden');
        });
        if (!otroModalAbierto) {
            const widgetFlotante = document.getElementById('avatar-master-container');
            if (widgetFlotante) widgetFlotante.classList.remove('hidden');
        }
    }

    /**
     * Filtra las tarjetas de ítem del modal de slot ("Tengo"/"Tienda") para
     * mostrar solo las que correspondan a las categorías permitidas del
     * slot actualmente seleccionado.
     * @param {string} slot - Slot de la casa (mesa, estante, cama, silla, cuadro, lampara, alfombra).
     * @returns {void}
     */
    function filtrarItemsPorSlot(slot) {
        const categoriasPermitidas = SLOT_CATEGORIAS[slot] || [];
        document.querySelectorAll('.slot-item-card').forEach((tarjeta) => {
            const categoria = tarjeta.dataset.categoria;
            tarjeta.classList.toggle('hidden', !categoriasPermitidas.includes(categoria));
        });
    }

    /**
     * Abre el modal pequeño de un slot de mueble/decoración: actualiza el
     * título, filtra los ítems visibles por categoría permitida y deja
     * activa la sub-pestaña "Tengo".
     * @param {string} slot - Slot de la casa a configurar en el modal.
     * @returns {void}
     */
    function abrirModalSlot(slot) {
        slotActivo = slot;

        const titulo = document.getElementById('modal-slot-titulo');
        const nombresSlot = {
            mesa: 'Mesa', estante: 'Estante de libros', cama: 'Cama',
            silla: 'Silla', cuadro: 'Cuadro', lampara: 'Lámpara', alfombra: 'Alfombra',
        };
        if (titulo) titulo.textContent = `Elegir ${nombresSlot[slot] || 'ítem'}`;

        filtrarItemsPorSlot(slot);

        // Reiniciar a la sub-pestaña "Tengo" cada vez que se abre.
        const tabTengo = document.querySelector('[data-slot-subtab="tengo"]');
        if (tabTengo) tabTengo.click();

        abrirModal('modal-slot');
    }

    /**
     * Envía una solicitud de compra de ítem (tienda de la casa) al backend.
     * @param {string} itemId - Identificador del ítem a comprar.
     * @param {string|null} slot - Slot de la casa donde colocar el ítem comprado, o null.
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
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
        });

        return response.json();
    }

    /**
     * Envía una solicitud para colocar un ítem ya posedido en un slot de la casa.
     * @param {string} itemId - Identificador del ítem a colocar.
     * @param {string} slot - Slot de la casa donde colocar el ítem.
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
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
        });

        return response.json();
    }

    /**
     * Actualiza en el DOM la imagen del hotspot indicado, sin recargar la
     * página, agregando o reemplazando la imagen colocada en ese slot.
     * @param {string} slot - Slot de la casa actualizado.
     * @param {string} itemNombre - Nombre del ítem, usado en el `alt` accesible.
     * @param {string} imagenUrl - URL de la imagen del ítem colocado.
     * @returns {void}
     */
    function actualizarImagenSlot(slot, itemNombre, imagenUrl) {
        const hotspot = document.querySelector(`.room-hotspot[data-slot="${slot}"]`);
        if (!hotspot) return;

        let img = document.querySelector(`.room-item-placed[data-slot-img="${slot}"]`);
        if (!img) {
            img = document.createElement('img');
            img.className = 'room-item-placed';
            img.dataset.slotImg = slot;
            img.style.left = hotspot.style.left;
            img.style.top = hotspot.style.top;
            img.style.width = hotspot.style.width;
            img.style.height = hotspot.style.height;
            hotspot.insertAdjacentElement('afterend', img);
        }
        img.src = imagenUrl;
        img.alt = `Ítem colocado: ${itemNombre}`;
    }

    /**
     * Gestiona la compra (sin colocar) de un ítem desde la pestaña "Tienda"
     * del modal de slot: compra el ítem, lo coloca de inmediato en el slot
     * activo y actualiza el DOM sin recargar la página.
     * @param {HTMLElement} boton - Botón "Comprar" pulsado.
     * @returns {Promise<void>}
     */
    async function manejarCompraEnSlot(boton) {
        const itemId = boton.dataset.itemId;
        const itemNombre = boton.dataset.itemNombre;
        if (!slotActivo) return;

        boton.disabled = true;
        try {
            const resultado = await comprarItem(itemId, slotActivo);
            if (resultado.exito) {
                actualizarMonedas(resultado.monedas);
                const tarjeta = boton.closest('.slot-item-card');
                const imagenElemento = tarjeta ? tarjeta.querySelector('img') : null;
                const imagenUrl = imagenElemento ? imagenElemento.src : '';
                actualizarImagenSlot(slotActivo, itemNombre, imagenUrl);
                mostrarMensaje(`¡Compraste y colocaste "${itemNombre}"!`, true);
                if (tarjeta) tarjeta.remove();
                cerrarModal('modal-slot');
            } else {
                mostrarMensaje(resultado.mensaje || 'No se pudo completar la compra.', false);
                boton.disabled = false;
            }
        } catch (error) {
            console.error('Error al comprar ítem de la casa:', error);
            mostrarMensaje('Ocurrió un error de conexión. Inténtalo de nuevo.', false);
            boton.disabled = false;
        }
    }

    /**
     * Gestiona la colocación de un ítem ya posedido desde la pestaña "Tengo"
     * del modal de slot, actualizando el DOM sin recargar la página.
     * @param {HTMLElement} boton - Botón "Colocar" pulsado.
     * @returns {Promise<void>}
     */
    async function manejarColocacionEnSlot(boton) {
        const itemId = boton.dataset.itemId;
        const itemNombre = boton.dataset.itemNombre;
        if (!slotActivo) return;

        boton.disabled = true;
        try {
            const resultado = await colocarItem(itemId, slotActivo);
            if (resultado.exito) {
                actualizarMonedas(resultado.monedas);
                const tarjeta = boton.closest('.slot-item-card');
                const imagenElemento = tarjeta ? tarjeta.querySelector('img') : null;
                const imagenUrl = imagenElemento ? imagenElemento.src : '';
                actualizarImagenSlot(slotActivo, itemNombre, imagenUrl);
                mostrarMensaje(`¡"${itemNombre}" colocado en tu habitación!`, true);
                cerrarModal('modal-slot');
            } else {
                mostrarMensaje(resultado.mensaje || 'No se pudo colocar el ítem.', false);
                boton.disabled = false;
            }
        } catch (error) {
            console.error('Error al colocar ítem de la casa:', error);
            mostrarMensaje('Ocurrió un error de conexión. Inténtalo de nuevo.', false);
            boton.disabled = false;
        }
    }

    /**
     * Activa visualmente una sub-pestaña ("Tengo"/"Tienda") del modal de slot.
     * @param {string} destino - Sub-pestaña a activar ("tengo" o "tienda").
     * @returns {void}
     */
    function activarSlotSubtab(destino) {
        document.querySelectorAll('.slot-subtab-btn').forEach((boton) => {
            const activo = boton.dataset.slotSubtab === destino;
            boton.setAttribute('aria-selected', activo ? 'true' : 'false');
            boton.classList.toggle('bg-purple-600', activo);
            boton.classList.toggle('text-white', activo);
            boton.classList.toggle('bg-gray-100', !activo);
            boton.classList.toggle('text-gray-500', !activo);
        });

        const panelTengo = document.getElementById('modal-slot-panel-tengo');
        const panelTienda = document.getElementById('modal-slot-panel-tienda');
        if (panelTengo) panelTengo.classList.toggle('hidden', destino !== 'tengo');
        if (panelTienda) panelTienda.classList.toggle('hidden', destino !== 'tienda');
    }

    document.addEventListener('DOMContentLoaded', () => {
        // Hotspots de la habitación: abren el modal de armario o el de slot.
        document.querySelectorAll('.room-hotspot').forEach((hotspot) => {
            hotspot.addEventListener('click', () => {
                const slot = hotspot.dataset.slot;
                const modalTarget = hotspot.dataset.modalTarget;

                if (modalTarget === 'modal-armario') {
                    abrirModal('modal-armario');
                } else {
                    abrirModalSlot(slot);
                }
            });
        });

        // Botón "Mi Armario" del encabezado.
        const btnAbrirArmario = document.getElementById('btn-abrir-armario');
        if (btnAbrirArmario) {
            btnAbrirArmario.addEventListener('click', () => abrirModal('modal-armario'));
        }

        // Botones de cerrar modal (X) y clic fuera del contenido.
        document.querySelectorAll('[data-cerrar-modal]').forEach((boton) => {
            boton.addEventListener('click', () => cerrarModal(boton.dataset.cerrarModal));
        });
        document.querySelectorAll('#modal-armario, #modal-slot').forEach((modal) => {
            modal.addEventListener('click', (evento) => {
                if (evento.target === modal) cerrarModal(modal.id);
            });
        });
        document.addEventListener('keydown', (evento) => {
            if (evento.key === 'Escape') {
                cerrarModal('modal-armario');
                cerrarModal('modal-slot');
            }
        });

        // Sub-tabs Tengo/Tienda del modal de slot.
        document.querySelectorAll('[data-slot-subtab]').forEach((boton) => {
            boton.addEventListener('click', () => activarSlotSubtab(boton.dataset.slotSubtab));
        });

        // Delegación de eventos para los botones de comprar/colocar dentro
        // del modal de slot (el contenido no cambia de nodo, así que la
        // delegación directa también funcionaría, pero se usa delegación
        // por robustez ante futuras re-renderizaciones parciales).
        document.body.addEventListener('click', (evento) => {
            const botonComprar = evento.target.closest('[data-comprar-item]');
            if (botonComprar) {
                manejarCompraEnSlot(botonComprar);
                return;
            }
            const botonColocar = evento.target.closest('[data-colocar-item]');
            if (botonColocar) {
                manejarColocacionEnSlot(botonColocar);
            }
        });
    });

    // Expone utilidades de monedas/mensaje para que armario.js (cargado por
    // separado dentro del modal de armario) pueda reutilizarlas sin duplicar
    // lógica ni depender del orden de carga de scripts.
    window.dysPlayCasa = {
        actualizarMonedas,
        mostrarMensaje,
        urlEquiparItem: URL_EQUIPAR_ITEM,
        urlComprarYEquipar: URL_COMPRAR_Y_EQUIPAR,
        urlDesequiparItem: URL_DESEQUIPAR_ITEM,
        csrfToken: CSRF_TOKEN,
    };
})();
