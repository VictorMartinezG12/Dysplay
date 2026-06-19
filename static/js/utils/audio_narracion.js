/**
 * Utilidad global de narración (Text-To-Speech) de DysPlay.
 *
 * Lee la configuración de accesibilidad de audio del usuario (inyectada por el
 * backend vía `json_script` en el elemento `#config-audio`) y construye un
 * `SpeechSynthesisUtterance` ya configurado con la velocidad, el volumen y,
 * de forma best-effort, la voz preferida del usuario.
 *
 * Pensado para ser cargado como script clásico (sin módulos ES, sin bundler)
 * y consumido desde los distintos módulos (historias, niveles, desafío, cámara)
 * a través de `window.crearUtteranceConfigurada`.
 */
(function () {
    'use strict';

    /** Valores por defecto si no se puede leer la configuración del usuario. */
    var CONFIG_AUDIO_DEFAULT = {
        velocidad_narracion: 'normal',
        tipo_voz: 'nino',
        volumen_narracion: 80,
        motor_voz: 'navegador'
    };

    /** Mapa de velocidad de narración (elegida por el usuario) a `rate` del utterance. */
    var MAPA_VELOCIDAD = {
        lenta: 0.5,
        normal: 0.85,
        rapida: 1.2
    };

    /**
     * Mapa de tipo de voz a `pitch` del utterance.
     *
     * Muchos navegadores (ej. Chrome) solo exponen 1-2 voces genéricas por
     * idioma, sin variantes de género/edad en el catálogo (`speechSynthesis
     * .getVoices()`), por lo que la selección de voz por nombre en
     * `seleccionarVozBestEffort` casi nunca encuentra coincidencia y el
     * usuario no percibe ningún cambio al modificar `tipo_voz` en ajustes.
     * El tono sí es soportado de forma universal por la Web Speech API y
     * permite que el ajuste sea audible incluso con una sola voz disponible.
     */
    var MAPA_PITCH = {
        nino: 1.5,
        nina: 1.65,
        'adulto-masculino': 0.75,
        'adulto-femenino': 1.1
    };

    /**
     * Lee y parsea la configuración de audio inyectada por el backend en el
     * elemento `#config-audio` (vía filtro `json_script` de Django).
     * Si el elemento no existe o el contenido no es JSON válido, se devuelven
     * los valores por defecto en vez de lanzar una excepción.
     * @returns {{velocidad_narracion: string, tipo_voz: string, volumen_narracion: number, motor_voz: string}}
     */
    function leerConfiguracionAudio() {
        try {
            var elemento = document.getElementById('config-audio');
            if (!elemento) {
                return CONFIG_AUDIO_DEFAULT;
            }
            var configLeida = JSON.parse(elemento.textContent);
            return {
                velocidad_narracion: configLeida.velocidad_narracion || CONFIG_AUDIO_DEFAULT.velocidad_narracion,
                tipo_voz: configLeida.tipo_voz || CONFIG_AUDIO_DEFAULT.tipo_voz,
                volumen_narracion: typeof configLeida.volumen_narracion === 'number'
                    ? configLeida.volumen_narracion
                    : CONFIG_AUDIO_DEFAULT.volumen_narracion,
                motor_voz: configLeida.motor_voz || CONFIG_AUDIO_DEFAULT.motor_voz
            };
        } catch (error) {
            return CONFIG_AUDIO_DEFAULT;
        }
    }

    /**
     * Selecciona, de forma best-effort, la voz del navegador más adecuada
     * según el idioma y el tipo de voz preferido por el usuario.
     *
     * NOTA: la disponibilidad y nombres de las voces dependen totalmente de la
     * plataforma/SO/navegador del usuario; esta heurística es aproximada y
     * puede no encontrar una coincidencia exacta (en ese caso no se asigna
     * `voice` y se usa la voz por defecto del navegador).
     * @param {string} lang - Idioma objetivo (ej. 'es-EC').
     * @param {string} tipoVoz - Tipo de voz preferido ('nino', 'nina',
     *   'adulto-masculino', 'adulto-femenino').
     * @returns {SpeechSynthesisVoice|null} Voz seleccionada o null si no hay coincidencia.
     */
    function seleccionarVozBestEffort(lang, tipoVoz) {
        if (!('speechSynthesis' in window)) {
            return null;
        }

        var voces = window.speechSynthesis.getVoices() || [];
        if (voces.length === 0) {
            return null;
        }

        var prefijoIdioma = (lang || 'es').slice(0, 2).toLowerCase();
        var vocesEnIdioma = voces.filter(function (voz) {
            return voz.lang && voz.lang.toLowerCase().indexOf(prefijoIdioma) === 0;
        });

        if (vocesEnIdioma.length === 0) {
            return null;
        }

        var esFemenino = tipoVoz === 'nina' || tipoVoz === 'adulto-femenino';
        var esMasculino = tipoVoz === 'nino' || tipoVoz === 'adulto-masculino';

        var vozPorGenero = vocesEnIdioma.find(function (voz) {
            var nombre = (voz.name || '').toLowerCase();
            if (esFemenino) {
                return nombre.indexOf('female') !== -1 || nombre.indexOf('mujer') !== -1
                    || nombre.indexOf('femenino') !== -1 || nombre.indexOf('femenina') !== -1;
            }
            if (esMasculino) {
                return nombre.indexOf('male') !== -1 || nombre.indexOf('hombre') !== -1
                    || nombre.indexOf('masculino') !== -1;
            }
            return false;
        });

        return vozPorGenero || vocesEnIdioma[0];
    }

    /**
     * Crea un `SpeechSynthesisUtterance` configurado con la velocidad, el
     * volumen y la voz preferidos por el usuario (leídos de `#config-audio`),
     * con valores por defecto seguros ante cualquier fallo.
     *
     * Si `speechSynthesis.getVoices()` aún no tiene voces cargadas, se intenta
     * escuchar una vez el evento `voiceschanged`, pero sin bloquear el flujo:
     * si para el momento de construir el utterance no hay voces disponibles,
     * simplemente se omite `utterance.voice` (queda la voz por defecto del
     * navegador) y el TTS nunca queda mudo ni lanza excepciones.
     * @param {string} texto - Texto a narrar.
     * @param {string} lang - Idioma fijo pasado por el módulo llamante (ej. 'es-EC').
     * @returns {SpeechSynthesisUtterance} Utterance listo para `speechSynthesis.speak()`.
     */
    function crearUtteranceConfigurada(texto, lang) {
        var configAudio = leerConfiguracionAudio();
        var utterance = new SpeechSynthesisUtterance(texto);

        utterance.lang = lang;
        utterance.rate = MAPA_VELOCIDAD[configAudio.velocidad_narracion] || MAPA_VELOCIDAD.normal;
        utterance.volume = Math.min(Math.max(configAudio.volumen_narracion / 100, 0), 1);
        utterance.pitch = MAPA_PITCH[configAudio.tipo_voz] || 1;

        try {
            if ('speechSynthesis' in window) {
                var vocesDisponibles = window.speechSynthesis.getVoices();
                if (!vocesDisponibles || vocesDisponibles.length === 0) {
                    window.speechSynthesis.addEventListener('voiceschanged', function () {
                        // Las voces ya estarán disponibles para próximas llamadas;
                        // no se modifica este utterance una vez creado.
                    }, { once: true });
                } else {
                    var voz = seleccionarVozBestEffort(lang, configAudio.tipo_voz);
                    if (voz) {
                        utterance.voice = voz;
                    }
                }
            }
        } catch (error) {
            // La selección de voz es best-effort: ante cualquier error se
            // continúa sin asignar `voice`, nunca se silencia el TTS.
        }

        return utterance;
    }

    /**
     * Obtiene el token CSRF desde el formulario o la cookie, para usarlo en
     * peticiones `fetch` con métodos que mutan estado (POST).
     * Mismo patrón usado en `historias.js` (`obtenerTokenCsrf`).
     * @returns {string} Token CSRF a enviar en la cabecera `X-CSRFToken`.
     */
    function obtenerTokenCsrf() {
        return document.querySelector('[name=csrfmiddlewaretoken]')?.value
            || document.cookie.split('; ').find(function (c) { return c.startsWith('csrftoken='); })?.split('=')[1]
            || '';
    }

    /**
     * Reproduce un audio sintetizado vía Web Speech API del navegador
     * (rama "navegador" / fallback de la rama "azure") y resuelve la promesa
     * cuando termina la narración (evento `onend` del utterance).
     * @param {string} texto - Texto a narrar.
     * @param {string} lang - Idioma fijo pasado por el módulo llamante (ej. 'es-EC').
     * @returns {Promise<void>} Promesa que resuelve cuando termina la narración.
     */
    function narrarConNavegador(texto, lang) {
        return new Promise(function (resolve) {
            if (!('speechSynthesis' in window)) {
                resolve();
                return;
            }
            var utterance = crearUtteranceConfigurada(texto, lang);
            utterance.onend = function () { resolve(); };
            utterance.onerror = function () { resolve(); };
            window.speechSynthesis.speak(utterance);
        });
    }

    /**
     * Narra un texto usando el motor de voz configurado por el usuario
     * (`motor_voz`: 'navegador' o 'azure'), con fallback automático a la Web
     * Speech API del navegador si el motor Azure falla por cualquier motivo
     * (sin credenciales, error de red, respuesta no exitosa, etc.), siguiendo
     * el principio "best-effort, nunca silencia" del módulo.
     *
     * Punto de entrada público recomendado para los módulos consumidores
     * (historias, niveles, desafío, cámara) en vez de invocar directamente
     * `speechSynthesis.speak(crearUtteranceConfigurada(...))`.
     * @param {string} texto - Texto a narrar.
     * @param {string} lang - Idioma fijo pasado por el módulo llamante (ej. 'es-EC').
     * @returns {Promise<void>} Promesa que resuelve cuando termina la narración
     *   (incluyendo los casos de fallback), para que el código llamante pueda
     *   deshabilitar/habilitar el botón "Escuchar" mientras dura.
     */
    async function narrarTexto(texto, lang) {
        var configAudio = leerConfiguracionAudio();

        if (configAudio.motor_voz !== 'azure') {
            return narrarConNavegador(texto, lang);
        }

        try {
            var respuesta = await fetch('/configuracion/audio/sintetizar/', {
                method: 'POST',
                headers: { 'X-CSRFToken': obtenerTokenCsrf() },
                body: new URLSearchParams({ texto: texto })
            });

            var tipoContenido = respuesta.headers.get('content-type') || '';
            if (!respuesta.ok || tipoContenido.indexOf('audio') === -1) {
                return await narrarConNavegador(texto, lang);
            }

            var blob = await respuesta.blob();
            var audio = new Audio(URL.createObjectURL(blob));
            return new Promise(function (resolve) {
                audio.onended = function () { resolve(); };
                audio.onerror = function () { resolve(); };
                audio.play().catch(function () { resolve(); });
            });
        } catch (error) {
            // Falla de red, Azure caído, etc.: nunca se relanza el error,
            // se cae automáticamente a la rama de navegador.
            return narrarConNavegador(texto, lang);
        }
    }

    window.crearUtteranceConfigurada = crearUtteranceConfigurada;
    window.narrarTexto = narrarTexto;
})();
