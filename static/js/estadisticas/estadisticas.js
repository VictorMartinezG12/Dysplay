/**
 * DysPlay - Panel de Estadísticas (Módulo H)
 * Interactividad del panel: racha animada con frase motivadora, animaciones
 * de carga (barras y conteo de racha), insignias clickeables (reutilizando
 * el sistema de celebraciones del Módulo K) y pista de coleccionables
 * bloqueados.
 */

/**
 * Devuelve una frase motivadora aleatoria sobre la racha de días, con el
 * singular/plural de "día" ya resuelto.
 * @param {number} diasRacha - Cantidad de días en racha del usuario.
 * @returns {string} Frase motivadora lista para mostrar.
 */
function obtenerFraseRachaAleatoria(diasRacha) {
    const textoDias = diasRacha === 1 ? 'día' : 'días';

    const frases = [
        `¡Llevas ${diasRacha} ${textoDias} seguidos, sigue así!`,
        `¡${diasRacha} ${textoDias} de racha! Eres imparable.`,
        `¡Wow, ${diasRacha} ${textoDias} sin parar de practicar!`,
        `${diasRacha} ${textoDias} en racha. ¡Tu esfuerzo brilla!`,
        `¡No hay quien te detenga! ${diasRacha} ${textoDias} en racha.`,
    ];

    return frases[Math.floor(Math.random() * frases.length)];
}

/**
 * Inicializa la interacción de la tarjeta de racha: animación del ícono de
 * llama y globo de diálogo con frase motivadora al hacer click/Enter.
 * @returns {void}
 */
function inicializarTarjetaRacha() {
    const tarjeta = document.getElementById('tarjeta-racha');
    const icono = document.getElementById('racha-icono');
    const mensaje = document.getElementById('racha-mensaje');
    const mensajeTexto = document.getElementById('racha-mensaje-texto');

    if (!tarjeta || !icono || !mensaje || !mensajeTexto) return;

    const diasRacha = parseInt(tarjeta.dataset.racha, 10) || 0;
    let temporizadorOcultarMensaje = null;

    /**
     * Reproduce la animación de la llama y muestra una frase motivadora
     * durante unos segundos, reiniciando limpio si ya estaba en curso.
     * @returns {void}
     */
    const activarRacha = () => {
        // Reiniciar animación de la llama (forzar reflow para poder repetirla).
        icono.classList.remove('animate-salto-llama');
        // eslint-disable-next-line no-unused-expressions
        icono.offsetWidth;
        icono.classList.add('animate-salto-llama');

        // Reiniciar el temporizador de ocultado si ya había uno activo.
        if (temporizadorOcultarMensaje) {
            clearTimeout(temporizadorOcultarMensaje);
        }

        mensajeTexto.textContent = obtenerFraseRachaAleatoria(diasRacha);
        mensaje.classList.add('racha-mensaje-visible');

        temporizadorOcultarMensaje = setTimeout(() => {
            mensaje.classList.remove('racha-mensaje-visible');
        }, 3000);
    };

    tarjeta.addEventListener('click', activarRacha);
    tarjeta.addEventListener('keydown', (evento) => {
        if (evento.key === 'Enter' || evento.key === ' ') {
            evento.preventDefault();
            activarRacha();
        }
    });

    icono.addEventListener('animationend', () => {
        icono.classList.remove('animate-salto-llama');
    });
}

/**
 * Anima el conteo ascendente del número de racha, de 0 hasta el valor real.
 * @returns {void}
 */
function animarConteoRacha() {
    const tarjeta = document.getElementById('tarjeta-racha');
    const numero = document.getElementById('racha-numero');
    if (!tarjeta || !numero) return;

    const valorFinal = parseInt(tarjeta.dataset.racha, 10) || 0;
    if (valorFinal === 0) {
        numero.textContent = '0';
        return;
    }

    const duracionMs = 800;
    const inicio = performance.now();

    /**
     * Paso de la animación de conteo, calculado en función del tiempo
     * transcurrido respecto a la duración total.
     * @param {number} tiempoActual - Marca de tiempo entregada por requestAnimationFrame.
     * @returns {void}
     */
    const paso = (tiempoActual) => {
        const progreso = Math.min((tiempoActual - inicio) / duracionMs, 1);
        const valorActual = Math.round(progreso * valorFinal);
        numero.textContent = String(valorActual);

        if (progreso < 1) {
            requestAnimationFrame(paso);
        }
    };

    requestAnimationFrame(paso);
}

/**
 * Anima el crecimiento de las barras del gráfico de actividad semanal desde
 * 0% hasta su altura real, escalonando el inicio por índice para un efecto
 * de "ola".
 * @returns {void}
 */
function animarBarrasSemana() {
    const barras = document.querySelectorAll('.barra-semana');

    barras.forEach((barra, indice) => {
        setTimeout(() => {
            barra.style.height = `${barra.dataset.altura}%`;
        }, 80 * indice);
    });
}

/**
 * Habilita el click/Enter en las insignias obtenidas para reabrir la
 * celebración con confeti, reutilizando `window.mostrarCelebracion` del
 * sistema de celebraciones (Módulo K), sin duplicar su lógica.
 * @returns {void}
 */
function inicializarInsigniasClickeables() {
    const insignias = document.querySelectorAll('.insignia-clickeable');

    insignias.forEach((tarjetaInsignia) => {
        /**
         * Abre el modal de celebración con los datos de la insignia tocada.
         * @returns {void}
         */
        const abrirCelebracion = () => {
            if (typeof window.mostrarCelebracion !== 'function') return;

            window.mostrarCelebracion(
                {
                    nombre: tarjetaInsignia.dataset.nombre,
                    descripcion: tarjetaInsignia.dataset.descripcion,
                    imagen: tarjetaInsignia.dataset.imagen,
                },
                () => {},
            );
        };

        tarjetaInsignia.addEventListener('click', abrirCelebracion);
        tarjetaInsignia.addEventListener('keydown', (evento) => {
            if (evento.key === 'Enter' || evento.key === ' ') {
                evento.preventDefault();
                abrirCelebracion();
            }
        });
    });
}

/**
 * Habilita el click/Enter en los coleccionables bloqueados para mostrar un
 * modal con una pista fija (sin revelar nombre ni descripción real).
 * @returns {void}
 */
function inicializarPistaColeccionables() {
    const coleccionablesBloqueados = document.querySelectorAll('.coleccionable-bloqueado');
    const modal = document.getElementById('modal-pista-coleccionable');
    const botonCerrar = document.getElementById('pista-cerrar');

    if (!modal || !botonCerrar) return;

    /**
     * Muestra el modal de pista.
     * @returns {void}
     */
    const abrirModal = () => {
        modal.classList.remove('hidden');
        botonCerrar.focus();
    };

    /**
     * Oculta el modal de pista.
     * @returns {void}
     */
    const cerrarModal = () => {
        modal.classList.add('hidden');
    };

    coleccionablesBloqueados.forEach((tarjeta) => {
        tarjeta.addEventListener('click', abrirModal);
        tarjeta.addEventListener('keydown', (evento) => {
            if (evento.key === 'Enter' || evento.key === ' ') {
                evento.preventDefault();
                abrirModal();
            }
        });
    });

    botonCerrar.addEventListener('click', cerrarModal);
}

document.addEventListener('DOMContentLoaded', () => {
    inicializarTarjetaRacha();
    animarConteoRacha();
    animarBarrasSemana();
    inicializarInsigniasClickeables();
    inicializarPistaColeccionables();
});
