/**
 * DysPlay - Módulo de Historias Interactivas
 * Gestiona la navegación entre fragmentos de una historia (narración, pausa
 * con pregunta, carga y desenlace), la lectura en voz alta de la narración,
 * la grabación de audio para preguntas de tipo "pronunciar" (codificado como
 * WAV real para Azure Speech) y el envío de la respuesta al backend, que
 * devuelve el siguiente fragmento o el resumen final de recompensas.
 */

(() => {
    const configElement = document.getElementById('historias-config');
    const config = configElement ? JSON.parse(configElement.textContent) : {};
    const lectura = config.lectura;
    const URL_EVALUAR = config.url_evaluar || '';

    if (!lectura) {
        document.addEventListener('DOMContentLoaded', () => lucide.createIcons());
        return;
    }

    // Mapa de fragmentos por id, para resolver el "siguiente fragmento" recibido del backend.
    const fragmentosPorId = {};
    lectura.fragmentos.forEach((fragmento) => { fragmentosPorId[fragmento.id] = fragmento; });

    let fragmentoActual = fragmentosPorId[lectura.fragmento_actual_id] || lectura.fragmentos[0];
    let fragmentoSiguientePendiente = null;

    // --- Variables para el micrófono real (AudioContext para forzar un WAV legítimo) ---
    let audioContext;
    let recorderNode;
    let audioStream;
    let audioBufferList = [];
    let recordingLength = 0;
    let isRecording = false;

    /**
     * Cambia la vista visible dentro del flujo de lectura, ocultando una
     * sección y mostrando otra.
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
     * Lee en voz alta un texto usando la API SpeechSynthesis del navegador,
     * configurada en español ecuatoriano.
     * @param {string} texto - Texto a leer.
     * @returns {void}
     */
    function leerTextoEnVozAlta(texto) {
        if ('speechSynthesis' in window) {
            const utterance = new SpeechSynthesisUtterance(texto);
            utterance.lang = 'es-EC';
            utterance.rate = 0.85;
            window.speechSynthesis.speak(utterance);
        }
    }

    /**
     * Renderiza la narración de un fragmento en `#view-narration` y
     * configura el botón "Reproducir narración" (audio grabado o TTS).
     * @param {Object} fragmento - Fragmento serializado a mostrar.
     * @returns {void}
     */
    function renderizarFragmento(fragmento) {
        fragmentoActual = fragmento;
        document.getElementById('narracion-texto').textContent = fragmento.texto_narracion;

        const btnEscuchar = document.getElementById('btn-escuchar');
        btnEscuchar.onclick = () => {
            if (fragmento.audio_narracion_url) {
                new Audio(fragmento.audio_narracion_url).play();
            } else {
                leerTextoEnVozAlta(fragmento.texto_narracion);
            }
        };

        document.getElementById('view-interaction').classList.add('hidden');
        document.getElementById('view-interaction').classList.remove('flex');
        document.getElementById('view-resolution').classList.add('hidden');
        document.getElementById('view-resolution').classList.remove('flex');
        document.getElementById('view-narration').classList.remove('hidden');
        document.getElementById('view-narration').classList.add('flex');
        lucide.createIcons();
    }

    /**
     * Prepara y muestra `#view-interaction` según el `tipo_respuesta` del
     * fragmento actual (elegir, escribir o pronunciar).
     * @returns {void}
     */
    function mostrarInteraccion() {
        document.getElementById('pregunta-texto').textContent = fragmentoActual.pregunta_interactiva;

        const bloqueElegir = document.getElementById('bloque-elegir');
        const bloqueEscribir = document.getElementById('bloque-escribir');
        const bloquePronunciar = document.getElementById('bloque-pronunciar');

        [bloqueElegir, bloqueEscribir, bloquePronunciar].forEach((bloque) => {
            bloque.classList.add('hidden');
            bloque.classList.remove('flex');
        });

        if (fragmentoActual.tipo_respuesta === 'elegir') {
            bloqueElegir.innerHTML = '';
            fragmentoActual.opciones.forEach((opcion) => {
                const boton = document.createElement('button');
                boton.type = 'button';
                boton.textContent = opcion.texto;
                boton.className = 'w-full sm:w-auto bg-white text-primaryFijo border-4 border-primaryFijo '
                    + 'rounded-2xl px-8 py-6 font-bold text-[20px] hover:bg-primaryFijo hover:text-white '
                    + 'transition-colors shadow-soft';
                boton.addEventListener('click', () => enviarRespuesta({ opcion_id: opcion.id }));
                bloqueElegir.appendChild(boton);
            });
            bloqueElegir.classList.remove('hidden');
            bloqueElegir.classList.add('flex');
        } else if (fragmentoActual.tipo_respuesta === 'escribir') {
            document.getElementById('input-escribir').value = '';
            bloqueEscribir.classList.remove('hidden');
            bloqueEscribir.classList.add('flex');
        } else if (fragmentoActual.tipo_respuesta === 'pronunciar') {
            bloquePronunciar.classList.remove('hidden');
            bloquePronunciar.classList.add('flex');
        }

        cambiarVista('view-narration', 'view-interaction');
    }

    /**
     * Determina un mensaje de error amigable según el tipo de excepción
     * lanzada por `getUserMedia`.
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
     * Convierte un arreglo de buffers de Float32Array en un único Float32Array continuo.
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
     * Escribe una cadena de texto como bytes UTF-8 dentro de un DataView.
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
     * de 16 bits mono, con cabecera RIFF válida.
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
     * Inicia o detiene la grabación del audio del estudiante para una
     * pregunta de tipo "pronunciar". Al detener, codifica el audio como WAV
     * y lo envía como respuesta.
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

            const samples = unirBuffers(audioBufferList, recordingLength);
            const audioBlob = codificarWAV(samples, sampleRateActual);

            await enviarRespuesta({ audio: audioBlob });
        }
    }

    /**
     * Envía la respuesta del estudiante al fragmento actual y actualiza la
     * vista de resolución con el resultado.
     * @param {Object} payload - `{ opcion_id }`, `{ texto_respuesta }` o `{ audio: Blob }`.
     * @returns {Promise<void>}
     */
    async function enviarRespuesta(payload) {
        cambiarVista(
            document.getElementById('view-interaction').classList.contains('hidden') ? 'view-narration' : 'view-interaction',
            'view-thinking',
        );

        const formData = new FormData();
        formData.append('fragmento_id', fragmentoActual.id);
        if (payload.opcion_id !== undefined) formData.append('opcion_id', payload.opcion_id);
        if (payload.texto_respuesta !== undefined) formData.append('texto_respuesta', payload.texto_respuesta);
        if (payload.audio !== undefined) formData.append('audio', payload.audio, 'grabacion.wav');

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
                mostrarResolucion(data);
                cambiarVista('view-thinking', 'view-resolution');
            } else {
                alert('No se pudo procesar tu respuesta. ' + data.message);
                renderizarFragmento(fragmentoActual);
            }
        } catch (error) {
            console.error(error);
            alert('Hubo un problema comunicándose con el servidor.');
            renderizarFragmento(fragmentoActual);
        }
    }

    /**
     * Pinta el resultado de un intento en `#view-resolution`: título según
     * acierto, mensaje del avatar y, si la historia se completó, el resumen
     * de recompensas.
     * @param {Object} data - Respuesta JSON del endpoint de evaluación.
     * @returns {void}
     */
    function mostrarResolucion(data) {
        const titulo = document.getElementById('resolucion-titulo');
        if (data.correcta === true) {
            titulo.textContent = '¡Muy bien!';
        } else if (data.correcta === false) {
            titulo.textContent = '¡Sigamos la historia!';
        } else {
            titulo.textContent = 'La aventura continúa...';
        }

        const emojisPorTipo = {
            historia_completada: '🏆',
            pronunciacion_correcta: '😄',
            pronunciacion_incorrecta: '💪',
        };
        const mensajeAvatar = document.getElementById('resolucion-mensaje-avatar');
        if (data.reaccion_avatar && data.reaccion_avatar.mensaje) {
            const emoji = emojisPorTipo[data.reaccion_avatar.tipo] || '🙂';
            mensajeAvatar.textContent = `${emoji} ${data.reaccion_avatar.mensaje}`;
        } else {
            mensajeAvatar.textContent = '';
        }

        const resumen = document.getElementById('resumen-final');
        const btnVolverMenu = document.getElementById('btn-volver-menu');
        const btnSiguiente = document.getElementById('btn-siguiente-fragmento');

        if (data.completada_ahora) {
            document.getElementById('resumen-monedas').innerHTML =
                `<i data-lucide="coins" class="w-8 h-8"></i> +${data.monedas_ganadas}`;

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
            btnVolverMenu.classList.remove('hidden');
            btnSiguiente.classList.add('hidden');
            fragmentoSiguientePendiente = null;
        } else {
            resumen.classList.add('hidden');
            resumen.classList.remove('flex');
            btnVolverMenu.classList.add('hidden');
            btnSiguiente.classList.remove('hidden');
            fragmentoSiguientePendiente = data.siguiente_fragmento;
        }
    }

    /**
     * Inicializa los listeners de la página de lectura de historias.
     * @returns {void}
     */
    function inicializar() {
        lucide.createIcons();

        if (lectura.completada) {
            // La historia ya fue completada antes: solo se permite volver al menú.
            document.getElementById('btn-continuar').classList.add('hidden');
            renderizarFragmento(fragmentoActual);
            return;
        }

        renderizarFragmento(fragmentoActual);

        document.getElementById('btn-continuar').addEventListener('click', () => {
            if (fragmentoActual.tipo_respuesta) {
                mostrarInteraccion();
            } else {
                enviarRespuesta({});
            }
        });

        document.getElementById('btn-enviar-escribir').addEventListener('click', () => {
            const texto = document.getElementById('input-escribir').value;
            enviarRespuesta({ texto_respuesta: texto });
        });

        document.getElementById('btn-grabar').addEventListener('click', alternarGrabacion);

        document.getElementById('btn-siguiente-fragmento').addEventListener('click', () => {
            if (fragmentoSiguientePendiente) {
                renderizarFragmento(fragmentoSiguientePendiente);
            }
        });
    }

    document.addEventListener('DOMContentLoaded', inicializar);
})();
