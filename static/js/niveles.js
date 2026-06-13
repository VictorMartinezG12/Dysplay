/**
 * DysPlay - Módulo de Niveles
 * Gestiona la navegación entre vistas (mapa, ejercicio, carga, resultado),
 * la lectura en voz alta de la frase objetivo, la grabación de audio del
 * estudiante (codificado como WAV real para Azure Speech) y el envío del
 * resultado al backend.
 */

(() => {
    // --- Configuración inyectada desde Django (json_script) ---
    const configElement = document.getElementById('niveles-config');
    const config = configElement ? JSON.parse(configElement.textContent) : {};
    const URL_GUARDAR_PROGRESO = config.url_guardar_progreso || '';

    // --- Variables de estado del ejercicio actual ---
    let fraseActual = '';
    let palabraObjetivoActual = '';
    let nivelSeleccionado = '';

    // --- Variables para el micrófono real (AudioContext para forzar un WAV legítimo) ---
    let audioContext;
    let recorderNode;
    let audioStream;
    let audioBufferList = [];
    let recordingLength = 0;
    let isRecording = false;

    /**
     * Cambia la vista visible dentro del flujo de niveles (mapa, ejercicio,
     * carga o resultado) ocultando una sección y mostrando otra.
     * @param {string} hideId - ID de la sección a ocultar.
     * @param {string} showId - ID de la sección a mostrar.
     * @returns {void}
     */
    function changeView(hideId, showId) {
        document.getElementById(hideId).classList.add('hidden');
        document.getElementById(hideId).classList.remove('flex');
        document.getElementById(showId).classList.remove('hidden');
        document.getElementById(showId).classList.add('flex');
        lucide.createIcons();
    }

    /**
     * Inicia el ejercicio de un nivel: guarda los datos de la misión actual,
     * actualiza el título y resalta la palabra objetivo dentro de la frase,
     * oculta el encabezado global y cambia a la vista de ejercicio.
     * @param {string} numeroNivel - Número del nivel seleccionado.
     * @param {string} fraseHistoria - Frase completa que el estudiante debe leer.
     * @param {string} palabraObjetivo - Palabra objetivo dentro de la frase.
     * @returns {void}
     */
    function startExercise(numeroNivel, fraseHistoria, palabraObjetivo) {
        nivelSeleccionado = numeroNivel;
        fraseActual = fraseHistoria;
        palabraObjetivoActual = palabraObjetivo;

        document.getElementById('exercise-level-title').textContent = `Nivel ${numeroNivel}`;

        const fraseModificada = fraseHistoria.replace(
            palabraObjetivo,
            `<span class="text-primaryFijo underline decoration-wavy decoration-2">${palabraObjetivo}</span>`
        );
        document.getElementById('exercise-phrase').innerHTML = fraseModificada;

        document.getElementById('global-header').classList.add('hidden');
        document.getElementById('global-header').classList.remove('flex');

        changeView('view-map', 'view-exercise');
    }

    /**
     * Lee en voz alta la frase actual del ejercicio usando la API
     * SpeechSynthesis del navegador, configurada en español ecuatoriano.
     * @returns {void}
     */
    function leerTextoEnVozAlta() {
        if ('speechSynthesis' in window) {
            const utterance = new SpeechSynthesisUtterance(fraseActual);
            utterance.lang = 'es-EC';
            utterance.rate = 0.85;
            window.speechSynthesis.speak(utterance);
        }
    }

    /**
     * Convierte un arreglo de buffers de Float32Array (capturados por el
     * ScriptProcessor) en un único Float32Array continuo.
     * @param {Float32Array[]} channelBuffer - Lista de fragmentos de audio capturados.
     * @param {number} recordingLength - Longitud total combinada de las muestras.
     * @returns {Float32Array} Arreglo plano con todas las muestras de audio.
     */
    function flattenArray(channelBuffer, recordingLength) {
        const result = new Float32Array(recordingLength);
        let offset = 0;
        for (let i = 0; i < channelBuffer.length; i++) {
            const buffer = channelBuffer[i];
            result.set(buffer, offset);
            offset += buffer.length;
        }
        return result;
    }

    /**
     * Escribe una cadena de texto como bytes UTF-8 dentro de un DataView,
     * usado para construir la cabecera RIFF del archivo WAV.
     * @param {DataView} view - Vista binaria del buffer destino.
     * @param {number} offset - Posición inicial de escritura.
     * @param {string} string - Texto a escribir byte por byte.
     * @returns {void}
     */
    function writeUtfBytes(view, offset, string) {
        for (let i = 0; i < string.length; i++) {
            view.setUint8(offset + i, string.charCodeAt(i));
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
    function encodeWAV(samples, sampleRate) {
        const buffer = new ArrayBuffer(44 + samples.length * 2);
        const view = new DataView(buffer);

        /* Escribir Cabecera RIFF legítima para archivos WAV */
        writeUtfBytes(view, 0, 'RIFF');
        view.setUint32(4, 36 + samples.length * 2, true);
        writeUtfBytes(view, 8, 'WAVE');
        writeUtfBytes(view, 12, 'fmt ');
        view.setUint32(16, 16, true);
        view.setUint16(20, 1, true); // PCM Lineal (sin compresión)
        view.setUint16(22, 1, true); // 1 canal (Mono)
        view.setUint32(24, sampleRate, true);
        view.setUint32(28, sampleRate * 2, true);
        view.setUint16(32, 2, true);
        view.setUint16(34, 16, true); // 16 bits de calidad por muestra
        writeUtfBytes(view, 36, 'data');
        view.setUint32(40, samples.length * 2, true);

        // Guardar datos PCM convirtiendo float a int16
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
                + 'en los ajustes de tu navegador (en iPhone/iPad: Ajustes > Safari > Micrófono) '
                + 'y vuelve a intentarlo.';
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
     * Inicia o detiene la grabación del audio del estudiante. Al iniciar,
     * solicita acceso al micrófono y comienza a capturar muestras mediante
     * un ScriptProcessor. Al detener, codifica el audio capturado como WAV,
     * lo envía al endpoint de guardado de progreso (CASO A) y muestra el
     * resultado de la evaluación de pronunciación.
     * @returns {Promise<void>}
     */
    async function toggleRecording() {
        const btnGrabar = document.getElementById('btn-grabar');
        const textGrabar = document.getElementById('text-grabar');

        if (!isRecording) {
            try {
                // Pedir stream del micrófono
                audioStream = await navigator.mediaDevices.getUserMedia({ audio: true });

                // Inicializar el contexto de audio del navegador
                audioContext = new (window.AudioContext || window.webkitAudioContext)();
                const source = audioContext.createMediaStreamSource(audioStream);

                // Capturar en mono (1 canal de entrada, 1 canal de salida)
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

            // Desconectar y apagar el micrófono en la pestaña
            if (recorderNode) recorderNode.disconnect();
            if (audioStream) audioStream.getTracks().forEach((track) => track.stop());

            const currentSampleRate = audioContext.sampleRate;
            if (audioContext) audioContext.close();

            btnGrabar.classList.remove('bg-error', 'text-white', 'animate-pulse');
            btnGrabar.classList.add('bg-white', 'text-error');
            textGrabar.textContent = 'Procesando...';

            changeView('view-exercise', 'view-loading');

            // Procesar el audio acumulado y compilarlo en un .wav estructurado real
            const samples = flattenArray(audioBufferList, recordingLength);
            const audioBlob = encodeWAV(samples, currentSampleRate);

            const formData = new FormData();
            formData.append('audio', audioBlob, 'grabacion.wav');
            formData.append('palabra_objetivo', palabraObjetivoActual);
            formData.append('nivel_id', nivelSeleccionado);

            const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;

            try {
                const response = await fetch(URL_GUARDAR_PROGRESO, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': csrfToken },
                    body: formData,
                });

                const data = await response.json();

                if (data.status === 'success') {
                    const scoreAzure = Math.round(data.score);

                    document.getElementById('score-text').textContent = `${scoreAzure}%`;
                    document.getElementById('score-chart').style.background = `conic-gradient(#10B981 ${scoreAzure}%, #edf2f7 0)`;

                    document.getElementById('input-nivel-id').value = nivelSeleccionado;
                    document.getElementById('input-score').value = scoreAzure;

                    changeView('view-loading', 'view-result');
                } else {
                    alert('No se pudo evaluar la pronunciación. ' + data.message);
                    goToMap();
                }
            } catch (error) {
                console.error(error);
                alert('Hubo un problema comunicándose con el servidor de Azure.');
                goToMap();
            }
        }
    }

    /**
     * Restaura la vista del mapa de niveles: muestra el encabezado global,
     * reinicia el estado visual del botón de grabar y vuelve a la sección
     * `view-map` desde cualquiera de las otras vistas.
     * @returns {void}
     */
    function goToMap() {
        document.getElementById('global-header').classList.remove('hidden');
        document.getElementById('global-header').classList.add('flex');

        const btnGrabar = document.getElementById('btn-grabar');
        btnGrabar.classList.add('bg-white', 'text-error');
        btnGrabar.classList.remove('bg-error', 'text-white', 'animate-pulse');
        document.getElementById('text-grabar').textContent = 'Grabar';

        changeView('view-result', 'view-map');
        changeView('view-exercise', 'view-map');
        changeView('view-loading', 'view-map');
    }

    /**
     * Inicializa los listeners de la página de niveles: enlaza el botón
     * del nivel actual (lee sus `data-*` con la frase y palabra objetivo),
     * el botón de "Escuchar" y el botón de "Grabar".
     * @returns {void}
     */
    function inicializar() {
        lucide.createIcons();

        const btnIniciarNivel = document.querySelector('[data-action="start-exercise"]');
        if (btnIniciarNivel) {
            btnIniciarNivel.addEventListener('click', () => {
                const { numeroNivel, fraseHistoria, palabraObjetivo } = btnIniciarNivel.dataset;
                startExercise(numeroNivel, fraseHistoria, palabraObjetivo);
            });
        }

        const btnEscuchar = document.querySelector('[data-action="leer-frase"]');
        if (btnEscuchar) {
            btnEscuchar.addEventListener('click', leerTextoEnVozAlta);
        }

        const btnGrabar = document.getElementById('btn-grabar');
        if (btnGrabar) {
            btnGrabar.addEventListener('click', toggleRecording);
        }
    }

    document.addEventListener('DOMContentLoaded', inicializar);
})();
