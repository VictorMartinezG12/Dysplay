/**
 * Previsualización en vivo del avatar dentro del panel de administración.
 *
 * El lienzo de referencia es siempre 500x500 (el mismo que usa Figma para
 * medir ropa/pelo/accesorios — ver doc/PANEL_ADMIN.md). Las posiciones (%)
 * de cada categoría son las MISMAS constantes usadas en producción
 * (avatar/templates/avatar/personalizar.html y componente.html): si se
 * cambian ahí, hay que cambiarlas aquí también.
 */
const POSICIONES_POR_CATEGORIA = {
    ropa_inferior: { left: '31%', top: '50%', width: '40.2%', height: '40.2%' },
    calzado: { left: '31.8%', top: '72.8%', width: '36.4%', height: '27.2%' },
    ropa_superior: { left: '28.2%', top: '37.4%', width: '43.6%', height: '35.4%' },
    cabello: { left: '19.4%', top: '-1.2%', width: '56.4%', height: '56.4%' },
    accesorio: { left: '30%', top: '-8%', width: '40%', height: '30%' },
};

// Slots de manga: se montan a pantalla completa (inset:0) porque ya vienen
// pre-posicionadas en un lienzo 500x500 propio (ver project_avatar_cuerpo_piezas).
const CAMPOS_MANGA = ['manga_sup_izq', 'manga_inf_izq', 'manga_sup_der', 'manga_inf_der'];

function aplicarPosicion(elemento, posicion) {
    if (!posicion) {
        elemento.style.inset = '0';
        elemento.style.left = '';
        elemento.style.top = '';
        elemento.style.width = '100%';
        elemento.style.height = '100%';
        return;
    }
    elemento.style.inset = 'auto';
    elemento.style.left = posicion.left;
    elemento.style.top = posicion.top;
    elemento.style.width = posicion.width;
    elemento.style.height = posicion.height;
}

function actualizarCapaPrincipal() {
    const selectCategoria = document.getElementById('id_categoria');
    const capa = document.getElementById('preview-imagen-principal');
    if (!selectCategoria || !capa) return;

    const categoria = selectCategoria.value;
    const tieneMangas = CAMPOS_MANGA.some((campo) => {
        const capaManga = document.getElementById(`preview-${campo}`);
        return capaManga && capaManga.style.display !== 'none';
    });

    // Con mangas cargadas, la imagen principal es el torso ya recortado
    // (lienzo completo 500x500); sin mangas, es la pieza recortada que se
    // estira dentro de la caja porcentual de su categoría.
    const posicion = tieneMangas ? null : POSICIONES_POR_CATEGORIA[categoria];
    aplicarPosicion(capa, posicion);

    // Mostrar/ocultar los inputs de manga: solo tienen sentido en ropa superior.
    document.querySelectorAll('[data-bloque-manga]').forEach((bloque) => {
        bloque.style.display = categoria === 'ropa_superior' ? '' : 'none';
    });
}

function previsualizarArchivo(input, idCapa) {
    const capa = document.getElementById(idCapa);
    if (!capa) return;
    const archivo = input.files && input.files[0];
    if (!archivo) {
        // El usuario canceló la selección: vuelve a mostrar (o no) la imagen
        // que ya existía antes de tocar el campo.
        capa.style.display = capa.dataset.teniaImagenInicial === '1' ? '' : 'none';
        actualizarCapaPrincipal();
        return;
    }
    capa.src = URL.createObjectURL(archivo);
    capa.style.display = '';
    actualizarCapaPrincipal();
}

document.addEventListener('DOMContentLoaded', () => {
    const selectCategoria = document.getElementById('id_categoria');
    if (selectCategoria) {
        selectCategoria.addEventListener('change', actualizarCapaPrincipal);
    }

    const inputPrincipal = document.getElementById('id_imagen');
    if (inputPrincipal) {
        inputPrincipal.addEventListener('change', () => previsualizarArchivo(inputPrincipal, 'preview-imagen-principal'));
    }

    CAMPOS_MANGA.forEach((campo) => {
        const input = document.getElementById(`id_${campo}`);
        if (input) {
            input.addEventListener('change', () => previsualizarArchivo(input, `preview-${campo}`));
        }
    });

    actualizarCapaPrincipal();
});
