/**
 * DysPlay - Avatar Event System
 * Gestiona las reacciones del avatar ante eventos globales del sistema.
 */

// Tipos de evento que disparan confetti global en pantalla completa.
const EVENTOS_FESTIVOS = new Set([
    'nivel_completado',
    'historia_completada',
    'desafio_completado',
    'insignia_nueva',
    'recompensa_ganada',
]);

/**
 * Lanza confetti de emojis animados sobre toda la pantalla.
 * Crea un overlay `position:fixed` temporal que se autodestruye al terminar.
 * @returns {void}
 */
function lanzarConfettiGlobal() {
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;pointer-events:none;z-index:9999;overflow:hidden;';

    const emojis = ['🎉', '✨', '🎊', '⭐', '🏆', '🎈', '🌟', '🎀'];
    const total = 40;
    let terminadas = 0;

    for (let i = 0; i < total; i++) {
        const pieza = document.createElement('span');
        const emoji = emojis[Math.floor(Math.random() * emojis.length)];
        const duracion = 1.8 + Math.random() * 1.4;
        const demora = Math.random() * 0.8;
        const tamaño = 1.2 + Math.random() * 1.4;
        const izq = Math.random() * 100;
        const rotacion = Math.random() * 720 - 360;

        pieza.textContent = emoji;
        pieza.style.cssText = `
            position:absolute;
            left:${izq}%;
            top:-60px;
            font-size:${tamaño}rem;
            animation: confetti-caida ${duracion}s ease-in ${demora}s forwards;
        `;

        pieza.addEventListener('animationend', () => {
            terminadas++;
            if (terminadas >= total) overlay.remove();
        });

        overlay.appendChild(pieza);
    }

    if (!document.getElementById('confetti-keyframes')) {
        const estilos = document.createElement('style');
        estilos.id = 'confetti-keyframes';
        estilos.textContent = `
            @keyframes confetti-caida {
                0%   { transform: translateY(0) rotate(0deg) scale(1); opacity: 1; }
                80%  { opacity: 1; }
                100% { transform: translateY(110vh) rotate(var(--rot, 360deg)) scale(0.6); opacity: 0; }
            }
        `;
        document.head.appendChild(estilos);
    }

    // Asignar rotación aleatoria por pieza via CSS custom property
    overlay.querySelectorAll('span').forEach(s => {
        const rot = Math.random() * 720 - 360;
        s.style.setProperty('--rot', `${rot}deg`);
    });

    document.body.appendChild(overlay);
}

class AvatarSystem {
    /**
     * Crea el sistema de avatar a partir del diccionario de reacciones
     * inyectado desde el backend.
     * @param {Object<string, {emocion: string, mensaje: string}>} reacciones - Mapa de tipo de evento a reacción.
     */
    constructor(reacciones) {
        this.reacciones = reacciones || {};
        this.avatarElement = document.getElementById('avatar-container');
        this.bubbleElement = document.getElementById('avatar-bubble');
        this.textElement = document.getElementById('avatar-text');
        this.currentTimeout = null;
        this.bounceTimeout = null;

        this.init();
    }

    /**
     * Inicializa el sistema de avatar: registra el listener de eventos
     * globales y muestra el saludo contextual inicial si está disponible.
     * @returns {void}
     */
    init() {
        // Escuchar eventos globales del sistema
        window.addEventListener('AVATAR_EVENT', (e) => {
            const { tipo, data } = e.detail;
            this.reaccionar(tipo, data);
        });

        window.avatarTest = (tipo) => {
            window.dispatchEvent(new CustomEvent('AVATAR_EVENT', {
                detail: { tipo: tipo, data: {} }
            }));
        };

        this.mostrarFraseContextual();
    }

    /**
     * Lee la frase contextual inyectada por el backend (si existe) y la
     * muestra en la burbuja del avatar como saludo inicial.
     * @returns {void}
     */
    mostrarFraseContextual() {
        const fraseElement = document.getElementById('avatar-frase-contextual-data');
        if (!fraseElement) return;

        try {
            const frase = JSON.parse(fraseElement.textContent);
            if (frase) {
                this.setEmocion('feliz');
                this.mostrarMensaje(frase);
                this.saludar();
            }
        } catch (error) {
            console.warn('⚠️ No se pudo leer la frase contextual del avatar:', error);
        }
    }

    /**
     * Activa la animación de saludo durante unos segundos.
     * @returns {void}
     */
    saludar() {
        if (!this.avatarElement) return;

        this.avatarElement.classList.remove('avatar-saludando');
        void this.avatarElement.offsetWidth;
        this.avatarElement.classList.add('avatar-saludando');
    }

    /**
     * Aplica la reacción configurada para un tipo de evento: cambia la
     * emoción del avatar, muestra el mensaje y lanza confetti si aplica.
     * @param {string} tipo - Tipo de evento (clave del diccionario de reacciones).
     * @param {Object<string, string>} [data] - Variables para interpolar en el mensaje.
     * @returns {void}
     */
    reaccionar(tipo, data) {
        const reaccion = this.reacciones[tipo];
        if (!reaccion) {
            console.warn(`⚠️ No existe reacción definida para el evento: ${tipo}`);
            return;
        }

        this.setEmocion(reaccion.emocion);

        let mensaje = data?.mensajeOverride || reaccion.mensaje;
        if (data) {
            Object.keys(data).forEach(key => {
                if (key !== 'mensajeOverride') mensaje = mensaje.replace(`{${key}}`, data[key]);
            });
        }

        this.mostrarMensaje(mensaje);

        if (EVENTOS_FESTIVOS.has(tipo)) {
            lanzarConfettiGlobal();
        }
    }

    /**
     * Cambia la clase CSS de emoción aplicada al avatar y dispara la
     * animación de rebote. El rebote dura 3 segundos y luego se detiene
     * para que el avatar vuelva a su posición normal.
     * @param {string} emocion - Nueva emoción.
     * @returns {void}
     */
    setEmocion(emocion) {
        if (!this.avatarElement) return;

        const emociones = ['neutral', 'feliz', 'triste', 'celebrando', 'pensando', 'sorprendido', 'preocupado', 'analizando', 'explicando'];
        emociones.forEach(e => this.avatarElement.classList.remove(`avatar-${e}`));
        this.avatarElement.classList.add(`avatar-${emocion}`);

        // Detener bounce anterior si existe
        if (this.bounceTimeout) {
            clearTimeout(this.bounceTimeout);
            this.bounceTimeout = null;
        }
        this.avatarElement.classList.remove('avatar-bouncing');
        void this.avatarElement.offsetWidth;

        if (['feliz', 'celebrando', 'sorprendido'].includes(emocion)) {
            this.avatarElement.classList.add('avatar-bouncing');
            // El rebote dura 3 s y luego para (no queda rebotando infinito)
            this.bounceTimeout = setTimeout(() => {
                this.avatarElement.classList.remove('avatar-bouncing');
            }, 3000);
        }
    }

    /**
     * Muestra un mensaje en la burbuja de texto del avatar durante 6 segundos.
     * @param {string} texto - Mensaje a mostrar en la burbuja.
     * @returns {void}
     */
    mostrarMensaje(texto) {
        if (!this.bubbleElement || !this.textElement) return;

        if (this.currentTimeout) clearTimeout(this.currentTimeout);

        this.textElement.innerText = texto;
        this.bubbleElement.classList.remove('hidden');
        this.bubbleElement.classList.add('animate-fade-in');

        this.currentTimeout = setTimeout(() => {
            this.bubbleElement.classList.add('hidden');
        }, 6000);
    }
}

// Inicialización global
document.addEventListener('DOMContentLoaded', () => {
    const reaccionesData = document.getElementById('avatar-reacciones-data');
    if (reaccionesData) {
        const reacciones = JSON.parse(reaccionesData.textContent);
        window.dysPlayAvatar = new AvatarSystem(reacciones);
    }
});
