/** @type {import('tailwindcss').Config} */
module.exports = {
  // Cubre todas las plantillas Django anidadas (apps + carpeta templates global) y JS estático
  content: [
    './**/templates/**/*.html',
    './static/js/**/*.js',
  ],
  theme: {
    extend: {
      colors: {
        // --- Tokens de base.html (sistema dinámico de temas/accesibilidad, Módulo I) ---
        dysPlayVerde: '#10B981',
        dysPlayAzul: '#3B82F6',
        dysPlayFondo: 'var(--color-fondo)',
        dysPlayTexto: 'var(--color-texto)',
        // 'primary' se mantiene como CSS var dinámica: base.html depende de esto
        // para que el Módulo I (accesibilidad/temas) pueda cambiar el color en runtime.
        primary: 'var(--color-primario)',
        secondary: '#C2410C',
        success: '#10B981',
        reward: '#C2410C',
        error: '#EF4444',

        // --- Tokens de las 5 plantillas standalone (camara, avatar, historias, estadisticas, niveles) ---
        // Estas plantillas no tienen las CSS vars de accesibilidad definidas, así que su
        // 'primary' original era un azul fijo (#3B82F6). Se renombra a 'primaryFijo' para
        // no chocar con el 'primary' dinámico de base.html.
        primaryFijo: '#3B82F6',
        bgBase: '#FFFBEB',
        textMain: '#1E293B',
        storyBg: '#1E3A8A',
      },
      fontFamily: {
        // Fuente dinámica de accesibilidad (base.html)
        dislexia: ['var(--global-font-family)'],
      },
      boxShadow: {
        // Valores de base.html (sistema principal con CSS vars)
        soft: '0px 8px 24px rgba(30, 41, 59, 0.06)',
        hard: '0px 8px 0px rgba(30, 41, 59, 0.12)',
        game: '0px 10px 0px #CBD5E0',
        'game-primary': '0px 10px 0px #1D4ED8',
        'game-success': '0px 10px 0px #047857',
        'game-warning': '0px 10px 0px #9A3412',
      },
    },
  },
  plugins: [],
}
