/**
 * DysPlay - Módulo de Desafío Diario
 * Gestiona la navegación entre vistas (inicio, ejercicio, carga, resultado),
 * la lectura en voz alta de la frase objetivo, la grabación de audio del
 * estudiante (codificado como WAV real para Azure Speech), el envío del
 * resultado al backend y el countdown de 24h cuando el desafío ya está
 * completado.
 */

(() => {
    // --- Configuración inyectada desde Django (json_script) ---
    const configElement = document.getElementById('desafio-config');
    const config = configElement ? JSON.parse(configElement.textContent) : {};
    const URL_EVALUAR = config.url_evaluar || '';

    // --- Variables de estado del ejercicio actual ---
    let frasePronunciar = '';
    let palabraObjetivoActual = '';
    let misionIdActual = '';

    // --- Variables para el micrófono real (AudioContext para forzar un WAV legítimo) ---
    let audioContext;
    let recorderNode;
    let audioStream;
    let audioBufferList = [];
    let recordingLength = 0;
    let isRecording = false;

    /**
     * Cambia la vista visible dentro del flujo del desafío (inicio, ejercicio,
     * carga o resultado) ocultando una sección y mostrando otra.
     * @param {string} hideId - ID de la sección a ocultar.
     * @param {string} showId - ID de la sección a mostrar.
     * @returns {void}
     */
    function cambiarVista(hideId, showId) {
        document.getElementById(hideId).classList.add('hidden');
        document.getElementById(hideId).classList.remove('flex');
        document.getElementById(showId).classList.remove('hidden');
        document.getElementById(showId).classList.add('flex');
        lucide.createIcons();
    }

    /**
     * Inicia el ejercicio seleccionado: guarda sus datos, resalta la palabra
     * objetivo dentro de la frase y cambia a la vista de ejercicio.
     * @param {string} misionId - Identificador de la `MisionVocabulario`.
     * @param {string} palabraObjetivo - Palabra objetivo a pronunciar.
     * @param {string} fraseHistoria - Frase completa que el estudiante debe leer.
     * @returns {void}
     */
    function iniciarEjercicio(misionId, palabraObjetivo, fraseHistoria) {
        misionIdActual = misionId;
        palabraObjetivoActual = palabraObjetivo;
        frasePronunciar = fraseHistoria;

        const fraseModificada = fraseHistoria.replace(
            palabraObjetivo,
            `<span class="text-primaryFijo underline decoration-wavy decoration-2">${palabraObjetivo}</span>`,
        );
        document.getElementById('ejercicio-frase').innerHTML = fraseModificada;

        document.getElementById('global-header').classList.add('hidden');
        document.getElementById('global-header').classList.remove('flex');

        cambiarVista('view-inicio', 'view-ejercicio');
    }

    /**
     * Lee en voz alta la frase actual del ejercicio usando el motor de voz
     * configurado por el usuario (navegador o Azure neural, con fallback
     * automático). Deshabilita el botón "Escuchar" mientras dura la
     * narración para evitar pulsaciones repetidas (y llamadas duplicadas a
     * la API de Azure).
     * @returns {Promise<void>}
     */
    async function leerTextoEnVozAlta() {
        const btnEscuchar = document.querySelector('[data-action="leer-frase"]');
        try {
            if (btnEscuchar) {
                btnEscuchar.disabled = true;
            }
            await window.narrarTexto(frasePronunciar, 'es-EC');
        } finally {
            if (btnEscuchar) {
                btnEscuchar.disabled = false;
            }
        }
    }

    /**
     * Convierte un arreglo de buffers de Float32Array (capturados por el
     * ScriptProcessor) en un único Float32Array continuo.
     * @param {Float32Array[]} channelBuffer - Lista de fragmentos de audio capturados.
     * @param {number} longitudTotal - Longitud total combinada de las muestras.
     * @returns {Float32Array} Arreglo plano con todas las muestras de audio.
     */
    function unirBuffers(channelBuffer, longitudTotal) {
        const resultado = new Float32Array(longitudTotal);
        let offset = 0;
        for (let i = 0; i < channelBuffer.length; i++) {
            const buffer = channelBuffer[i];
            resultado.set(buffer, offset);
            offset += buffer.length;
        }
        return resultado;
    }

    /**
     * Escribe una cadena de texto como bytes UTF-8 dentro de un DataView,
     * usado para construir la cabecera RIFF del archivo WAV.
     * @param {DataView} view - Vista binaria del buffer destino.
     * @param {number} offset - Posición inicial de escritura.
     * @param {string} texto - Texto a escribir byte por byte.
     * @returns {void}
     */
    function escribirBytesUtf(view, offset, texto) {
        for (let i = 0; i < texto.length; i++) {
            view.setUint8(offset + i, texto.charCodeAt(i));
        }
    }

    /**
     * Codifica un arreglo de muestras de audio PCM (float) en un Blob WAV
     * de 16 bits mono, con cabecera RIFF válida, compatible con la
     * validación de tipo (`audio/wav`) que realiza el backend con python-magic.
     * @param {Float32Array} samples - Muestras de audio en formato float (-1 a 1).
     * @param {number} sampleRate - Frecuencia de muestreo del AudioContext usado.
     * @returns {Blob} Blob de tipo `audio/wav` listo para enviar al servidor.
     */
    function codificarWAV(samples, sampleRate) {
        const buffer = new ArrayBuffer(44 + samples.length * 2);
        const view = new DataView(buffer);

        escribirBytesUtf(view, 0, 'RIFF');
        view.setUint32(4, 36 + samples.length * 2, true);
        escribirBytesUtf(view, 8, 'WAVE');
        escribirBytesUtf(view, 12, 'fmt ');
        view.setUint32(16, 16, true);
        view.setUint16(20, 1, true);
        view.setUint16(22, 1, true);
        view.setUint32(24, sampleRate, true);
        view.setUint32(28, sampleRate * 2, true);
        view.setUint16(32, 2, true);
        view.setUint16(34, 16, true);
        escribirBytesUtf(view, 36, 'data');
        view.setUint32(40, samples.length * 2, true);

        let offset = 44;
        for (let i = 0; i < samples.length; i++, offset += 2) {
            const s = Math.max(-1, Math.min(1, samples[i]));
            view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
        }

        return new Blob([view], { type: 'audio/wav' });
    }

    /**
     * Determina un mensaje de error amigable según el tipo de excepción
     * lanzada por `getUserMedia`, contemplando los casos típicos de
     * iOS Safari (permiso denegado, sin micrófono, contexto no seguro, etc.).
     * @param {Error} err - Error capturado al solicitar el micrófono.
     * @returns {string} Mensaje amigable para mostrar al usuario.
     */
    function obtenerMensajeErrorMicrofono(err) {
        const nombre = err && err.name;

        if (nombre === 'NotAllowedError' || nombre === 'PermissionDeniedError') {
            return 'Necesitamos permiso para usar el micrófono. Por favor, habilítalo '
                + 'en los ajustes de tu navegador y vuelve a intentarlo.';
        }
        if (nombre === 'NotFoundError' || nombre === 'DevicesNotFoundError') {
            return 'No encontramos un micrófono disponible en este dispositivo.';
        }
        if (nombre === 'NotReadableError' || nombre === 'TrackStartError') {
            return 'No se pudo acceder al micrófono porque otra aplicación lo está usando.';
        }
        if (nombre === 'SecurityError') {
            return 'Por seguridad, el micrófono solo funciona con una conexión segura (HTTPS).';
        }
        return 'Por favor, permite el acceso al micrófono en el navegador para poder jugar.';
    }

    /**
     * Inicia o detiene la grabación del audio del estudiante. Al detener,
     * codifica el audio capturado como WAV y lo envía al endpoint de
     * evaluación del desafío diario.
     * @returns {Promise<void>}
     */
    async function alternarGrabacion() {
        const btnGrabar = document.getElementById('btn-grabar');
        const textGrabar = document.getElementById('text-grabar');

        if (!isRecording) {
            try {
                audioStream = await navigator.mediaDevices.getUserMedia({ audio: true });

                audioContext = new (window.AudioContext || window.webkitAudioContext)();
                const source = audioContext.createMediaStreamSource(audioStream);

                recorderNode = audioContext.createScriptProcessor(4096, 1, 1);
                audioBufferList = [];
                recordingLength = 0;

                recorderNode.onaudioprocess = (e) => {
                    if (!isRecording) return;
                    const channelData = e.inputBuffer.getChannelData(0);
                    audioBufferList.push(new Float32Array(channelData));
                    recordingLength += channelData.length;
                };

                source.connect(recorderNode);
                recorderNode.connect(audioContext.destination);

                isRecording = true;

                btnGrabar.classList.remove('bg-white', 'text-error');
                btnGrabar.classList.add('bg-error', 'text-white', 'animate-pulse');
                textGrabar.textContent = 'Detener (Grabando...)';
            } catch (err) {
                console.error(err);
                alert(obtenerMensajeErrorMicrofono(err));
            }
        } else {
            isRecording = false;

            if (recorderNode) recorderNode.disconnect();
            if (audioStream) audioStream.getTracks().forEach((track) => track.stop());

            const sampleRateActual = audioContext.sampleRate;
            if (audioContext) audioContext.close();

            btnGrabar.classList.remove('bg-error', 'text-white', 'animate-pulse');
            btnGrabar.classList.add('bg-white', 'text-error');
            textGrabar.textContent = 'Procesando...';

            cambiarVista('view-ejercicio', 'view-loading');

            const samples = unirBuffers(audioBufferList, recordingLength);
            const audioBlob = codificarWAV(samples, sampleRateActual);

            await enviarIntento(audioBlob);
        }
    }

    /**
     * Envía el audio grabado al endpoint de evaluación del desafío diario y
     * actualiza la vista de resultado con la respuesta del servidor.
     * @param {Blob} audioBlob - Audio codificado en WAV.
     * @returns {Promise<void>}
     */
    async function enviarIntento(audioBlob) {
        const formData = new FormData();
        formData.append('audio', audioBlob, 'grabacion.wav');
        formData.append('mision_id', misionIdActual);

        const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value
            || document.cookie.split('; ').find((c) => c.startsWith('csrftoken='))?.split('=')[1];

        try {
            const response = await fetch(URL_EVALUAR, {
                method: 'POST',
                headers: { 'X-CSRFToken': csrfToken },
                body: formData,
            });

            const data = await response.json();

            if (data.status === 'success') {
                mostrarResultado(data);
                cambiarVista('view-loading', 'view-resultado');
            } else {
                alert('No se pudo evaluar la pronunciación. ' + data.message);
                volverAlInicio();
            }
        } catch (error) {
            console.error(error);
            alert('Hubo un problema comunicándose con el servidor.');
            volverAlInicio();
        }
    }

    /**
     * Pinta los resultados de un intento en `#view-resultado`: puntaje,
     * palabras evaluadas, mensaje del avatar y, si se completó el desafío
     * completo en este intento, el resumen final con monedas, coleccionable
     * e insignia.
     * @param {Object} data - Respuesta JSON del endpoint de evaluación.
     * @returns {void}
     */
    function mostrarResultado(data) {
        const scoreRedondeado = Math.round(data.score);

        // Solo existen en el DOM para admins (mostrar_puntuacion_detallada)
        const scoreText = document.getElementById('score-text');
        const scoreChart = document.getElementById('score-chart');
        if (scoreText) scoreText.textContent = `${scoreRedondeado}%`;
        if (scoreChart) scoreChart.style.background = `conic-gradient(#10B981 ${scoreRedondeado}%, #edf2f7 0)`;

        document.getElementById('resultado-titulo').textContent = data.ejercicio_superado
            ? '¡Bien hecho!'
            : '¡Lo intentaste genial!';

        mostrarMensajeAvatar(data.reaccion_avatar);
        mostrarIndicadoresPalabras(data.palabras);

        const resumen = document.getElementById('resumen-final');
        if (data.desafio_completado_ahora) {
            document.getElementById('resumen-monedas').textContent = `+${data.monedas_ganadas} Monedas`;

            const coleccionableBox = document.getElementById('resumen-coleccionable');
            if (data.coleccionable_obtenido) {
                document.getElementById('resumen-coleccionable-texto').textContent =
                    `¡Obtuviste: ${data.coleccionable_obtenido.nombre}!`;
                coleccionableBox.classList.remove('hidden');
                coleccionableBox.classList.add('flex');
            } else {
                coleccionableBox.classList.add('hidden');
                coleccionableBox.classList.remove('flex');
            }

            const insigniaBox = document.getElementById('resumen-insignia');
            if (data.insignia_nueva) {
                insigniaBox.classList.remove('hidden');
                insigniaBox.classList.add('flex');
            } else {
                insigniaBox.classList.add('hidden');
                insigniaBox.classList.remove('flex');
            }

            resumen.classList.remove('hidden');
            resumen.classList.add('flex');
            document.getElementById('btn-volver-desafio').classList.add('hidden');
        } else {
            resumen.classList.add('hidden');
            resumen.classList.remove('flex');
            document.getElementById('btn-volver-desafio').classList.remove('hidden');
        }
    }

    /**
     * Muestra el mensaje motivador del avatar en `#resultado-mensaje-avatar`,
     * anteponiendo un emoji acorde al tipo de reacción recibida.
     * @param {{tipo: string, mensaje: string}} [reaccionAvatar] - Reacción del avatar devuelta por el backend.
     * @returns {void}
     */
    function mostrarMensajeAvatar(reaccionAvatar) {
        const elementoMensaje = document.getElementById('resultado-mensaje-avatar');
        if (!reaccionAvatar || !reaccionAvatar.mensaje) {
            elementoMensaje.textContent = '';
            return;
        }

        const emojisPorTipo = {
            desafio_completado: '🏆',
            pronunciacion_correcta: '😄',
            pronunciacion_incorrecta: '💪',
        };
        const emoji = emojisPorTipo[reaccionAvatar.tipo] || '🙂';
        elementoMensaje.textContent = `${emoji} ${reaccionAvatar.mensaje}`;

        window.dispatchEvent(new CustomEvent('AVATAR_EVENT', {
            detail: { tipo: reaccionAvatar.tipo, data: {} },
        }));
    }

    /**
     * Genera los chips de indicadores por palabra dentro de
     * `#resultado-palabras`. Si no hay palabras, mantiene el contenedor oculto.
     * @param {{palabra: string, score: number}[]} [palabras] - Lista de palabras evaluadas con su score individual.
     * @returns {void}
     */
    function mostrarIndicadoresPalabras(palabras) {
        const contenedor = document.getElementById('resultado-palabras');
        if (!contenedor) return;  // No existe en modo estudiante

        contenedor.innerHTML = '';

        if (!palabras || palabras.length === 0) {
            contenedor.classList.add('hidden');
            contenedor.classList.remove('flex');
            return;
        }

        palabras.forEach((palabra) => {
            const chip = document.createElement('span');
            const esCorrecta = palabra.score >= 70;
            chip.textContent = palabra.palabra;
            chip.className = 'px-4 py-2 rounded-full font-bold text-[16px] border-2 '
                + (esCorrecta
                    ? 'bg-success/10 text-success border-success'
                    : 'bg-error/10 text-error border-error');
            contenedor.appendChild(chip);
        });

        contenedor.classList.remove('hidden');
        contenedor.classList.add('flex');
    }

    /**
     * Vuelve a la vista de inicio recargando la página, para reflejar el
     * estado actualizado de los ejercicios completados desde el servidor.
     * @returns {void}
     */
    function volverAlInicio() {
        window.location.reload();
    }

    /**
     * Inicia el countdown de 24h mostrado cuando el desafío de hoy ya está
     * completado, actualizando `#countdown-texto` cada segundo en formato
     * HH:MM:SS. Al llegar a cero, recarga la página para obtener el nuevo
     * desafío del día.
     * @param {number} segundosIniciales - Segundos restantes hasta la medianoche.
     * @returns {void}
     */
    function iniciarCountdown(segundosIniciales) {
        let segundosRestantes = segundosIniciales;
        const elemento = document.getElementById('countdown-texto');
        if (!elemento) return;

        const actualizar = () => {
            if (segundosRestantes <= 0) {
                window.location.reload();
                return;
            }

            const horas = Math.floor(segundosRestantes / 3600);
            const minutos = Math.floor((segundosRestantes % 3600) / 60);
            const segundos = segundosRestantes % 60;

            elemento.textContent = `${String(horas).padStart(2, '0')}:${String(minutos).padStart(2, '0')}:${String(segundos).padStart(2, '0')}`;
            segundosRestantes -= 1;
        };

        actualizar();
        setInterval(actualizar, 1000);
    }

    /**
     * Inicializa los listeners de la página del desafío diario: botones de
     * "iniciar ejercicio", "Escuchar", "Grabar", "Volver al desafío" y el
     * countdown si el desafío ya está completado.
     * @returns {void}
     */
    function inicializar() {
        lucide.createIcons();

        document.querySelectorAll('[data-action="iniciar-ejercicio"]').forEach((boton) => {
            boton.addEventListener('click', () => {
                const { misionId, palabraObjetivo, fraseHistoria } = boton.dataset;
                iniciarEjercicio(misionId, palabraObjetivo, fraseHistoria);
            });
        });

        const btnEscuchar = document.querySelector('[data-action="leer-frase"]');
        if (btnEscuchar) {
            btnEscuchar.addEventListener('click', leerTextoEnVozAlta);
        }

        const btnGrabar = document.getElementById('btn-grabar');
        if (btnGrabar) {
            btnGrabar.addEventListener('click', alternarGrabacion);
        }

        const btnVolver = document.getElementById('btn-volver-desafio');
        if (btnVolver) {
            btnVolver.addEventListener('click', volverAlInicio);
        }

        if (config.bloqueado && config.segundos_restantes != null) {
            iniciarCountdown(config.segundos_restantes);
        }
    }

    document.addEventListener('DOMContentLoaded', inicializar);
})();
