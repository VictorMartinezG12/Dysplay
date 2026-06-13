/**
 * DysPlay - Avatar Event System
 * Gestiona las reacciones del avatar ante eventos globales del sistema.
 */

class AvatarSystem {
    constructor(reacciones) {
        this.reacciones = reacciones || {};
        this.avatarElement = document.getElementById('avatar-container');
        this.bubbleElement = document.getElementById('avatar-bubble');
        this.textElement = document.getElementById('avatar-text');
        this.currentTimeout = null;
        
        this.init();
    }

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
    }

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
