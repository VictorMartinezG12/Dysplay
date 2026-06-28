/**
 * DysPlay - Armario del Avatar ("paper doll")
 * Gestiona las pestañas de zona del cuerpo (cabello, torso superior, torso
 * inferior, calzado, accesorios), las sub-pestañas "Tengo"/"Tienda" de cada
 * una, y las acciones AJAX de equipar / comprar-y-equipar, actualizando la
 * vista previa del avatar sin recargar la página.
 *
 * Se carga tanto dentro del modal de armario de `casa.html` como en el
 * acceso directo `personalizar.html`; en ambos casos el contenido viene del
 * mismo partial `_armario_contenido.html`, así que el comportamiento es
 * idéntico en los dos contextos.
 */

(() => {
    /**
     * Posiciones (%) de cada capa sobre el lienzo de referencia 500x500,
     * calcadas de las que ya renderiza el servidor en `_armario_contenido.html`.
     * Las 3 subcategorías de accesorio usan posiciones distintas para que no
     * se apilen exactamente en el mismo lugar (sombrero arriba de la cabeza,
     * gafas a la altura de los ojos, reloj cerca de la muñeca).
     * @type {Object<string, {left: string, top: string, width: string, height: string, z: number}>}
     */
    const POSICIONES_CAPA = {
        ropa_inferior: { left: '31%', top: '50%', width: '40.2%', height: '40.2%', z: 12 },
        calzado: { left: '31.8%', top: '72.8%', width: '36.4%', height: '27.2%', z: 14 },
        ropa_superior: { left: '28.2%', top: '37.4%', width: '43.6%', height: '35.4%', z: 20 },
        ropa: { left: '28.2%', top: '37.4%', width: '43.6%', height: '35.4%', z: 20 },
        cabello: { left: '19.4%', top: '-1.2%', width: '56.4%', height: '56.4%', z: 30 },
    };

    /**
     * Posiciones (%) específicas para cada subcategoría de accesorio, para
     * que sombrero/gafas/reloj no se apilen en el mismo lugar.
     * @type {Object<string, {left: string, top: string, width: string, height: string, z: number}>}
     */
    const POSICIONES_ACCESORIO = {
        sombrero: { left: '24%', top: '-4%', width: '48%', height: '34%', z: 40 },
        gafas: { left: '28%', top: '24%', width: '42%', height: '14%', z: 40 },
        reloj: { left: '9%', top: '49%', width: '15%', height: '15%', z: 40 },
        otro: { left: '30%', top: '-2%', width: '40%', height: '30%', z: 40 },
    };

    let elementosCacheados = null;

    /**
     * Obtiene (y cachea) las referencias a los elementos del DOM del armario.
     * Se vuelve a calcular solo si todavía no se había hecho, ya que el
     * contenido del partial no se reemplaza dinámicamente (solo se muestra
     * dentro de un modal ya presente en el DOM).
     * @returns {{mensaje: HTMLElement|null, capas: HTMLElement|null}}
     */
    function obtenerElementos() {
        if (!elementosCacheados) {
            elementosCacheados = {
                mensaje: document.getElementById('armario-mensaje'),
                capas: document.getElementById('armario-layers-items'),
            };
        }
        return elementosCacheados;
    }

    /**
     * Obtiene la configuración (URLs + token CSRF) necesaria para las
     * peticiones AJAX del armario. Prioriza `window.dysPlayCasa` (modal de
     * armario embebido en `casa.html`, donde `casa.js` ya expone esas
     * mismas URLs); si no existe, lee el `json_script` propio de
     * `personalizar.html` (acceso directo por URL, sin `casa.js` cargado).
     * @returns {{urlEquiparItem: string, urlComprarYEquipar: string, csrfToken: string}}
     */
    function obtenerConfig() {
        if (window.dysPlayCasa) {
            return {
                urlEquiparItem: window.dysPlayCasa.urlEquiparItem,
                urlComprarYEquipar: window.dysPlayCasa.urlComprarYEquipar,
                urlDesequiparItem: window.dysPlayCasa.urlDesequiparItem || '',
                csrfToken: window.dysPlayCasa.csrfToken,
            };
        }
        const elementoConfig = document.getElementById('armario-config-data');
        if (elementoConfig) {
            try {
                return JSON.parse(elementoConfig.textContent);
            } catch (error) {
                console.error('Error al leer la configuración del armario:', error);
            }
        }
        return { urlEquiparItem: '', urlComprarYEquipar: '', urlDesequiparItem: '', csrfToken: '' };
    }

    /**
     * Muestra un mensaje accesible de éxito o error dentro del armario.
     * @param {string} texto - Texto del mensaje a mostrar.
     * @param {boolean} esExito - `true` para estilo de éxito, `false` para error.
     * @returns {void}
     */
    function mostrarMensaje(texto, esExito) {
        const { mensaje } = obtenerElementos();
        if (!mensaje) return;

        mensaje.textContent = texto;
        mensaje.classList.remove('hidden', 'bg-green-50', 'border-green-300', 'text-green-800', 'bg-red-50', 'border-red-300', 'text-red-800');
        mensaje.classList.add(esExito ? 'bg-green-50' : 'bg-red-50', esExito ? 'border-green-300' : 'border-red-300', esExito ? 'text-green-800' : 'text-red-800');

        clearTimeout(mensaje._timeoutId);
        mensaje._timeoutId = setTimeout(() => mensaje.classList.add('hidden'), 5000);
    }

    /**
     * Actualiza el contador de monedas, reutilizando la utilidad de casa.js
     * si está disponible (modal de armario dentro de casa.html) o, si no,
     * actualizando directamente el elemento local del armario.
     * @param {number} monedas - Nuevo saldo de monedas del usuario.
     * @returns {void}
     */
    function actualizarMonedas(monedas) {
        if (typeof monedas !== 'number') return;
        if (window.dysPlayCasa && typeof window.dysPlayCasa.actualizarMonedas === 'function') {
            window.dysPlayCasa.actualizarMonedas(monedas);
        }
        const monedasArmario = document.getElementById('armario-monedas-valor');
        if (monedasArmario) monedasArmario.textContent = monedas;
    }

    /**
     * Activa visualmente una pestaña de zona del cuerpo (cabello, torso
     * superior, torso inferior, calzado, accesorios) y muestra su panel.
     * @param {string} zona - Id de la zona a activar.
     * @returns {void}
     */
    function activarZona(zona) {
        document.querySelectorAll('.zona-tab-btn').forEach((boton) => {
            const activo = boton.dataset.zona === zona;
            boton.setAttribute('aria-selected', activo ? 'true' : 'false');
            boton.classList.toggle('bg-purple-600', activo);
            boton.classList.toggle('text-white', activo);
            boton.classList.toggle('border-purple-800', activo);
            boton.classList.toggle('shadow-md', activo);
            boton.classList.toggle('bg-gray-50', !activo);
            boton.classList.toggle('text-gray-500', !activo);
            boton.classList.toggle('border-gray-200', !activo);
        });

        document.querySelectorAll('.zona-panel').forEach((panel) => {
            panel.classList.toggle('hidden', panel.dataset.zona !== zona);
        });
    }

    /**
     * Activa visualmente una sub-pestaña ("Tengo"/"Tienda") dentro de un
     * grupo (zona simple del cuerpo o sub-sección de accesorio).
     * @param {string} grupo - Id del grupo de sub-pestañas (ej. "cabello" o "accesorio-sombrero").
     * @param {string} destino - Sub-pestaña a activar ("tengo" o "tienda").
     * @returns {void}
     */
    function activarSubtab(grupo, destino) {
        document.querySelectorAll(`[data-subtab][data-subtab-group="${grupo}"]`).forEach((boton) => {
            const activo = boton.dataset.subtabTarget === destino;
            boton.setAttribute('aria-selected', activo ? 'true' : 'false');
            boton.classList.toggle('bg-purple-600', activo);
            boton.classList.toggle('text-white', activo);
            boton.classList.toggle('bg-gray-100', !activo);
            boton.classList.toggle('text-gray-500', !activo);
        });

        document.querySelectorAll(`[data-subpanel][data-subtab-group="${grupo}"]`).forEach((panel) => {
            panel.classList.toggle('hidden', panel.dataset.subtabTarget !== destino);
        });
    }

    /**
     * Crea o actualiza la capa visual de una prenda/accesorio equipado en la
     * vista previa del avatar, con un pequeño efecto de aparición.
     * @param {string} categoria - Categoría del ítem (cabello, ropa_superior, etc., o "accesorio").
     * @param {string} subcategoria - Subcategoría (solo relevante si categoria es "accesorio").
     * @param {string} imagenUrl - URL de la imagen del ítem equipado.
     * @returns {void}
     */
    function actualizarCapaPreview(categoria, subcategoria, imagenUrl) {
        const { capas } = obtenerElementos();
        if (!capas) return;

        const esAccesorio = categoria === 'accesorio';
        let capa = esAccesorio
            ? capas.querySelector(`img[data-cat="accesorio"][data-subcategoria="${subcategoria}"]`)
            : capas.querySelector(`img[data-cat="${categoria}"]`);

        if (!capa) {
            capa = document.createElement('img');
            capa.dataset.cat = categoria;
            if (esAccesorio) capa.dataset.subcategoria = subcategoria;
            capa.className = 'absolute object-contain transition-all duration-300 transform scale-0';
            capa.alt = '';

            const posicion = esAccesorio
                ? (POSICIONES_ACCESORIO[subcategoria] || POSICIONES_ACCESORIO.otro)
                : (POSICIONES_CAPA[categoria] || { left: '0%', top: '0%', width: '100%', height: '100%', z: 20 });

            capa.style.left = posicion.left;
            capa.style.top = posicion.top;
            capa.style.width = posicion.width;
            capa.style.height = posicion.height;
            capa.style.zIndex = String(posicion.z);
            capas.appendChild(capa);
        }

        capa.src = imagenUrl;
        setTimeout(() => capa.classList.remove('scale-0'), 10);
    }

    /**
     * Marca como equipado, en el grid de ítems, el botón correspondiente y
     * desmarca cualquier otro de la misma clave de exclusividad (misma
     * categoría, o misma subcategoría si es un accesorio).
     * @param {string} itemId - Identificador del ítem recién equipado.
     * @param {string} categoria - Categoría del ítem equipado.
     * @param {string} subcategoria - Subcategoría del ítem (accesorios).
     * @returns {void}
     */
    function marcarEquipadoEnGrid(itemId, categoria, subcategoria) {
        const selectorGrupo = categoria === 'accesorio'
            ? `[data-equipar-item][data-item-categoria="accesorio"][data-item-subcategoria="${subcategoria}"]`
            : `[data-equipar-item][data-item-categoria="${categoria}"]`;

        document.querySelectorAll(selectorGrupo).forEach((boton) => {
            const esEsteItem = boton.dataset.itemId === String(itemId);
            boton.classList.toggle('border-purple-500', esEsteItem);
            boton.classList.toggle('bg-purple-50', esEsteItem);
            boton.classList.toggle('shadow-inner', esEsteItem);
            boton.classList.toggle('border-gray-100', !esEsteItem);
            boton.classList.toggle('bg-gray-50', !esEsteItem);
            boton.dataset.equipado = esEsteItem ? 'true' : 'false';
        });
    }

    /**
     * Elimina la capa visual de un ítem de la vista previa del avatar.
     * @param {string} categoria - Categoría del ítem.
     * @param {string} subcategoria - Subcategoría (accesorios).
     * @returns {void}
     */
    function quitarCapaPreview(categoria, subcategoria) {
        const { capas } = obtenerElementos();
        if (!capas) return;
        const esAccesorio = categoria === 'accesorio';
        const capa = esAccesorio
            ? capas.querySelector(`img[data-cat="accesorio"][data-subcategoria="${subcategoria}"]`)
            : capas.querySelector(`img[data-cat="${categoria}"]`);
        if (capa) {
            capa.classList.add('scale-0');
            setTimeout(() => capa.remove(), 300);
        }
    }

    /**
     * Envía la solicitud para desequipar (quitar) un ítem sin eliminarlo del inventario.
     * @param {string} itemId - Identificador del ítem a desequipar.
     * @returns {Promise<Object>} Respuesta JSON del servidor.
     */
    async function desequiparItemPeticion(itemId) {
        const { urlDesequiparItem, csrfToken } = obtenerConfig();
        const formData = new FormData();
        formData.append('item_id', itemId);
        formData.append('csrfmiddlewaretoken', csrfToken);
        const response = await fetch(urlDesequiparItem, {
            method: 'POST',
            body: formData,
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
        });
        return response.json();
    }

    /**
     * Envía la solicitud para equipar un ítem ya posedido por el usuario.
     * @param {string} itemId - Identificador del ítem a equipar.
     * @returns {Promise<Object>} Respuesta JSON del servidor.
     */
    async function equiparItemPeticion(itemId) {
        const { urlEquiparItem, csrfToken } = obtenerConfig();

        const formData = new FormData();
        formData.append('item_id', itemId);
        formData.append('csrfmiddlewaretoken', csrfToken);

        const response = await fetch(urlEquiparItem, {
            method: 'POST',
            body: formData,
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
        });
        return response.json();
    }

    /**
     * Envía la solicitud para comprar y equipar un ítem en un solo paso.
     * @param {string} itemId - Identificador del ítem a comprar y equipar.
     * @returns {Promise<Object>} Respuesta JSON del servidor.
     */
    async function comprarYEquiparPeticion(itemId) {
        const { urlComprarYEquipar, csrfToken } = obtenerConfig();

        const formData = new FormData();
        formData.append('item_id', itemId);
        formData.append('csrfmiddlewaretoken', csrfToken);

        const response = await fetch(urlComprarYEquipar, {
            method: 'POST',
            body: formData,
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
        });
        return response.json();
    }

    /**
     * Gestiona el clic en un ítem de "Tengo": lo equipa vía AJAX y actualiza
     * la vista previa y el grid sin recargar la página.
     * @param {HTMLElement} boton - Botón de ítem pulsado.
     * @returns {Promise<void>}
     */
    async function manejarEquipar(boton) {
        const itemId = boton.dataset.itemId;
        const categoria = boton.dataset.itemCategoria;
        const subcategoria = boton.dataset.itemSubcategoria;
        const imagenUrl = boton.dataset.itemImg;
        const yaEquipado = boton.dataset.equipado === 'true';

        boton.disabled = true;

        if (yaEquipado) {
            // Toggle: el ítem ya está puesto → quitárselo
            try {
                const resultado = await desequiparItemPeticion(itemId);
                if (resultado.exito) {
                    quitarCapaPreview(resultado.categoria || categoria, resultado.subcategoria || subcategoria);
                    boton.classList.remove('border-purple-500', 'bg-purple-50', 'shadow-inner');
                    boton.classList.add('border-gray-100', 'bg-gray-50');
                    boton.dataset.equipado = 'false';
                } else {
                    mostrarMensaje(resultado.mensaje || 'No se pudo quitar el ítem.', false);
                }
            } catch (error) {
                console.error('Error al desequipar ítem:', error);
                mostrarMensaje('Ocurrió un error de conexión. Inténtalo de nuevo.', false);
            } finally {
                boton.disabled = false;
            }
            return;
        }

        // Ítem no equipado → equiparlo normalmente
        actualizarCapaPreview(categoria, subcategoria, imagenUrl);

        try {
            const resultado = await equiparItemPeticion(itemId);
            if (resultado.exito) {
                marcarEquipadoEnGrid(itemId, resultado.categoria || categoria, resultado.subcategoria || subcategoria);
            } else {
                mostrarMensaje(resultado.mensaje || 'No se pudo equipar el ítem.', false);
            }
        } catch (error) {
            console.error('Error al equipar ítem:', error);
            mostrarMensaje('Ocurrió un error de conexión. Inténtalo de nuevo.', false);
        } finally {
            boton.disabled = false;
        }
    }

    /**
     * Gestiona el clic en un ítem de "Tienda": lo compra y equipa en un solo
     * paso vía AJAX, actualiza monedas, vista previa y mueve la tarjeta del
     * ítem a la pestaña "Tengo" correspondiente sin recargar la página.
     * @param {HTMLElement} boton - Botón de ítem pulsado.
     * @returns {Promise<void>}
     */
    async function manejarComprarYEquipar(boton) {
        const itemId = boton.dataset.itemId;
        const itemNombre = boton.dataset.itemNombre;

        boton.disabled = true;
        try {
            const resultado = await comprarYEquiparPeticion(itemId);
            if (resultado.exito) {
                actualizarMonedas(resultado.monedas);
                actualizarCapaPreview(resultado.categoria, resultado.subcategoria, resultado.imagen_url);
                mostrarMensaje(`¡"${itemNombre}" comprado y equipado!`, true);
                boton.remove();
            } else {
                mostrarMensaje(resultado.mensaje || 'No se pudo completar la compra.', false);
                boton.disabled = false;
            }
        } catch (error) {
            console.error('Error al comprar y equipar ítem:', error);
            mostrarMensaje('Ocurrió un error de conexión. Inténtalo de nuevo.', false);
            boton.disabled = false;
        }
    }

    document.addEventListener('DOMContentLoaded', () => {
        // Pestañas de zona del cuerpo.
        document.querySelectorAll('[data-zona-tab]').forEach((boton) => {
            boton.addEventListener('click', () => activarZona(boton.dataset.zona));
        });

        // Sub-pestañas Tengo/Tienda (zonas simples y sub-secciones de accesorio).
        document.querySelectorAll('[data-subtab]').forEach((boton) => {
            boton.addEventListener('click', () => activarSubtab(boton.dataset.subtabGroup, boton.dataset.subtabTarget));
        });

        // Delegación de eventos para equipar / comprar-y-equipar, ya que el
        // armario puede estar oculto dentro de un modal al cargar la página.
        document.body.addEventListener('click', (evento) => {
            const botonEquipar = evento.target.closest('[data-equipar-item]');
            if (botonEquipar) {
                manejarEquipar(botonEquipar);
                return;
            }
            const botonComprarEquipar = evento.target.closest('[data-comprar-equipar-item]');
            if (botonComprarEquipar) {
                manejarComprarYEquipar(botonComprarEquipar);
            }
        });
    });
})();
