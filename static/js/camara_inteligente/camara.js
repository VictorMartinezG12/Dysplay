/**
 * DysPlay - Módulo de Cámara Inteligente
 * Gestiona el acceso a la cámara y al micrófono del dispositivo: captura una
 * foto del objeto enfocado y la envía al backend para reconocerlo y generar
 * una frase de práctica (Gemini), grava la pronunciación del estudiante
 * (codificada como WAV real para Azure Speech) y muestra el resultado con
 * las monedas obtenidas.
 */

(() => {
    // --- Configuración inyectada desde Django (json_script) ---
    const configElement = document.getElementById('camara-config');
    const config = configElement ? JSON.parse(configElement.textContent) : {};
    const URL_CAPTURAR = config.url_capturar || '';
    const URL_EVALUAR = config.url_evaluar || '';
    const URL_HOME = config.url_home || '/';

    // --- Variables de estado del ejercicio actual ---
    let frasePronunciar = '';
    let videoStream;

    // --- Variables para la detección de objetos en vivo (TensorFlow.js + COCO-SSD) ---
    let modeloDeteccion = null;
    let scriptsDeteccionCargados = false;
    let cargandoScriptsDeteccion = false;
    let idIntervaloDeteccion = null;
    let deteccionEnCurso = false;
    // Centro normalizado (0-1) de la detección actualmente resaltada, o null si no hay ninguna.
    let deteccionPrioritariaActual = null;

    // --- Variables para el micrófono real (AudioContext para forzar un WAV legítimo) ---
    let audioContext;
    let recorderNode;
    let audioStream;
    let audioBufferList = [];
    let recordingLength = 0;
    let isRecording = false;

    /**
     * Cambia la vista visible dentro del flujo de la cámara inteligente
     * ocultando una sección y mostrando otra.
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
     * Obtiene el token CSRF actual desde el formulario o la cookie de Django.
     * @returns {string|undefined} Token CSRF para incluir en las peticiones `fetch`.
     */
    function obtenerCsrfToken() {
        return document.querySelector('[name=csrfmiddlewaretoken]')?.value
            || document.cookie.split('; ').find((c) => c.startsWith('csrftoken='))?.split('=')[1];
    }

    /**
     * Determina un mensaje de error amigable según el tipo de excepción
     * lanzada por `getUserMedia` al solicitar la cámara.
     * @param {Error} err - Error capturado al solicitar la cámara.
     * @returns {string} Mensaje amigable para mostrar al usuario.
     */
    function obtenerMensajeErrorCamara(err) {
        const nombre = err && err.name;

        if (nombre === 'NotAllowedError' || nombre === 'PermissionDeniedError') {
            return 'Necesitamos permiso para usar la cámara. Por favor, habilítala '
                + 'en los ajustes de tu navegador y vuelve a intentarlo.';
        }
        if (nombre === 'NotFoundError' || nombre === 'DevicesNotFoundError') {
            return 'No encontramos una cámara disponible en este dispositivo.';
        }
        if (nombre === 'NotReadableError' || nombre === 'TrackStartError') {
            return 'No se pudo acceder a la cámara porque otra aplicación la está usando.';
        }
        if (nombre === 'SecurityError') {
            return 'Por seguridad, la cámara solo funciona con una conexión segura (HTTPS).';
        }
        return 'Por favor, permite el acceso a la cámara en el navegador para poder jugar.';
    }

    /**
     * Determina un mensaje de error amigable según el tipo de excepción
     * lanzada por `getUserMedia` al solicitar el micrófono.
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
     * Solicita acceso a la cámara del dispositivo y conecta el flujo de
     * video al elemento `#video-camara`. Una vez que el video tiene
     * dimensiones reales, carga (de forma diferida) el modelo de detección
     * de objetos y arranca el bucle de detección en vivo.
     * @returns {Promise<void>}
     */
    async function iniciarCamara() {
        try {
            videoStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } });
            const video = document.getElementById('video-camara');
            video.srcObject = videoStream;
            video.addEventListener('loadedmetadata', async () => {
                await asegurarModeloDeteccionCargado();
                iniciarDeteccionEnVivo();
            }, { once: true });
        } catch (err) {
            console.error(err);
            alert(obtenerMensajeErrorCamara(err));
        }
    }

    /**
     * Inyecta dinámicamente un `<script>` en el documento y resuelve la
     * promesa cuando termina de cargar (o rechaza si falla), usado para
     * cargar los vendor scripts de detección de objetos solo cuando se
     * necesitan (no como `<script src>` fijo global).
     * @param {string} url - URL del script a cargar.
     * @returns {Promise<void>}
     */
    function cargarScriptDinamico(url) {
        return new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = url;
            script.onload = () => resolve();
            script.onerror = () => reject(new Error(`No se pudo cargar el script: ${url}`));
            document.head.appendChild(script);
        });
    }

    /**
     * Carga de forma diferida TensorFlow.js, COCO-SSD y el modelo
     * `lite_mobilenet_v2` (vendorizados localmente) solo la primera vez que
     * se entra al visor de la cámara, y configura el backend de TF.js en
     * WebGL antes de cargar el modelo. Si ya estaba cargado, no hace nada
     * (reutiliza el modelo en memoria). Si algo falla, degrada limpiamente:
     * la detección en vivo queda deshabilitada pero el resto del flujo de
     * captura sigue funcionando con normalidad.
     * @returns {Promise<void>}
     */
    async function asegurarModeloDeteccionCargado() {
        if (scriptsDeteccionCargados || cargandoScriptsDeteccion) {
            return;
        }
        cargandoScriptsDeteccion = true;

        try {
            const urlTfJs = JSON.parse(document.getElementById('url-tf-js').textContent);
            const urlCocoSsdJs = JSON.parse(document.getElementById('url-coco-ssd-js').textContent);
            const urlModeloCocoSsd = JSON.parse(document.getElementById('url-modelo-coco-ssd').textContent);

            if (typeof window.tf === 'undefined') {
                await cargarScriptDinamico(urlTfJs);
            }
            if (typeof window.cocoSsd === 'undefined') {
                await cargarScriptDinamico(urlCocoSsdJs);
            }

            // Backend WebGL obligatorio: el backend CPU es demasiado lento para
            // correr detección continua en dispositivos de gama baja.
            await window.tf.setBackend('webgl');
            await window.tf.ready();

            modeloDeteccion = await window.cocoSsd.load({
                base: 'lite_mobilenet_v2',
                modelUrl: urlModeloCocoSsd,
            });

            scriptsDeteccionCargados = true;
        } catch (err) {
            // Degradación limpia: sin modelo de detección, solo queda visible
            // el punto central fijo y la captura sigue funcionando sin
            // `punto_objetivo`.
            console.error('No se pudo cargar el modelo de detección de objetos.', err);
            modeloDeteccion = null;
            scriptsDeteccionCargados = false;
        } finally {
            cargandoScriptsDeteccion = false;
        }
    }

    /**
     * Calcula, de la lista de detecciones devueltas por COCO-SSD, la más
     * cercana al punto central del video. Criterio: si alguna detección
     * contiene literalmente el punto central dentro de su `bbox`, se
     * prioriza esa; si ninguna lo contiene, se elige la de menor distancia
     * euclidiana entre el centro de su `bbox` y el punto central. Es un
     * criterio simple (no exhaustivo) pensado para el caso de uso de
     * "apuntar con la cámara a un solo objeto a la vez".
     * @param {Array<{bbox: number[], class: string, score: number}>} detecciones - Detecciones devueltas por `modelo.detect()`.
     * @param {number} centroX - Coordenada X del centro del video, en píxeles.
     * @param {number} centroY - Coordenada Y del centro del video, en píxeles.
     * @returns {{bbox: number[], class: string, score: number}|null} La detección priorizada, o `null` si no hay ninguna.
     */
    function encontrarDeteccionMasCercanaAlCentro(detecciones, centroX, centroY) {
        if (!detecciones || detecciones.length === 0) {
            return null;
        }

        const contienenElCentro = detecciones.filter((deteccion) => {
            const [x, y, ancho, alto] = deteccion.bbox;
            return centroX >= x && centroX <= x + ancho && centroY >= y && centroY <= y + alto;
        });
        if (contienenElCentro.length > 0) {
            // Si varias contienen el centro, se prioriza la de mayor confianza.
            return contienenElCentro.reduce((mejor, actual) => (actual.score > mejor.score ? actual : mejor));
        }

        let masCercana = null;
        let menorDistancia = Infinity;
        detecciones.forEach((deteccion) => {
            const [x, y, ancho, alto] = deteccion.bbox;
            const centroDeteccionX = x + ancho / 2;
            const centroDeteccionY = y + alto / 2;
            const distancia = Math.hypot(centroDeteccionX - centroX, centroDeteccionY - centroY);
            if (distancia < menorDistancia) {
                menorDistancia = distancia;
                masCercana = deteccion;
            }
        });
        return masCercana;
    }

    /**
     * Dibuja el marco de la detección priorizada sobre `#canvas-deteccion-vivo`,
     * escalando de píxeles del video a píxeles del canvas visible. Si no hay
     * ninguna detección, limpia el canvas (solo queda visible el punto
     * central fijo).
     * @param {HTMLCanvasElement} canvas - Canvas overlay de detección.
     * @param {HTMLVideoElement} video - Elemento de video con el feed en vivo.
     * @param {{bbox: number[], class: string}|null} deteccion - Detección priorizada a resaltar, o `null`.
     * @returns {void}
     */
    function dibujarMarcoDeteccion(canvas, video, deteccion) {
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        if (!deteccion) {
            return;
        }

        const escalaX = canvas.width / video.videoWidth;
        const escalaY = canvas.height / video.videoHeight;
        const [x, y, ancho, alto] = deteccion.bbox;
        const xEscalado = x * escalaX;
        const yEscalado = y * escalaY;
        const anchoEscalado = ancho * escalaX;
        const altoEscalado = alto * escalaY;

        ctx.strokeStyle = '#48BB78';
        ctx.lineWidth = 4;
        ctx.strokeRect(xEscalado, yEscalado, anchoEscalado, altoEscalado);

        const etiqueta = deteccion.class || '';
        if (etiqueta) {
            ctx.font = 'bold 16px sans-serif';
            const anchoTexto = ctx.measureText(etiqueta).width;
            const yEtiqueta = Math.max(0, yEscalado - 22);
            ctx.fillStyle = '#48BB78';
            ctx.fillRect(xEscalado, yEtiqueta, anchoTexto + 12, 22);
            ctx.fillStyle = '#FFFFFF';
            ctx.fillText(etiqueta, xEscalado + 6, yEtiqueta + 16);
        }
    }

    /**
     * Ejecuta un ciclo de detección de objetos sobre el frame actual del
     * video: corre el modelo, encuentra la detección más cercana al centro,
     * la dibuja en el canvas overlay y guarda su centro normalizado en
     * `deteccionPrioritariaActual` para usarlo al capturar. Usa el guard
     * `deteccionEnCurso` para no acumular llamadas a `detect()` si el
     * dispositivo es lento.
     * @returns {Promise<void>}
     */
    async function ejecutarCicloDeteccion() {
        if (deteccionEnCurso || !modeloDeteccion) {
            return;
        }
        deteccionEnCurso = true;

        try {
            const video = document.getElementById('video-camara');
            const canvas = document.getElementById('canvas-deteccion-vivo');
            if (!video || !canvas || video.videoWidth === 0) {
                return;
            }

            if (canvas.width !== canvas.clientWidth || canvas.height !== canvas.clientHeight) {
                canvas.width = canvas.clientWidth;
                canvas.height = canvas.clientHeight;
            }

            const detecciones = await modeloDeteccion.detect(video);
            const centroX = video.videoWidth / 2;
            const centroY = video.videoHeight / 2;
            const deteccionPriorizada = encontrarDeteccionMasCercanaAlCentro(detecciones, centroX, centroY);

            dibujarMarcoDeteccion(canvas, video, deteccionPriorizada);

            deteccionPrioritariaActual = deteccionPriorizada ? {
                x: (deteccionPriorizada.bbox[0] + deteccionPriorizada.bbox[2] / 2) / video.videoWidth,
                y: (deteccionPriorizada.bbox[1] + deteccionPriorizada.bbox[3] / 2) / video.videoHeight,
                clase: deteccionPriorizada.class || null,
            } : null;
        } catch (err) {
            console.error('Error durante la detección de objetos en vivo.', err);
        } finally {
            deteccionEnCurso = false;
        }
    }

    /**
     * Inicia el bucle de detección de objetos en vivo con un intervalo fijo
     * (no en cada frame de `requestAnimationFrame`, sería demasiado costoso
     * en dispositivos de gama baja). Es seguro llamarla varias veces: detiene
     * cualquier intervalo previo antes de arrancar uno nuevo. Si el modelo no
     * llegó a cargarse (degradación limpia), no hace nada.
     * @returns {void}
     */
    function iniciarDeteccionEnVivo() {
        detenerDeteccionEnVivo();
        if (!modeloDeteccion) {
            return;
        }
        idIntervaloDeteccion = setInterval(ejecutarCicloDeteccion, 280);
    }

    /**
     * Detiene el bucle de detección de objetos en vivo y limpia el canvas
     * overlay (y la detección priorizada guardada), usado al salir de
     * `#view-camera` para no gastar CPU/batería en otras vistas del flujo.
     * @returns {void}
     */
    function detenerDeteccionEnVivo() {
        if (idIntervaloDeteccion !== null) {
            clearInterval(idIntervaloDeteccion);
            idIntervaloDeteccion = null;
        }
        deteccionPrioritariaActual = null;
        const canvas = document.getElementById('canvas-deteccion-vivo');
        if (canvas) {
            const ctx = canvas.getContext('2d');
            ctx.clearRect(0, 0, canvas.width, canvas.height);
        }
    }

    /**
     * Captura el cuadro actual del video en un canvas, lo envía como imagen
     * JPEG en base64 al endpoint de captura y muestra el ejercicio generado.
     * @returns {Promise<void>}
     */
    async function capturarObjeto() {
        const video = document.getElementById('video-camara');
        const canvas = document.getElementById('canvas-captura');

        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
        const imagenBase64 = canvas.toDataURL('image/jpeg', 0.8);

        // Se guarda antes de detener el bucle, que limpia `deteccionPrioritariaActual`.
        const puntoObjetivo = deteccionPrioritariaActual;

        // La detección en vivo ya no es necesaria fuera de #view-camera.
        detenerDeteccionEnVivo();

        document.getElementById('global-header').classList.add('hidden');
        document.getElementById('global-header').classList.remove('flex');
        cambiarVista('view-camera', 'view-analyzing-obj');

        const formData = new FormData();
        formData.append('imagen', imagenBase64);
        if (puntoObjetivo) {
            formData.append('punto_objetivo', JSON.stringify({ x: puntoObjetivo.x, y: puntoObjetivo.y }));
            if (puntoObjetivo.clase) {
                formData.append('clase_offline', puntoObjetivo.clase);
            }
        }

        try {
            const response = await fetch(URL_CAPTURAR, {
                method: 'POST',
                headers: { 'X-CSRFToken': obtenerCsrfToken() },
                body: formData,
            });
            const data = await response.json();

            if (data.status === 'success') {
                mostrarEjercicio(data);
                await mostrarCajaDeteccion(canvas, data);
                cambiarVista('view-analyzing-obj', 'view-exercise');
            } else {
                alert('No pudimos reconocer el objeto. ' + data.message);
                volverAlVisor();
            }
        } catch (error) {
            console.error(error);
            alert('Hubo un problema comunicándose con el servidor.');
            volverAlVisor();
        }
    }

    /**
     * Dibuja sobre el canvas de captura (que ya contiene la foto tomada) un
     * resaltado de la caja de detección devuelta por el backend, y lo muestra
     * brevemente como confirmación visual de "esto es lo que reconocí" antes
     * de continuar con el flujo normal. Si no hay caja de detección, no
     * dibuja nada y continúa sin demora (degradación limpia).
     * @param {HTMLCanvasElement} canvas - Canvas `#canvas-captura` con la foto ya dibujada.
     * @param {{caja_deteccion: Array<{x: number, y: number}>|null, fuente_calificador: string|null}} data - Respuesta del endpoint de captura. Los puntos de `caja_deteccion` siempre vienen normalizados (fracción 0-1 del ancho/alto de la imagen).
     * @returns {Promise<void>}
     */
    function mostrarCajaDeteccion(canvas, data) {
        const cajaDeteccion = data.caja_deteccion;
        if (!cajaDeteccion || !Array.isArray(cajaDeteccion) || cajaDeteccion.length < 4) {
            return Promise.resolve();
        }

        const ctx = canvas.getContext('2d');
        const puntos = cajaDeteccion.map((punto) => ({
            x: punto.x * canvas.width,
            y: punto.y * canvas.height,
        }));

        // Color según si el objeto tiene un calificador (logo/texto) reconocido encima, solo para dar variedad visual.
        const colorTrazo = data.fuente_calificador === 'texto' ? '#3B82F6'
            : data.fuente_calificador === 'logo' ? '#F59E0B'
                : '#48BB78';

        ctx.lineWidth = Math.max(4, canvas.width * 0.008);
        ctx.strokeStyle = colorTrazo;
        ctx.lineJoin = 'round';
        ctx.beginPath();
        ctx.moveTo(puntos[0].x, puntos[0].y);
        for (let i = 1; i < puntos.length; i++) {
            ctx.lineTo(puntos[i].x, puntos[i].y);
        }
        ctx.closePath();
        ctx.stroke();

        // El canvas vive dentro de #view-camera (que ahora está oculta), así
        // que se muestra como overlay fijo centrado en el viewport para que
        // sea visible sobre #view-analyzing-obj sin alterar el flujo de vistas.
        canvas.classList.remove('hidden');
        canvas.classList.add(
            'fixed', 'top-1/2', 'left-1/2', 'z-50', 'max-w-[90vw]', 'max-h-[70vh]',
            'rounded-2xl', 'shadow-soft', 'border-8', 'border-white', 'transition-opacity', 'duration-300',
        );
        canvas.style.transform = 'translate(-50%, -50%)';
        canvas.style.opacity = '0';
        // Forzar reflow para que la transición de opacidad se aplique.
        // eslint-disable-next-line no-unused-expressions
        canvas.offsetWidth;
        canvas.style.opacity = '1';

        return new Promise((resolve) => {
            setTimeout(() => {
                canvas.style.opacity = '0';
                setTimeout(() => {
                    canvas.classList.add('hidden');
                    canvas.classList.remove(
                        'fixed', 'top-1/2', 'left-1/2', 'z-50', 'max-w-[90vw]', 'max-h-[70vh]',
                        'rounded-2xl', 'shadow-soft', 'border-8', 'border-white', 'transition-opacity', 'duration-300',
                    );
                    canvas.style.transform = '';
                    canvas.style.opacity = '';
                    resolve();
                }, 300);
            }, 800);
        });
    }

    /**
     * Vuelve a mostrar el visor de la cámara (`#view-camera`) y restaura el
     * encabezado global, usado cuando la captura o la evaluación fallan.
     * @returns {void}
     */
    function volverAlVisor() {
        document.getElementById('global-header').classList.remove('hidden');
        document.getElementById('global-header').classList.add('flex');
        cambiarVista('view-analyzing-obj', 'view-camera');
        iniciarDeteccionEnVivo();
    }

    /**
     * Pinta el ejercicio generado (objeto detectado y frase a leer) en
     * `#view-exercise` y guarda la frase para la lectura en voz alta y la
     * evaluación de pronunciación posterior.
     * @param {{objeto: string, frase_generada: string}} data - Respuesta del endpoint de captura.
     * @returns {void}
     */
    function mostrarEjercicio(data) {
        frasePronunciar = data.frase_generada;
        document.getElementById('exercise-titulo').textContent = `¡Encontré: ${data.objeto}!`;
        document.getElementById('frase-generada').textContent = data.frase_generada;
    }

    /**
     * Lee en voz alta la frase generada usando el motor de voz configurado
     * por el usuario (navegador o Azure neural, con fallback automático).
     * Deshabilita el botón "Escuchar" mientras dura la narración para
     * evitar pulsaciones repetidas (y llamadas duplicadas a la API de Azure).
     * @returns {Promise<void>}
     */
    async function leerFraseEnVozAlta() {
        const btnEscuchar = document.getElementById('btn-escuchar');
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
     * Inicia o detiene la grabación del audio del estudiante. Al detener,
     * codifica el audio capturado como WAV y lo envía al endpoint de
     * evaluación de pronunciación.
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

            cambiarVista('view-exercise', 'view-analyzing-voice');

            const samples = unirBuffers(audioBufferList, recordingLength);
            const audioBlob = codificarWAV(samples, sampleRateActual);

            await enviarEvaluacion(audioBlob);
        }
    }

    /**
     * Envía el audio grabado al endpoint de evaluación de pronunciación junto
     * con la frase generada y actualiza la vista de resultado con la respuesta.
     * @param {Blob} audioBlob - Audio codificado en WAV.
     * @returns {Promise<void>}
     */
    async function enviarEvaluacion(audioBlob) {
        const formData = new FormData();
        formData.append('audio', audioBlob, 'grabacion.wav');
        formData.append('frase_referencia', frasePronunciar);

        try {
            const response = await fetch(URL_EVALUAR, {
                method: 'POST',
                headers: { 'X-CSRFToken': obtenerCsrfToken() },
                body: formData,
            });
            const data = await response.json();

            if (data.status === 'success') {
                mostrarResultado(data);
                cambiarVista('view-analyzing-voice', 'view-result');
            } else {
                alert('No se pudo evaluar la pronunciación. ' + data.message);
                volverAlEjercicio();
            }
        } catch (error) {
            console.error(error);
            alert('Hubo un problema comunicándose con el servidor.');
            volverAlEjercicio();
        }
    }

    /**
     * Restaura el botón de grabar y vuelve a `#view-exercise`, usado cuando
     * la evaluación de pronunciación falla.
     * @returns {void}
     */
    function volverAlEjercicio() {
        const btnGrabar = document.getElementById('btn-grabar');
        const textGrabar = document.getElementById('text-grabar');
        btnGrabar.classList.remove('bg-error', 'text-white', 'animate-pulse');
        btnGrabar.classList.add('bg-white', 'text-error');
        textGrabar.textContent = 'Grabar';
        cambiarVista('view-analyzing-voice', 'view-exercise');
    }

    /**
     * Pinta los resultados de la evaluación en `#view-result`: puntaje,
     * mensaje del avatar y, si correspondieron, las monedas ganadas.
     * @param {Object} data - Respuesta JSON del endpoint de evaluación.
     * @returns {void}
     */
    function mostrarResultado(data) {
        const scoreRedondeado = Math.round(data.score);
        const colorPrincipal = data.correcta ? '#48BB78' : '#F56565';

        document.getElementById('score-text').textContent = `${scoreRedondeado}%`;
        document.getElementById('score-chart').style.background = `conic-gradient(${colorPrincipal} ${scoreRedondeado}%, #edf2f7 0)`;

        document.getElementById('resultado-titulo').textContent = data.correcta ? '¡Increíble!' : '¡Sigue practicando!';
        document.getElementById('resultado-subtitulo').textContent = data.correcta
            ? 'Leíste correctamente la frase.'
            : 'Casi lo logras, inténtalo de nuevo.';

        const elementoMensaje = document.getElementById('resultado-mensaje-avatar');
        if (data.reaccion_avatar && data.reaccion_avatar.mensaje) {
            elementoMensaje.textContent = data.reaccion_avatar.mensaje;
            window.dispatchEvent(new CustomEvent('AVATAR_EVENT', {
                detail: { tipo: data.reaccion_avatar.tipo, data: {} },
            }));
        } else {
            const tipoAutoAvatar = data.correcta ? 'pronunciacion_correcta' : 'pronunciacion_incorrecta';
            elementoMensaje.textContent = '';
            window.dispatchEvent(new CustomEvent('AVATAR_EVENT', {
                detail: { tipo: tipoAutoAvatar, data: {} },
            }));
        }

        const cajaMonedas = document.getElementById('caja-monedas');
        if (data.monedas_ganadas > 0) {
            document.getElementById('monedas-ganadas-text').textContent = `+ ${data.monedas_ganadas} Monedas`;
            cajaMonedas.classList.remove('hidden');
            cajaMonedas.classList.add('flex');
        } else {
            cajaMonedas.classList.add('hidden');
            cajaMonedas.classList.remove('flex');
        }

        // Restaurar el botón de grabar para el próximo intento.
        const btnGrabar = document.getElementById('btn-grabar');
        const textGrabar = document.getElementById('text-grabar');
        btnGrabar.classList.remove('bg-error', 'text-white', 'animate-pulse');
        btnGrabar.classList.add('bg-white', 'text-error');
        textGrabar.textContent = 'Grabar';
    }

    /**
     * Navega de vuelta a la pantalla principal de DysPlay.
     * @returns {void}
     */
    function volverDesdeEjercicio() {
        document.getElementById('global-header').classList.remove('hidden');
        document.getElementById('global-header').classList.add('flex');
        cambiarVista('view-exercise', 'view-camera');
        iniciarDeteccionEnVivo();
    }

    function goToMenu() {
        detenerDeteccionEnVivo();
        window.location.href = URL_HOME;
    }

    /**
     * Vuelve al visor de la cámara para capturar un nuevo objeto, mostrando
     * de nuevo el encabezado global.
     * @returns {void}
     */
    function resetCamera() {
        document.getElementById('global-header').classList.remove('hidden');
        document.getElementById('global-header').classList.add('flex');
        cambiarVista('view-result', 'view-camera');
        iniciarDeteccionEnVivo();
    }

    /**
     * Inicializa la página de Cámara Inteligente: solicita acceso a la
     * cámara y registra los listeners de los botones del flujo (capturar,
     * escuchar, grabar, salir al menú y nuevo objeto).
     * @returns {void}
     */
    function inicializar() {
        lucide.createIcons();
        iniciarCamara();

        document.getElementById('btn-capturar')?.addEventListener('click', capturarObjeto);
        document.getElementById('btn-escuchar')?.addEventListener('click', leerFraseEnVozAlta);
        document.getElementById('btn-grabar')?.addEventListener('click', alternarGrabacion);
        document.getElementById('btn-volver-ejercicio')?.addEventListener('click', volverDesdeEjercicio);
        document.getElementById('btn-salir-menu')?.addEventListener('click', goToMenu);
        document.getElementById('btn-nuevo-objeto')?.addEventListener('click', resetCamera);
    }

    document.addEventListener('DOMContentLoaded', inicializar);
})();
