/**
 * DysPlay - Avatar Event System
 * Gestiona las reacciones del avatar ante eventos globales del sistema.
 */

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
        
        this.init();
    }

    /**
     * Inicializa el sistema de avatar: registra el listener de eventos
     * globales y muestra el saludo contextual inicial si está disponible.
     * @returns {void}
     */
    init() {
        console.log("🦁 Avatar System Initialized");

        // Escuchar eventos globales del sistema
        window.addEventListener('AVATAR_EVENT', (e) => {
            const { tipo, data } = e.detail;
            this.reaccionar(tipo, data);
        });

        // Eventos de prueba (pueden eliminarse luego)
        window.avatarTest = (tipo) => {
            window.dispatchEvent(new CustomEvent('AVATAR_EVENT', {
                detail: { tipo: tipo, data: {} }
            }));
        };

        // Mostrar la frase contextual de saludo al cargar la página, si existe.
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
            }
        } catch (error) {
            console.warn('⚠️ No se pudo leer la frase contextual del avatar:', error);
        }
    }

    /**
     * Aplica la reacción configurada para un tipo de evento: cambia la
     * emoción del avatar y muestra el mensaje correspondiente.
     * @param {string} tipo - Tipo de evento (clave del diccionario de reacciones).
     * @param {Object<string, string>} [data] - Variables para interpolar en el mensaje (ej: {objeto: 'manzana'}).
     * @returns {void}
     */
    reaccionar(tipo, data) {
        const reaccion = this.reacciones[tipo];
        if (!reaccion) {
            console.warn(`⚠️ No existe reacción definida para el evento: ${tipo}`);
            return;
        }

        console.log(`🎬 Avatar reaccionando a: ${tipo}`, reaccion);

        // 1. Cambiar Animación/Emoción
        this.setEmocion(reaccion.emocion);

        // 2. Mostrar Mensaje
        let mensaje = reaccion.mensaje;
        
        // Reemplazo básico de variables en el mensaje (ej: {objeto})
        if (data) {
            Object.keys(data).forEach(key => {
                mensaje = mensaje.replace(`{${key}}`, data[key]);
            });
        }

        this.mostrarMensaje(mensaje);
    }

    /**
     * Cambia la clase CSS de emoción aplicada al avatar y dispara la
     * animación de rebote si corresponde.
     * @param {string} emocion - Nueva emoción (neutral, feliz, triste, celebrando, etc.).
     * @returns {void}
     */
    setEmocion(emocion) {
        if (!this.avatarElement) return;
        
        // En una implementación real, aquí cambiaríamos el sprite o el SVG
        // Por ahora, usamos clases CSS para simular estados visuales
        const emociones = ['neutral', 'feliz', 'triste', 'celebrando', 'pensando', 'sorprendido', 'preocupado', 'analizando', 'explicando'];
        emociones.forEach(e => this.avatarElement.classList.remove(`avatar-${e}`));
        this.avatarElement.classList.add(`avatar-${emocion}`);
        
        // Animación de rebote al cambiar de emoción
        this.avatarElement.classList.remove('animate-bounce');
        void this.avatarElement.offsetWidth; // Force reflow
        if (['feliz', 'celebrando', 'sorprendido'].includes(emocion)) {
            this.avatarElement.classList.add('animate-bounce');
        }
    }

    /**
     * Muestra un mensaje en la burbuja de texto del avatar durante unos
     * segundos y luego la oculta automáticamente.
     * @param {string} texto - Mensaje a mostrar en la burbuja.
     * @returns {void}
     */
    mostrarMensaje(texto) {
        if (!this.bubbleElement || !this.textElement) return;

        // Limpiar timeout anterior si existe
        if (this.currentTimeout) clearTimeout(this.currentTimeout);

        this.textElement.innerText = texto;
        this.bubbleElement.classList.remove('hidden');
        this.bubbleElement.classList.add('animate-fade-in');

        // Ocultar mensaje después de 6 segundos (ajustable)
        this.currentTimeout = setTimeout(() => {
            this.bubbleElement.classList.add('hidden');
        }, 6000);
    }
}

// Inicialización global
document.addEventListener('DOMContentLoaded', () => {
    // Las reacciones vienen inyectadas desde el context processor como un JSON
    const reaccionesData = document.getElementById('avatar-reacciones-data');
    if (reaccionesData) {
        const reacciones = JSON.parse(reaccionesData.textContent);
        window.dysPlayAvatar = new AvatarSystem(reacciones);
    }
});
