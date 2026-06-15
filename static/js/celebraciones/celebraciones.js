/**
 * DysPlay - Celebraciones
 * Consulta las insignias pendientes de mostrar al usuario y presenta un
 * modal de celebración secuencial con animación de confeti para cada una.
 */

/**
 * Obtiene el token CSRF disponible en la página, ya sea desde un campo de
 * formulario o desde la cookie `csrftoken`.
 * @returns {string|undefined} Token CSRF o `undefined` si no se encuentra.
 */
function obtenerCsrfToken() {
    return document.querySelector('[name=csrfmiddlewaretoken]')?.value
        || document.cookie.split('; ').find((cookie) => cookie.startsWith('csrftoken='))?.split('=')[1];
}

/**
 * Crea piezas de confeti animadas (emojis) dentro del contenedor indicado
 * y las elimina automáticamente al finalizar su animación.
 * @param {HTMLElement} contenedor - Elemento donde se agregarán las piezas de confeti.
 * @returns {void}
 */
function lanzarConfeti(contenedor) {
    if (!contenedor) return;

    const emojis = ['🎉', '✨', '🎊', '⭐', '🏆', '🎈'];
    const totalPiezas = 18;

    for (let i = 0; i < totalPiezas; i += 1) {
        const pieza = document.createElement('span');
        pieza.className = 'confeti-pieza animate-confeti';
        pieza.textContent = emojis[Math.floor(Math.random() * emojis.length)];
        pieza.style.left = `${Math.random() * 100}%`;
        pieza.style.animationDuration = `${2 + Math.random() * 1.5}s`;
        pieza.style.animationDelay = `${Math.random() * 0.6}s`;
        contenedor.appendChild(pieza);

        // Eliminar la pieza una vez termina su animación para no acumular nodos.
        pieza.addEventListener('animationend', () => {
            pieza.remove();
        });
    }
}

/**
 * Muestra el modal de celebración con los datos de una insignia y dispara
 * el confeti correspondiente.
 * @param {{nombre: string, descripcion: string, imagen: string}} insignia - Datos de la insignia a mostrar.
 * @param {() => void} alCerrar - Función a ejecutar cuando el usuario cierra el modal.
 * @returns {void}
 */
function mostrarCelebracion(insignia, alCerrar) {
    const modal = document.getElementById('modal-celebracion-insignia');
    if (!modal) {
        alCerrar();
        return;
    }

    const titulo = document.getElementById('celebracion-titulo');
    const descripcion = document.getElementById('celebracion-descripcion');
    const imagen = document.getElementById('celebracion-imagen');
    const icono = document.getElementById('celebracion-icono');
    const botonCerrar = document.getElementById('celebracion-cerrar');
    const confetiContenedor = document.getElementById('confeti-contenedor');

    if (titulo) titulo.textContent = insignia.nombre || 'Nueva insignia';
    if (descripcion) descripcion.textContent = insignia.descripcion || '';

    if (insignia.imagen) {
        if (imagen) {
            imagen.src = insignia.imagen;
            imagen.alt = `Insignia: ${insignia.nombre || 'nueva insignia conseguida'}`;
            imagen.classList.remove('hidden');
        }
        if (icono) icono.classList.add('hidden');
    } else {
        if (imagen) imagen.classList.add('hidden');
        if (icono) icono.classList.remove('hidden');
    }

    modal.classList.remove('hidden');
    lanzarConfeti(confetiContenedor);

    /**
     * Manejador de cierre del modal: oculta el modal, limpia el listener
     * y continúa con la siguiente insignia en la cola (si existe).
     * @returns {void}
     */
    const manejarCierre = () => {
        modal.classList.add('hidden');
        if (confetiContenedor) confetiContenedor.innerHTML = '';
        botonCerrar?.removeEventListener('click', manejarCierre);
        alCerrar();
    };

    botonCerrar?.addEventListener('click', manejarCierre);
}

/**
 * Muestra secuencialmente la cola de insignias pendientes: al cerrar una,
 * se muestra automáticamente la siguiente hasta agotar la lista.
 * @param {Array<{nombre: string, descripcion: string, imagen: string}>} insignias - Insignias pendientes a celebrar.
 * @returns {void}
 */
function mostrarColaDeInsignias(insignias) {
    if (!insignias || insignias.length === 0) return;

    // Avisar al avatar para que reaccione con la emoción de "insignia_nueva".
    window.dispatchEvent(new CustomEvent('AVATAR_EVENT', {
        detail: { tipo: 'insignia_nueva', data: {} },
    }));

    let indice = 0;

    /**
     * Muestra la insignia actual de la cola y programa la siguiente.
     * @returns {void}
     */
    const mostrarSiguiente = () => {
        if (indice >= insignias.length) return;
        const insigniaActual = insignias[indice];
        indice += 1;
        mostrarCelebracion(insigniaActual, mostrarSiguiente);
    };

    mostrarSiguiente();
}

/**
 * Consulta al backend las insignias pendientes de mostrar al usuario y, si
 * existen, inicia la celebración secuencial. Falla silenciosamente ante
 * errores de red para no interrumpir la experiencia del usuario.
 * @returns {Promise<void>}
 */
async function consultarInsigniasPendientes() {
    const csrfToken = obtenerCsrfToken();

    try {
        const respuesta = await fetch('/recompensas/insignias-pendientes/', {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken },
        });

        if (!respuesta.ok) {
            console.warn('⚠️ No se pudieron obtener las insignias pendientes:', respuesta.status);
            return;
        }

        const datos = await respuesta.json();
        mostrarColaDeInsignias(datos.insignias);
    } catch (error) {
        console.warn('⚠️ Error al consultar insignias pendientes:', error);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    consultarInsigniasPendientes();
});
