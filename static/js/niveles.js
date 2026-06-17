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

    // AbortController para cancelar el fetch de Azure si el usuario sale a mitad
    let abortController = null;

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
     * oculta el encabezado global y cambia a la vista de ejercicio. Si el
     * nivel tiene una narrativa de introducción, muestra primero el modal
     * `#modal-narrativa` y posterga el cambio de vista hasta que el
     * estudiante presione "¡Comenzar!".
     * @param {string} numeroNivel - Número del nivel seleccionado.
     * @param {string} fraseHistoria - Frase completa que el estudiante debe leer.
     * @param {string} palabraObjetivo - Palabra objetivo dentro de la frase.
     * @param {string} [narrativaIntro] - Texto narrativo de introducción del nivel (puede ser vacío).
     * @returns {void}
     */
    function startExercise(numeroNivel, fraseHistoria, palabraObjetivo, narrativaIntro) {
        nivelSeleccionado = numeroNivel;
        fraseActual = fraseHistoria;
        palabraObjetivoActual = palabraObjetivo;

        document.getElementById('exercise-level-title').textContent = `Nivel ${numeroNivel}`;

        const fraseModificada = fraseHistoria.replace(
            palabraObjetivo,
            `<span class="text-primaryFijo underline decoration-wavy decoration-2">${palabraObjetivo}</span>`
        );
        document.getElementById('exercise-phrase').innerHTML = fraseModificada;

        if (narrativaIntro) {
            document.getElementById('narrativa-texto').textContent = narrativaIntro;
            const modal = document.getElementById('modal-narrativa');
            modal.classList.remove('hidden');
            modal.classList.add('flex');
            lucide.createIcons();
            return;
        }

        document.getElementById('global-header').classList.add('hidden');
        document.getElementById('global-header').classList.remove('flex');

        changeView('view-map', 'view-exercise');
    }

    /**
     * Cierra el modal de narrativa y avanza a la vista de ejercicio,
     * ocultando el encabezado global.
     * @returns {void}
     */
    function comenzarDesdeNarrativa() {
        const modal = document.getElementById('modal-narrativa');
        modal.classList.add('hidden');
        modal.classList.remove('flex');

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

            abortController = new AbortController();

            try {
                const response = await fetch(URL_GUARDAR_PROGRESO, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': csrfToken },
                    body: formData,
                    signal: abortController.signal,
                });

                const data = await response.json();

                if (data.status === 'success') {
                    const scoreAzure = Math.round(data.score);

                    // Score detallado (solo si el elemento existe en el DOM)
                    const scoreChart = document.getElementById('score-chart');
                    if (scoreChart) {
                        scoreChart.style.background = `conic-gradient(#10B981 ${scoreAzure}%, #edf2f7 0)`;
                        document.getElementById('score-text').textContent = `${scoreAzure}%`;
                    }

                    document.getElementById('input-nivel-id').value = nivelSeleccionado;
                    document.getElementById('input-score').value = scoreAzure;

                    // Monedas ganadas reales (CASO A)
                    document.getElementById('resultado-monedas').textContent = `+ ${data.monedas_ganadas} Monedas`;

                    // Estrellas obtenidas (B.2)
                    mostrarEstrellas(data.estrellas || 1);

                    // Mensaje motivador del avatar
                    mostrarMensajeAvatar(data.reaccion_avatar);

                    // Indicadores por palabra (solo si el elemento existe en el DOM)
                    if (document.getElementById('resultado-palabras')) {
                        mostrarIndicadoresPalabras(data.palabras);
                    }

                    // Título/subtítulo + botones según si avanzó de nivel
                    actualizarResultadoSegunAvance(data.avanzo_de_nivel);

                    abortController = null;
                    changeView('view-loading', 'view-result');
                } else {
                    alert('No se pudo evaluar la pronunciación. ' + data.message);
                    goToMap();
                }
            } catch (error) {
                if (error.name === 'AbortError') return;
                console.error(error);
                alert('Hubo un problema comunicándose con el servidor de Azure.');
                goToMap();
            }
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
            nivel_completado: '🌟',
            pronunciacion_correcta: '😄',
            pronunciacion_incorrecta: '💪',
        };
        const emoji = emojisPorTipo[reaccionAvatar.tipo] || '🙂';

        elementoMensaje.textContent = `${emoji} ${reaccionAvatar.mensaje}`;
    }

    /**
     * Genera los chips de indicadores por palabra dentro de
     * `#resultado-palabras`. Si no hay palabras, mantiene el contenedor
     * oculto.
     * @param {{palabra: string, score: number}[]} [palabras] - Lista de palabras evaluadas con su score individual.
     * @returns {void}
     */
    function mostrarIndicadoresPalabras(palabras) {
        const contenedor = document.getElementById('resultado-palabras');
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
     * Ajusta el título, subtítulo y botones de `#view-result` según si el
     * estudiante avanzó de nivel: muestra "Siguiente Nivel" si avanzó, o
     * "Reintentar" si debe volver a intentar el mismo nivel.
     * @param {boolean} avanzoDeNivel - Indica si el estudiante desbloqueó el siguiente nivel.
     * @returns {void}
     */
    function actualizarResultadoSegunAvance(avanzoDeNivel) {
        const titulo = document.getElementById('resultado-titulo');
        const subtitulo = document.getElementById('resultado-subtitulo');
        const btnSiguienteNivel = document.getElementById('btn-siguiente-nivel');
        const btnReintentar = document.getElementById('btn-reintentar');

        if (avanzoDeNivel) {
            titulo.textContent = '¡Nivel Superado!';
            subtitulo.textContent = '¡Lo hiciste increíble! Sigue así.';

            btnSiguienteNivel.classList.remove('hidden');
            btnSiguienteNivel.classList.add('flex');
            btnReintentar.classList.add('hidden');
            btnReintentar.classList.remove('flex');
        } else {
            titulo.textContent = '¡Sigue practicando!';
            subtitulo.textContent = 'Puedes intentarlo de nuevo cuando quieras.';

            btnSiguienteNivel.classList.add('hidden');
            btnSiguienteNivel.classList.remove('flex');
            btnReintentar.classList.remove('hidden');
            btnReintentar.classList.add('flex');
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

        // Al ocultar view-map durante el ejercicio, la página se "achica" y
        // el navegador pierde la posición de scroll; al volver, sin esto,
        // se queda arriba en vez de en el nivel donde estaba el estudiante.
        centrarEnNivelActual();
    }

    /**
     * Sale al mapa desde cualquier pantalla del flujo sin guardar progreso parcial:
     * detiene la grabación (libera el micrófono), cancela el fetch pendiente y
     * vuelve a `view-map`. No otorga ni descuenta monedas.
     * @returns {void}
     */
    function salirAlMapa() {
        if (isRecording) {
            isRecording = false;
            if (recorderNode) recorderNode.disconnect();
            if (audioStream) audioStream.getTracks().forEach((t) => t.stop());
            if (audioContext) audioContext.close();
        }

        if (abortController) {
            abortController.abort();
            abortController = null;
        }

        goToMap();
    }

    /**
     * Muestra las estrellas obtenidas (1, 2 o 3) en `#resultado-estrellas`,
     * rellenando con ⭐ y dejando las restantes como ☆.
     * @param {number} numEstrellas - Número de estrellas (1, 2 o 3).
     * @returns {void}
     */
    function mostrarEstrellas(numEstrellas) {
        ['estrella-1', 'estrella-2', 'estrella-3'].forEach((id, i) => {
            const el = document.getElementById(id);
            if (!el) return;
            el.textContent = i < numEstrellas ? '⭐' : '☆';
        });
    }

    // Ancho de diseño interno del mapa de niveles (debe coincidir con el
    // usado en niveles/services.py para calcular las coordenadas x/y).
    const ANCHO_DISENO_MAPA = 390;

    /**
     * Reescala el canvas del mapa de niveles (de tamaño fijo, 390px de
     * ancho de diseño) para que ocupe el ancho real disponible de
     * `.mapa-escala-wrapper`, sin distorsión. Se hace por JS — y no con
     * CSS container queries — porque esa propiedad no la soportan todos
     * los navegadores; con JS el mapa se ve grande en cualquiera.
     * También fija el alto del wrapper al alto ya escalado, para que
     * reserve el espacio correcto en el flujo normal de la página.
     * @returns {void}
     */
    function ajustarEscalaMapa() {
        const wrapper = document.querySelector('.mapa-escala-wrapper');
        const canvas = document.querySelector('.mapa-canvas-unico');
        if (!wrapper || !canvas) return;

        const anchoDisponible = wrapper.clientWidth;
        if (!anchoDisponible) return;

        const escala = anchoDisponible / ANCHO_DISENO_MAPA;
        const altoNatural = parseFloat(canvas.style.height) || canvas.offsetHeight;

        canvas.style.transform = `scale(${escala})`;
        wrapper.style.height = `${altoNatural * escala}px`;
    }

    /**
     * Centra el scroll de la página en el nodo del nivel actual (`.lvl-actual`)
     * para que, con mapas largos de muchas zonas, el estudiante vea de
     * inmediato dónde está parado en vez de tener que buscarlo. Se llama al
     * cargar la página y también ocurre naturalmente al volver del flujo de
     * ejercicio (ese flujo siempre recarga la página completa de niveles).
     * @returns {void}
     */
    function centrarEnNivelActual() {
        const nodoActual = document.querySelector('.lvl-actual');
        if (!nodoActual) return;
        nodoActual.scrollIntoView({ block: 'center', inline: 'center' });
    }

    /**
     * Inicializa los listeners de la página de niveles: enlaza el botón
     * del nivel actual (lee sus `data-*` con la frase, palabra objetivo y
     * narrativa de introducción), el botón de "Escuchar", el botón de
     * "Grabar", el botón "¡Comenzar!" del modal de narrativa y el botón
     * "Reintentar" de la vista de resultado.
     * @returns {void}
     */
    function inicializar() {
        lucide.createIcons();

        ajustarEscalaMapa();
        centrarEnNivelActual();
        let resizeTimeoutId = null;
        window.addEventListener('resize', () => {
            clearTimeout(resizeTimeoutId);
            resizeTimeoutId = setTimeout(ajustarEscalaMapa, 100);
        });

        document.querySelectorAll('[data-action="start-exercise"]').forEach((btn) => {
            btn.addEventListener('click', () => {
                const { numeroNivel, fraseHistoria, palabraObjetivo, narrativaIntro } = btn.dataset;
                startExercise(numeroNivel, fraseHistoria, palabraObjetivo, narrativaIntro);
            });
        });

        const btnEscuchar = document.querySelector('[data-action="leer-frase"]');
        if (btnEscuchar) {
            btnEscuchar.addEventListener('click', leerTextoEnVozAlta);
        }

        const btnGrabar = document.getElementById('btn-grabar');
        if (btnGrabar) {
            btnGrabar.addEventListener('click', toggleRecording);
        }

        document.querySelectorAll('[data-action="salir-al-mapa"]').forEach((btn) => {
            btn.addEventListener('click', salirAlMapa);
        });

        const btnComenzarNarrativa = document.getElementById('btn-comenzar-narrativa');
        if (btnComenzarNarrativa) {
            btnComenzarNarrativa.addEventListener('click', comenzarDesdeNarrativa);
        }

        const btnReintentar = document.getElementById('btn-reintentar');
        if (btnReintentar) {
            btnReintentar.addEventListener('click', () => {
                document.getElementById('text-grabar').textContent = 'Grabar';
                changeView('view-result', 'view-exercise');
            });
        }
    }

    document.addEventListener('DOMContentLoaded', inicializar);
})();
