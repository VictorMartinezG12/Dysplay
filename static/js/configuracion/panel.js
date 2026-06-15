/**
 * Lógica de la pantalla "Mi Configuración" (Módulo I - Accesibilidad).
 * Sincroniza el valor numérico mostrado junto a los controles deslizantes
 * de volumen (narración y música) cuando el usuario los mueve.
 */

/**
 * Vincula un input de tipo range con el elemento que muestra su valor
 * actual, actualizando el texto cada vez que el usuario lo modifica.
 * @param {string} inputId - id del elemento `<input type="range">`.
 * @param {string} valorId - id del elemento donde se muestra el porcentaje.
 * @returns {void}
 */
function vincularControlDeslizante(inputId, valorId) {
    const control = document.getElementById(inputId);
    const etiquetaValor = document.getElementById(valorId);

    if (!control || !etiquetaValor) {
        return;
    }

    control.addEventListener('input', () => {
        etiquetaValor.textContent = `${control.value}%`;
    });
}

document.addEventListener('DOMContentLoaded', () => {
    vincularControlDeslizante('input-volumen-narracion', 'valor-volumen-narracion');
    vincularControlDeslizante('input-volumen-musica', 'valor-volumen-musica');
});
