/**
 * Previsualización en vivo del formulario de CaraAvatar (panel_admin).
 * Lee la URL inicial de `imagen_parpadeo` desde el `json_script` que el
 * template renderiza con id="dato-imagen-parpadeo-inicial".
 */
document.addEventListener('DOMContentLoaded', () => {
    const elementoDato = document.getElementById('dato-imagen-parpadeo-inicial');
    const urlImagenParpadeoInicial = elementoDato ? JSON.parse(elementoDato.textContent) : '';

    const capa = document.getElementById('preview-cara');
    if (!capa) return;

    const inputImagen = document.getElementById('id_imagen');
    if (inputImagen) {
        inputImagen.addEventListener('change', () => {
            const archivo = inputImagen.files && inputImagen.files[0];
            if (!archivo) return;
            capa.src = URL.createObjectURL(archivo);
            capa.style.display = '';
        });
    }

    const urlNormal = capa.src;
    const inputParpadeo = document.getElementById('id_imagen_parpadeo');
    const botonParpadeo = document.getElementById('boton-ver-parpadeo');
    let mostrandoParpadeo = false;

    function urlParpadeoActual() {
        const archivo = inputParpadeo && inputParpadeo.files && inputParpadeo.files[0];
        return archivo ? URL.createObjectURL(archivo) : urlImagenParpadeoInicial;
    }

    if (inputParpadeo) {
        inputParpadeo.addEventListener('change', () => {
            const archivo = inputParpadeo.files && inputParpadeo.files[0];
            if (archivo && botonParpadeo) botonParpadeo.classList.remove('hidden');
        });
    }

    if (botonParpadeo) {
        botonParpadeo.addEventListener('click', () => {
            mostrandoParpadeo = !mostrandoParpadeo;
            capa.src = mostrandoParpadeo ? urlParpadeoActual() : urlNormal;
            botonParpadeo.textContent = mostrandoParpadeo ? '👁️ Ver normal' : '👁️ Ver variante de parpadeo';
        });
    }
});
