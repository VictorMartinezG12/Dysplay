from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from niveles.models import Nivel, ProgresoEstudiante

from . import services
from .models import ConfiguracionCamara, FraseTemplate

UsuarioCustom = get_user_model()

# Imagen PNG 1x1 válida (transparente) en base64, usada para probar el flujo de captura.
IMAGEN_PNG_VALIDA_BASE64 = (
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII='
)


def _crear_audio_wav_falso():
    """Genera un `SimpleUploadedFile` con una cabecera WAV mínima válida para python-magic."""
    cabecera_wav = (
        b'RIFF' + (36).to_bytes(4, 'little') + b'WAVEfmt '
        + (16).to_bytes(4, 'little')
        + (1).to_bytes(2, 'little') + (1).to_bytes(2, 'little')
        + (16000).to_bytes(4, 'little') + (32000).to_bytes(4, 'little')
        + (2).to_bytes(2, 'little') + (16).to_bytes(2, 'little')
        + b'data' + (0).to_bytes(4, 'little')
    )
    return SimpleUploadedFile("audio.wav", cabecera_wav, content_type="audio/wav")


# ---------------------------------------------------------------------------
# Tests de modelos
# ---------------------------------------------------------------------------
class FraseTemplateModelTests(TestCase):
    """Tests básicos del modelo `FraseTemplate`."""

    def test_str_incluye_objeto_y_nivel(self):
        frase = FraseTemplate.objects.create(
            objeto_keyword='lápiz',
            frase_plantilla='El lápiz es largo y amarillo.',
            nivel_dificultad=2,
            recompensa_monedas=10,
        )
        self.assertIn('lápiz', str(frase))
        self.assertIn('2', str(frase))


class ConfiguracionCamaraModelTests(TestCase):
    """Tests del modelo singleton `ConfiguracionCamara`."""

    def test_obtener_crea_registro_si_no_existe_con_modo_economico_falso(self):
        self.assertEqual(ConfiguracionCamara.objects.count(), 0)
        configuracion = ConfiguracionCamara.obtener()
        self.assertEqual(ConfiguracionCamara.objects.count(), 1)
        self.assertFalse(configuracion.modo_economico)

    def test_obtener_devuelve_el_mismo_registro_en_llamadas_sucesivas(self):
        primera = ConfiguracionCamara.obtener()
        primera.modo_economico = True
        primera.save()

        segunda = ConfiguracionCamara.obtener()

        self.assertEqual(primera.pk, segunda.pk)
        self.assertTrue(segunda.modo_economico)
        self.assertEqual(ConfiguracionCamara.objects.count(), 1)

    def test_save_fuerza_pk_1_sin_duplicar_registros(self):
        configuracion = ConfiguracionCamara(pk=99, modo_economico=True)
        configuracion.save()

        self.assertEqual(configuracion.pk, 1)
        self.assertEqual(ConfiguracionCamara.objects.count(), 1)
        self.assertEqual(ConfiguracionCamara.objects.get().pk, 1)


# ---------------------------------------------------------------------------
# Tests de `validar_imagen_base64`
# ---------------------------------------------------------------------------
class ValidarImagenBase64Tests(TestCase):
    """Tests de `services.validar_imagen_base64`."""

    def test_imagen_valida_retorna_base64_sin_prefijo(self):
        data_url = f'data:image/png;base64,{IMAGEN_PNG_VALIDA_BASE64}'
        resultado = services.validar_imagen_base64(data_url)
        self.assertEqual(resultado, IMAGEN_PNG_VALIDA_BASE64)

    def test_imagen_vacia_lanza_error(self):
        with self.assertRaises(ValueError):
            services.validar_imagen_base64('')

    def test_contenido_no_base64_lanza_error(self):
        with self.assertRaises(ValueError):
            services.validar_imagen_base64('esto no es base64 válido!!')

    def test_contenido_no_imagen_lanza_error(self):
        import base64
        texto_base64 = base64.b64encode(b'esto no es una imagen').decode('utf-8')
        with self.assertRaises(ValueError):
            services.validar_imagen_base64(texto_base64)


# ---------------------------------------------------------------------------
# Tests de `_texto_es_calificador_valido`
# ---------------------------------------------------------------------------
class TextoEsCalificadorValidoTests(TestCase):
    """Tests de `services._texto_es_calificador_valido`."""

    def test_texto_vacio_no_es_valido(self):
        self.assertFalse(services._texto_es_calificador_valido(''))
        self.assertFalse(services._texto_es_calificador_valido('   '))

    def test_palabra_real_es_valida(self):
        self.assertTrue(services._texto_es_calificador_valido('agua'))

    def test_codigo_de_serie_con_muchos_digitos_no_es_valido(self):
        # Caso real reportado: goma de borrar con "703064 44750" impreso.
        self.assertFalse(services._texto_es_calificador_valido('703064 44750'))

    def test_texto_demasiado_largo_no_es_valido(self):
        texto_largo = 'a' * (services.LONGITUD_MAXIMA_TEXTO_CALIFICADOR + 1)
        self.assertFalse(services._texto_es_calificador_valido(texto_largo))


# ---------------------------------------------------------------------------
# Tests de `_caja_contiene_centro`
# ---------------------------------------------------------------------------
class CajaContieneCentroTests(TestCase):
    """Tests de `services._caja_contiene_centro`."""

    def test_falta_alguna_caja_asume_solapamiento(self):
        self.assertTrue(services._caja_contiene_centro(None, [{'x': 0.5, 'y': 0.5}]))
        self.assertTrue(services._caja_contiene_centro([{'x': 0.1, 'y': 0.1}], None))
        self.assertTrue(services._caja_contiene_centro([], []))

    def test_centro_dentro_de_la_caja_devuelve_true(self):
        caja_objeto = [{'x': 0.1, 'y': 0.1}, {'x': 0.5, 'y': 0.1}, {'x': 0.5, 'y': 0.5}, {'x': 0.1, 'y': 0.5}]
        caja_interior = [{'x': 0.2, 'y': 0.2}, {'x': 0.3, 'y': 0.2}, {'x': 0.3, 'y': 0.3}, {'x': 0.2, 'y': 0.3}]
        self.assertTrue(services._caja_contiene_centro(caja_objeto, caja_interior))

    def test_centro_fuera_de_la_caja_devuelve_false(self):
        caja_objeto = [{'x': 0.0, 'y': 0.0}, {'x': 0.2, 'y': 0.0}, {'x': 0.2, 'y': 0.2}, {'x': 0.0, 'y': 0.2}]
        caja_interior = [{'x': 0.8, 'y': 0.8}, {'x': 1.0, 'y': 0.8}, {'x': 1.0, 'y': 1.0}, {'x': 0.8, 'y': 1.0}]
        self.assertFalse(services._caja_contiene_centro(caja_objeto, caja_interior))


# ---------------------------------------------------------------------------
# Tests de `_detectar_objeto_y_calificador`
# ---------------------------------------------------------------------------
class DetectarObjetoYCalificadorTests(TestCase):
    """Tests de `services._detectar_objeto_y_calificador`: el objeto siempre es la
    base, y un logo/texto solo califica si se solapa con el objeto y (si es texto)
    parece una palabra real."""

    CAJA_OBJETO = [{'x': 0.1, 'y': 0.1}, {'x': 0.4, 'y': 0.1}, {'x': 0.4, 'y': 0.4}, {'x': 0.1, 'y': 0.4}]
    CAJA_SOLAPADA = [{'x': 0.2, 'y': 0.2}, {'x': 0.3, 'y': 0.2}, {'x': 0.3, 'y': 0.3}, {'x': 0.2, 'y': 0.3}]
    CAJA_LEJANA = [{'x': 0.8, 'y': 0.8}, {'x': 1.0, 'y': 0.8}, {'x': 1.0, 'y': 1.0}, {'x': 0.8, 'y': 1.0}]

    def test_sin_etiquetas_devuelve_none_aunque_haya_logo_o_texto(self):
        resultado_vision = {
            'etiquetas': [],
            'logos': [{'description': 'Nike', 'score': 0.9, 'vertices': self.CAJA_SOLAPADA}],
            'texto': {'contenido': 'Hola mundo', 'vertices': self.CAJA_SOLAPADA},
        }
        self.assertIsNone(services._detectar_objeto_y_calificador(resultado_vision))

    def test_solo_objeto_sin_logo_ni_texto_calificador_none(self):
        resultado_vision = {
            'etiquetas': [{'description': 'pencil', 'score': 0.9, 'vertices': self.CAJA_OBJETO}],
            'logos': [],
            'texto': None,
        }
        resultado = services._detectar_objeto_y_calificador(resultado_vision)
        self.assertEqual(resultado['etiqueta_en'], 'pencil')
        self.assertIsNone(resultado['calificador'])
        self.assertIsNone(resultado['fuente_calificador'])

    def test_elige_etiqueta_de_mayor_score_entre_varios_objetos(self):
        resultado_vision = {
            'etiquetas': [
                {'description': 'pencil', 'score': 0.5, 'vertices': self.CAJA_OBJETO},
                {'description': 'book', 'score': 0.95, 'vertices': self.CAJA_OBJETO},
            ],
            'logos': [],
            'texto': None,
        }
        resultado = services._detectar_objeto_y_calificador(resultado_vision)
        self.assertEqual(resultado['etiqueta_en'], 'book')

    def test_logo_que_se_solapa_con_el_objeto_se_usa_como_calificador(self):
        resultado_vision = {
            'etiquetas': [{'description': 'bottle', 'score': 0.9, 'vertices': self.CAJA_OBJETO}],
            'logos': [{'description': 'Coca-Cola', 'score': 0.85, 'vertices': self.CAJA_SOLAPADA}],
            'texto': None,
        }
        resultado = services._detectar_objeto_y_calificador(resultado_vision)
        self.assertEqual(resultado['calificador'], 'Coca-Cola')
        self.assertEqual(resultado['fuente_calificador'], 'logo')

    def test_logo_que_no_se_solapa_se_ignora(self):
        resultado_vision = {
            'etiquetas': [{'description': 'bottle', 'score': 0.9, 'vertices': self.CAJA_OBJETO}],
            'logos': [{'description': 'Coca-Cola', 'score': 0.85, 'vertices': self.CAJA_LEJANA}],
            'texto': None,
        }
        resultado = services._detectar_objeto_y_calificador(resultado_vision)
        self.assertIsNone(resultado['calificador'])
        self.assertIsNone(resultado['fuente_calificador'])

    def test_texto_valido_que_se_solapa_se_usa_como_calificador(self):
        resultado_vision = {
            'etiquetas': [{'description': 'bottle', 'score': 0.9, 'vertices': self.CAJA_OBJETO}],
            'logos': [],
            'texto': {'contenido': 'agua', 'vertices': self.CAJA_SOLAPADA},
        }
        resultado = services._detectar_objeto_y_calificador(resultado_vision)
        self.assertEqual(resultado['calificador'], 'agua')
        self.assertEqual(resultado['fuente_calificador'], 'texto')

    def test_texto_tipo_codigo_que_se_solapa_se_ignora(self):
        # Caso real del bug reportado: goma de borrar con "703064 44750" impreso,
        # que antes generaba una frase sin sentido con ese código.
        resultado_vision = {
            'etiquetas': [{'description': 'eraser', 'score': 0.9, 'vertices': self.CAJA_OBJETO}],
            'logos': [],
            'texto': {'contenido': '703064 44750', 'vertices': self.CAJA_SOLAPADA},
        }
        resultado = services._detectar_objeto_y_calificador(resultado_vision)
        self.assertIsNone(resultado['calificador'])
        self.assertIsNone(resultado['fuente_calificador'])
        self.assertEqual(resultado['etiqueta_en'], 'eraser')

    def test_texto_valido_pero_que_no_se_solapa_se_ignora(self):
        resultado_vision = {
            'etiquetas': [{'description': 'bottle', 'score': 0.9, 'vertices': self.CAJA_OBJETO}],
            'logos': [],
            'texto': {'contenido': 'agua', 'vertices': self.CAJA_LEJANA},
        }
        resultado = services._detectar_objeto_y_calificador(resultado_vision)
        self.assertIsNone(resultado['calificador'])

    def test_logo_valido_tiene_prioridad_sobre_texto_valido(self):
        resultado_vision = {
            'etiquetas': [{'description': 'bottle', 'score': 0.9, 'vertices': self.CAJA_OBJETO}],
            'logos': [{'description': 'Coca-Cola', 'score': 0.85, 'vertices': self.CAJA_SOLAPADA}],
            'texto': {'contenido': 'agua', 'vertices': self.CAJA_SOLAPADA},
        }
        resultado = services._detectar_objeto_y_calificador(resultado_vision)
        self.assertEqual(resultado['calificador'], 'Coca-Cola')
        self.assertEqual(resultado['fuente_calificador'], 'logo')

    def test_etiqueta_tipo_barcode_se_descarta_aunque_tenga_mas_score(self):
        # Caso real del bug reportado: Vision identificó un código de barras
        # impreso en una goma de borrar como el "objeto" principal (con score
        # más alto que cualquier otra etiqueta), generando una frase sin
        # sentido ("1d barcode"). Debe descartarse e ignorar esa etiqueta.
        resultado_vision = {
            'etiquetas': [
                {'description': '1D Barcode', 'score': 0.95, 'vertices': self.CAJA_OBJETO},
                {'description': 'Eraser', 'score': 0.7, 'vertices': self.CAJA_OBJETO},
            ],
            'logos': [],
            'texto': None,
        }
        resultado = services._detectar_objeto_y_calificador(resultado_vision)
        self.assertEqual(resultado['etiqueta_en'], 'eraser')

    def test_solo_barcode_localizado_cae_a_etiquetas_generales(self):
        resultado_vision = {
            'etiquetas': [{'description': 'Barcode', 'score': 0.95, 'vertices': self.CAJA_OBJETO}],
            'etiquetas_generales': [
                {'description': 'Eraser', 'score': 0.8},
                {'description': 'Rubber', 'score': 0.6},
            ],
            'logos': [],
            'texto': None,
        }
        resultado = services._detectar_objeto_y_calificador(resultado_vision)
        self.assertEqual(resultado['etiqueta_en'], 'eraser')
        self.assertIsNone(resultado['vertices'])

    def test_sin_etiquetas_ni_generales_utilizables_devuelve_none(self):
        resultado_vision = {
            'etiquetas': [{'description': 'QR Code', 'score': 0.95, 'vertices': self.CAJA_OBJETO}],
            'etiquetas_generales': [{'description': 'Sticker', 'score': 0.5}],
            'logos': [],
            'texto': None,
        }
        self.assertIsNone(services._detectar_objeto_y_calificador(resultado_vision))


# ---------------------------------------------------------------------------
# Tests de `punto_objetivo` (apuntado en vivo con COCO-SSD) en `_detectar_objeto_y_calificador`
# ---------------------------------------------------------------------------
class PuntoObjetivoTests(TestCase):
    """Tests de `_sanear_punto_objetivo` y de cómo `punto_objetivo` influye en
    qué etiqueta se elige cuando hay varios objetos en la foto."""

    CAJA_IZQUIERDA = [{'x': 0.0, 'y': 0.0}, {'x': 0.2, 'y': 0.0}, {'x': 0.2, 'y': 0.2}, {'x': 0.0, 'y': 0.2}]
    CAJA_DERECHA = [{'x': 0.8, 'y': 0.8}, {'x': 1.0, 'y': 0.8}, {'x': 1.0, 'y': 1.0}, {'x': 0.8, 'y': 1.0}]

    def test_sanear_punto_objetivo_valido(self):
        self.assertEqual(services._sanear_punto_objetivo({'x': 0.5, 'y': 0.3}), {'x': 0.5, 'y': 0.3})

    def test_sanear_punto_objetivo_acota_fuera_de_rango(self):
        self.assertEqual(services._sanear_punto_objetivo({'x': 1.5, 'y': -0.2}), {'x': 1.0, 'y': 0.0})

    def test_sanear_punto_objetivo_invalido_devuelve_none(self):
        self.assertIsNone(services._sanear_punto_objetivo('no es un dict'))
        self.assertIsNone(services._sanear_punto_objetivo({'x': 'no es numero', 'y': 0.5}))
        self.assertIsNone(services._sanear_punto_objetivo(None))

    def test_punto_objetivo_dentro_de_etiqueta_no_top_la_elige(self):
        # "book" tiene más score que "pencil", pero el niño tenía centrado "pencil".
        resultado_vision = {
            'etiquetas': [
                {'description': 'book', 'score': 0.95, 'vertices': self.CAJA_DERECHA},
                {'description': 'pencil', 'score': 0.5, 'vertices': self.CAJA_IZQUIERDA},
            ],
            'logos': [],
            'texto': None,
        }
        resultado = services._detectar_objeto_y_calificador(resultado_vision, punto_objetivo={'x': 0.1, 'y': 0.1})
        self.assertEqual(resultado['etiqueta_en'], 'pencil')

    def test_punto_objetivo_fuera_de_toda_caja_usa_mayor_score_global(self):
        resultado_vision = {
            'etiquetas': [
                {'description': 'book', 'score': 0.95, 'vertices': self.CAJA_DERECHA},
                {'description': 'pencil', 'score': 0.5, 'vertices': self.CAJA_IZQUIERDA},
            ],
            'logos': [],
            'texto': None,
        }
        resultado = services._detectar_objeto_y_calificador(resultado_vision, punto_objetivo={'x': 0.5, 'y': 0.5})
        self.assertEqual(resultado['etiqueta_en'], 'book')

    def test_punto_objetivo_ausente_se_comporta_igual_que_antes(self):
        resultado_vision = {
            'etiquetas': [
                {'description': 'book', 'score': 0.95, 'vertices': self.CAJA_DERECHA},
                {'description': 'pencil', 'score': 0.5, 'vertices': self.CAJA_IZQUIERDA},
            ],
            'logos': [],
            'texto': None,
        }
        resultado = services._detectar_objeto_y_calificador(resultado_vision)
        self.assertEqual(resultado['etiqueta_en'], 'book')



# ---------------------------------------------------------------------------
# Tests de `generar_frase_deteccion`
# ---------------------------------------------------------------------------
class GenerarFraseDeteccionTests(TestCase):
    """Tests de `services.generar_frase_deteccion`."""

    def setUp(self):
        # Se limpia la caché entre tests para que el eco de corto plazo
        # (ver `CACHE_ECO_CAMARA_TIMEOUT_SEGUNDOS`) de un test no contamine
        # al siguiente, ya que varios reutilizan el mismo `usuario_id=1` y
        # la misma etiqueta ('pencil').
        cache.clear()
        self.addCleanup(cache.clear)

        # Se desactivan ambas llamadas al LLM en estos tests (parchando
        # `_traducir_objeto_llm` y `_generar_frase_llm` para que siempre
        # devuelvan `None`) para ejercitar el flujo de respaldo con
        # `TRADUCCION_OBJETOS`/`FraseTemplate`/`FRASE_GENERICA`, que es
        # lo que verifican estos tests.
        parche_traduccion = patch.object(services, '_traducir_objeto_llm', return_value=None)
        parche_traduccion.start()
        self.addCleanup(parche_traduccion.stop)

        parche_frase = patch.object(services, '_generar_frase_llm', return_value=None)
        parche_frase.start()
        self.addCleanup(parche_frase.stop)

        self.frase_facil = FraseTemplate.objects.create(
            objeto_keyword='lápiz',
            frase_plantilla='Frase fácil del lápiz.',
            nivel_dificultad=1,
            recompensa_monedas=5,
        )
        self.frase_dificil = FraseTemplate.objects.create(
            objeto_keyword='lápiz',
            frase_plantilla='Frase difícil del lápiz.',
            nivel_dificultad=4,
            recompensa_monedas=20,
        )

    def _resultado_vision_objeto(self, descripcion, score=0.9):
        return {
            'etiquetas': [{'description': descripcion, 'score': score, 'vertices': []}],
            'logos': [],
            'texto': None,
        }

    def test_sin_deteccion_devuelve_none(self):
        resultado_vision = {'etiquetas': [], 'logos': [], 'texto': None}
        self.assertIsNone(services.generar_frase_deteccion(resultado_vision, 1, usuario_id=1))

    def test_sin_etiquetas_devuelve_none_aunque_haya_logo_o_texto(self):
        # Ya no hay fallback a logo/texto solo: sin un objeto localizado por
        # Vision no hay nada que practicar.
        resultado_vision = {
            'etiquetas': [],
            'logos': [{'description': 'Nike', 'score': 0.9, 'vertices': []}],
            'texto': {'contenido': 'Hola mundo', 'vertices': []},
        }
        self.assertIsNone(services.generar_frase_deteccion(resultado_vision, nivel_usuario=1, usuario_id=1))

    def test_filtra_por_nivel_del_usuario(self):
        resultado_vision = self._resultado_vision_objeto('pencil')
        resultado = services.generar_frase_deteccion(resultado_vision, nivel_usuario=1, usuario_id=1)
        self.assertEqual(resultado['objeto'], 'lápiz')
        self.assertEqual(resultado['frase_generada'], self.frase_facil.frase_plantilla)
        self.assertIsNone(resultado['fuente_calificador'])

    def test_sin_frase_en_su_nivel_usa_cualquier_nivel_del_objeto(self):
        self.frase_facil.delete()
        resultado_vision = self._resultado_vision_objeto('pencil')
        resultado = services.generar_frase_deteccion(resultado_vision, nivel_usuario=1, usuario_id=1)
        self.assertEqual(resultado['frase_generada'], self.frase_dificil.frase_plantilla)

    def test_etiqueta_sin_traduccion_devuelve_frase_generica(self):
        resultado_vision = self._resultado_vision_objeto('unknown_object_xyz', score=0.8)
        resultado = services.generar_frase_deteccion(resultado_vision, nivel_usuario=1, usuario_id=1)
        self.assertEqual(resultado['objeto'], 'unknown_object_xyz')
        self.assertIn('unknown_object_xyz', resultado['frase_generada'])
        self.assertEqual(resultado['recompensa_monedas'], services.RECOMPENSA_MONEDAS_FALLBACK)

    def test_objeto_siempre_es_la_base_nunca_el_logo_o_texto_solo(self):
        # El calificador (logo/texto) solo enriquece el nombre del objeto; el
        # objeto detectado por Vision siempre es la base de la frase
        # (en este test, vía el fallback de emergencia con la etiqueta
        # traducida/respaldo, ya que el LLM está parchado para fallar).
        resultado_vision = {
            'etiquetas': [{'description': 'pencil', 'score': 0.9, 'vertices': []}],
            'logos': [{'description': 'Nike', 'score': 0.85, 'vertices': []}],
            'texto': {'contenido': 'Hola mundo', 'vertices': []},
        }
        resultado = services.generar_frase_deteccion(resultado_vision, nivel_usuario=1, usuario_id=1)
        self.assertEqual(resultado['objeto'], 'lápiz')
        self.assertNotEqual(resultado['objeto'], 'Nike')
        self.assertNotEqual(resultado['objeto'], 'Hola mundo')

    def test_traduccion_llm_exitosa_para_objeto_fuera_de_diccionario_no_expone_ingles(self):
        # Caso real que motivó separar la traducción de la generación de la
        # frase: 'dolphin' no está en TRADUCCION_OBJETOS, pero el LLM
        # de traducción sí lo traduce correctamente ('delfín'). Si luego el
        # LLM de generación de frase falla y no hay FraseTemplate para
        # 'delfín', el resultado final debe usar el nombre YA TRADUCIDO
        # ('delfín'), nunca la etiqueta cruda en inglés ('dolphin').
        with patch.object(services, '_traducir_objeto_llm', return_value='delfín'):
            resultado_vision = {
                'etiquetas': [{'description': 'dolphin', 'score': 0.9, 'vertices': []}],
                'logos': [],
                'texto': None,
            }
            resultado = services.generar_frase_deteccion(resultado_vision, nivel_usuario=1, usuario_id=1)

        self.assertEqual(resultado['objeto'], 'delfín')
        self.assertIn('delfín', resultado['frase_generada'])
        self.assertNotIn('dolphin', resultado['frase_generada'])
        self.assertEqual(resultado['recompensa_monedas'], services.RECOMPENSA_MONEDAS_FALLBACK)


# ---------------------------------------------------------------------------
# Tests del eco de corto plazo por estudiante en `generar_frase_deteccion`
# ---------------------------------------------------------------------------
class EcoCortoPlazoGenerarFraseDeteccionTests(TestCase):
    """Tests del eco de 15 minutos por estudiante (`CACHE_ECO_CAMARA_TIMEOUT_SEGUNDOS`)."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def _resultado_vision_objeto(self, descripcion='pencil', score=0.9):
        return {
            'etiquetas': [{'description': descripcion, 'score': score, 'vertices': []}],
            'logos': [],
            'texto': None,
        }

    @patch.object(services, '_generar_frase_llm', return_value='El lápiz amarillo escribe bonito.')
    @patch.object(services, '_traducir_objeto_llm', return_value='lápiz')
    def test_misma_deteccion_mismo_usuario_repite_frase_sin_invocar_llm_de_nuevo(self, mock_traducir, mock_frase):
        resultado_vision = self._resultado_vision_objeto()

        primera = services.generar_frase_deteccion(resultado_vision, nivel_usuario=1, usuario_id=42)
        mock_traducir.assert_called_once()
        mock_frase.assert_called_once()

        mock_traducir.reset_mock()
        mock_frase.reset_mock()

        segunda = services.generar_frase_deteccion(resultado_vision, nivel_usuario=1, usuario_id=42)

        self.assertEqual(primera['frase_generada'], segunda['frase_generada'])
        mock_traducir.assert_not_called()
        mock_frase.assert_not_called()

    @patch.object(services, '_generar_frase_llm', return_value='El lápiz amarillo escribe bonito.')
    @patch.object(services, '_traducir_objeto_llm', return_value='lápiz')
    def test_mismo_objeto_distinto_usuario_no_comparte_eco(self, mock_traducir, mock_frase):
        resultado_vision = self._resultado_vision_objeto()

        services.generar_frase_deteccion(resultado_vision, nivel_usuario=1, usuario_id=1)
        self.assertEqual(mock_traducir.call_count, 1)
        self.assertEqual(mock_frase.call_count, 1)

        services.generar_frase_deteccion(resultado_vision, nivel_usuario=1, usuario_id=2)
        self.assertEqual(mock_traducir.call_count, 2)
        self.assertEqual(mock_frase.call_count, 2)

    def test_eco_combina_caja_deteccion_actual_no_la_del_eco(self):
        caja_vieja = [{'x': 0.1, 'y': 0.1}, {'x': 0.2, 'y': 0.1}, {'x': 0.2, 'y': 0.2}, {'x': 0.1, 'y': 0.2}]
        caja_nueva = [{'x': 0.5, 'y': 0.5}, {'x': 0.6, 'y': 0.5}, {'x': 0.6, 'y': 0.6}, {'x': 0.5, 'y': 0.6}]

        with patch.object(services, '_traducir_objeto_llm', return_value='lápiz'), \
             patch.object(services, '_generar_frase_llm', return_value='El lápiz amarillo escribe bonito.'):
            resultado_vision_vieja = {
                'etiquetas': [{'description': 'pencil', 'score': 0.9, 'vertices': caja_vieja}],
                'logos': [], 'texto': None,
            }
            services.generar_frase_deteccion(resultado_vision_vieja, nivel_usuario=1, usuario_id=7)

        resultado_vision_nueva = {
            'etiquetas': [{'description': 'pencil', 'score': 0.9, 'vertices': caja_nueva}],
            'logos': [], 'texto': None,
        }
        with patch.object(services, '_traducir_objeto_llm') as mock_traducir:
            resultado = services.generar_frase_deteccion(resultado_vision_nueva, nivel_usuario=1, usuario_id=7)
            mock_traducir.assert_not_called()

        self.assertEqual(resultado['caja_deteccion'], caja_nueva)


# ---------------------------------------------------------------------------
# Tests de "modo económico" (`ConfiguracionCamara`) en `generar_frase_deteccion`
# ---------------------------------------------------------------------------
class ModoEconomicoGenerarFraseDeteccionTests(TestCase):
    """Tests del modo económico: nunca llama al LLM, usa diccionario fijo + FraseTemplate/FRASE_SOLO_NOMBRE."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        ConfiguracionCamara.objects.create(pk=1, modo_economico=True)

    def _resultado_vision_objeto(self, descripcion='pencil', score=0.9):
        return {
            'etiquetas': [{'description': descripcion, 'score': score, 'vertices': []}],
            'logos': [],
            'texto': None,
        }

    @patch.object(services, '_generar_frase_llm')
    @patch.object(services, '_traducir_objeto_llm')
    def test_modo_economico_no_llama_al_llm_y_usa_diccionario(self, mock_traducir, mock_frase):
        resultado_vision = self._resultado_vision_objeto('pencil')
        resultado = services.generar_frase_deteccion(resultado_vision, nivel_usuario=1, usuario_id=1)

        mock_traducir.assert_not_called()
        mock_frase.assert_not_called()
        self.assertEqual(resultado['objeto'], 'lápiz')

    @patch.object(services, '_generar_frase_llm')
    @patch.object(services, '_traducir_objeto_llm')
    def test_modo_economico_usa_frase_template_guardada_si_existe(self, mock_traducir, mock_frase):
        FraseTemplate.objects.create(
            objeto_keyword='lápiz',
            frase_plantilla='Frase curada del lápiz.',
            nivel_dificultad=1,
            recompensa_monedas=8,
        )
        resultado_vision = self._resultado_vision_objeto('pencil')
        resultado = services.generar_frase_deteccion(resultado_vision, nivel_usuario=1, usuario_id=1)

        self.assertEqual(resultado['frase_generada'], 'Frase curada del lápiz.')
        self.assertEqual(resultado['recompensa_monedas'], 8)
        mock_traducir.assert_not_called()
        mock_frase.assert_not_called()

    @patch.object(services, '_generar_frase_llm')
    @patch.object(services, '_traducir_objeto_llm')
    def test_modo_economico_sin_frase_template_usa_frase_solo_nombre(self, mock_traducir, mock_frase):
        resultado_vision = self._resultado_vision_objeto('pencil')
        resultado = services.generar_frase_deteccion(resultado_vision, nivel_usuario=1, usuario_id=1)

        self.assertIn('lápiz', resultado['frase_generada'])
        self.assertIn('Dilo en voz alta', resultado['frase_generada'])
        self.assertEqual(resultado['recompensa_monedas'], services.RECOMPENSA_MONEDAS_FALLBACK)
        mock_traducir.assert_not_called()
        mock_frase.assert_not_called()


# ---------------------------------------------------------------------------
# Tests de auto-guardado de `FraseTemplate` generadas con éxito por el LLM
# ---------------------------------------------------------------------------
class GuardarFraseTemplateAutomaticaTests(TestCase):
    """Tests de `services._guardar_frase_template_automatica` y su disparo desde `generar_frase_deteccion`."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_frase_exitosa_del_llm_se_guarda_como_frase_template_automatica(self):
        services._guardar_frase_template_automatica('lápiz', 1, 'El lápiz amarillo escribe bonito.')

        frase_guardada = FraseTemplate.objects.get(objeto_keyword='lápiz', nivel_dificultad=1)
        self.assertTrue(frase_guardada.creada_automaticamente)
        self.assertEqual(frase_guardada.frase_plantilla, 'El lápiz amarillo escribe bonito.')

    def test_misma_frase_exacta_dos_veces_no_se_duplica(self):
        services._guardar_frase_template_automatica('lápiz', 1, 'El lápiz amarillo escribe bonito.')
        services._guardar_frase_template_automatica('lápiz', 1, 'El lápiz amarillo escribe bonito.')

        self.assertEqual(
            FraseTemplate.objects.filter(objeto_keyword='lápiz', nivel_dificultad=1).count(), 1
        )

    def test_alcanzado_el_maximo_de_variantes_no_se_guarda_una_sexta(self):
        for indice in range(services.MAXIMO_VARIANTES_FRASE_AUTOGUARDADA):
            FraseTemplate.objects.create(
                objeto_keyword='lápiz',
                frase_plantilla=f'Variante número {indice} del lápiz.',
                nivel_dificultad=1,
                recompensa_monedas=5,
                creada_automaticamente=True,
            )

        services._guardar_frase_template_automatica('lápiz', 1, 'Una variante distinta y nueva del lápiz.')

        self.assertEqual(
            FraseTemplate.objects.filter(objeto_keyword='lápiz', nivel_dificultad=1).count(),
            services.MAXIMO_VARIANTES_FRASE_AUTOGUARDADA,
        )

    @patch.object(services, '_generar_frase_llm', return_value='El lápiz amarillo escribe bonito.')
    @patch.object(services, '_traducir_objeto_llm', return_value='lápiz')
    def test_generar_frase_deteccion_exitosa_dispara_el_autoguardado(self, mock_traducir, mock_frase):
        resultado_vision = {
            'etiquetas': [{'description': 'pencil', 'score': 0.9, 'vertices': []}],
            'logos': [], 'texto': None,
        }
        services.generar_frase_deteccion(resultado_vision, nivel_usuario=1, usuario_id=1)

        self.assertTrue(
            FraseTemplate.objects.filter(
                objeto_keyword='lápiz', nivel_dificultad=1, creada_automaticamente=True,
                frase_plantilla='El lápiz amarillo escribe bonito.',
            ).exists()
        )


# ---------------------------------------------------------------------------
# Tests de `_traducir_objeto_llm` y `_generar_frase_llm` (Azure OpenAI) y su cacheo
# ---------------------------------------------------------------------------
class TraducirObjetoLlmTests(TestCase):
    """Tests de `services._traducir_objeto_llm`, mockeando `AzureOpenAI` (sin red real)."""

    def setUp(self):
        cache.clear()

    def _mock_respuesta_llm(self, texto):
        """Construye un mock de la respuesta de `chat.completions.create`."""
        mensaje = MagicMock()
        mensaje.content = texto
        opcion = MagicMock()
        opcion.message = mensaje
        respuesta = MagicMock()
        respuesta.choices = [opcion]
        return respuesta

    @patch.object(services, 'AzureOpenAI')
    def test_exito_traduce_y_cachea(self, mock_clase_cliente):
        mock_cliente = MagicMock()
        mock_cliente.chat.completions.create.return_value = self._mock_respuesta_llm('lápiz')
        mock_clase_cliente.return_value = mock_cliente

        resultado = services._traducir_objeto_llm('pencil', None)

        self.assertEqual(resultado, 'lápiz')
        self.assertEqual(mock_cliente.chat.completions.create.call_count, 1)
        self.assertEqual(cache.get('traduccion_llm_camara_pencil_ninguno'), 'lápiz')

    @patch.object(services, 'AzureOpenAI')
    def test_con_calificador_no_traduce_el_calificador(self, mock_clase_cliente):
        mock_cliente = MagicMock()
        mock_cliente.chat.completions.create.return_value = self._mock_respuesta_llm('botella de agua')
        mock_clase_cliente.return_value = mock_cliente

        resultado = services._traducir_objeto_llm('bottle', 'agua')

        self.assertEqual(resultado, 'botella de agua')
        self.assertEqual(cache.get('traduccion_llm_camara_bottle_agua'), 'botella de agua')

    @patch.object(services, 'AzureOpenAI')
    def test_segunda_llamada_usa_cache_y_no_invoca_de_nuevo_al_llm(self, mock_clase_cliente):
        mock_cliente = MagicMock()
        mock_cliente.chat.completions.create.return_value = self._mock_respuesta_llm('gato')
        mock_clase_cliente.return_value = mock_cliente

        primera = services._traducir_objeto_llm('cat', None)
        segunda = services._traducir_objeto_llm('cat', None)

        self.assertEqual(primera, segunda)
        self.assertEqual(mock_cliente.chat.completions.create.call_count, 1)

    @patch.object(services, 'AzureOpenAI')
    def test_fallo_de_api_devuelve_none(self, mock_clase_cliente):
        mock_clase_cliente.side_effect = TimeoutError('la API no respondió a tiempo')

        resultado = services._traducir_objeto_llm('pencil', None)
        self.assertIsNone(resultado)

    @patch.object(services, 'AzureOpenAI')
    def test_respuesta_demasiado_larga_devuelve_none(self, mock_clase_cliente):
        mock_cliente = MagicMock()
        mock_cliente.chat.completions.create.return_value = self._mock_respuesta_llm(
            'No puedo traducir eso, podrías darme más contexto por favor para ayudarte mejor'
        )
        mock_clase_cliente.return_value = mock_cliente

        resultado = services._traducir_objeto_llm('pencil', None)
        self.assertIsNone(resultado)

    @patch.object(services, 'AzureOpenAI')
    def test_respuesta_vacia_devuelve_none(self, mock_clase_cliente):
        mock_cliente = MagicMock()
        mock_cliente.chat.completions.create.return_value = self._mock_respuesta_llm('   ')
        mock_clase_cliente.return_value = mock_cliente

        resultado = services._traducir_objeto_llm('pencil', None)
        self.assertIsNone(resultado)


class GenerarFraseLlmTests(TestCase):
    """Tests de `services._generar_frase_llm`, mockeando `AzureOpenAI` (sin red real)."""

    def setUp(self):
        cache.clear()

    def _mock_respuesta_llm(self, texto):
        """Construye un mock de la respuesta de `chat.completions.create`."""
        mensaje = MagicMock()
        mensaje.content = texto
        opcion = MagicMock()
        opcion.message = mensaje
        respuesta = MagicMock()
        respuesta.choices = [opcion]
        return respuesta

    @patch.object(services, 'AzureOpenAI')
    def test_exito_genera_y_cachea(self, mock_clase_cliente):
        mock_cliente = MagicMock()
        mock_cliente.chat.completions.create.return_value = self._mock_respuesta_llm(
            'El lápiz amarillo escribe en el cuaderno.'
        )
        mock_clase_cliente.return_value = mock_cliente

        resultado = services._generar_frase_llm('lápiz', 1)

        self.assertEqual(resultado, 'El lápiz amarillo escribe en el cuaderno.')
        self.assertEqual(mock_cliente.chat.completions.create.call_count, 1)
        self.assertEqual(cache.get('frase_llm_camara_lápiz_1'), resultado)

    @patch.object(services, 'AzureOpenAI')
    def test_segunda_llamada_usa_cache_y_no_invoca_de_nuevo_al_llm(self, mock_clase_cliente):
        mock_cliente = MagicMock()
        mock_cliente.chat.completions.create.return_value = self._mock_respuesta_llm(
            'El gato duerme en la silla.'
        )
        mock_clase_cliente.return_value = mock_cliente

        primera = services._generar_frase_llm('gato', 2)
        segunda = services._generar_frase_llm('gato', 2)

        self.assertEqual(primera, segunda)
        self.assertEqual(mock_cliente.chat.completions.create.call_count, 1)

    @patch.object(services, 'AzureOpenAI')
    def test_fallo_de_api_devuelve_none(self, mock_clase_cliente):
        mock_clase_cliente.side_effect = TimeoutError('la API no respondió a tiempo')

        resultado = services._generar_frase_llm('lápiz', 1)
        self.assertIsNone(resultado)

    @patch.object(services, 'AzureOpenAI')
    def test_respuesta_demasiado_larga_devuelve_none(self, mock_clase_cliente):
        mock_cliente = MagicMock()
        texto_largo = ' '.join(['palabra'] * 30)
        mock_cliente.chat.completions.create.return_value = self._mock_respuesta_llm(texto_largo)
        mock_clase_cliente.return_value = mock_cliente

        resultado = services._generar_frase_llm('lápiz', 1)
        self.assertIsNone(resultado)

    @patch.object(services, 'AzureOpenAI')
    def test_respuesta_vacia_devuelve_none(self, mock_clase_cliente):
        mock_cliente = MagicMock()
        mock_cliente.chat.completions.create.return_value = self._mock_respuesta_llm('')
        mock_clase_cliente.return_value = mock_cliente

        resultado = services._generar_frase_llm('lápiz', 1)
        self.assertIsNone(resultado)

    @patch.object(services, 'AzureOpenAI')
    def test_repeticion_degenerada_de_palabra_devuelve_none(self, mock_clase_cliente):
        # Caso real reportado: el modelo arranca bien y luego se "atasca"
        # repitiendo la misma palabra muchas veces seguidas.
        mock_cliente = MagicMock()
        mock_cliente.chat.completions.create.return_value = self._mock_respuesta_llm(
            'Pelo del perro con el peine de plata, peina peina peina peina peina.'
        )
        mock_clase_cliente.return_value = mock_cliente

        resultado = services._generar_frase_llm('peine', 1)
        self.assertIsNone(resultado)


# ---------------------------------------------------------------------------
# Tests de `_tiene_repeticion_degenerada`
# ---------------------------------------------------------------------------
class TieneRepeticionDegeneradaTests(TestCase):
    """Tests de `services._tiene_repeticion_degenerada`."""

    def test_caso_real_reportado_es_degenerado(self):
        texto = 'Pelo del perro con el peine de plata, peina peina peina peina peina, peina peina peina peina peina.'
        self.assertTrue(services._tiene_repeticion_degenerada(texto))

    def test_frase_normal_no_es_degenerada(self):
        self.assertFalse(services._tiene_repeticion_degenerada('Tres tristes tigres trillan trigo en un trigal.'))

    def test_repeticion_de_dos_o_tres_veces_no_es_degenerada(self):
        self.assertFalse(services._tiene_repeticion_degenerada('Lupita pule, pule, pule el lápiz lila.'))

    def test_texto_vacio_no_es_degenerado(self):
        self.assertFalse(services._tiene_repeticion_degenerada(''))


# ---------------------------------------------------------------------------
# Tests de `_nivel_dificultad_usuario`
# ---------------------------------------------------------------------------
class NivelDificultadUsuarioTests(TestCase):
    """Tests de `services._nivel_dificultad_usuario`."""

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(username='cam_nivel_user', password='claveSegura123')

    def test_sin_progreso_devuelve_nivel_1(self):
        self.assertEqual(services._nivel_dificultad_usuario(self.usuario), 1)

    def test_nivel_alto_se_acota_a_5(self):
        nivel = Nivel.objects.create(numero=8, titulo='Avanzado', puntos_recompensa=50)
        ProgresoEstudiante.objects.create(usuario=self.usuario, nivel_actual=nivel)
        self.assertEqual(services._nivel_dificultad_usuario(self.usuario), 5)


# ---------------------------------------------------------------------------
# Tests de la vista `camara_view`
# ---------------------------------------------------------------------------
class CamaraViewTests(TestCase):
    """Verifica autenticación y render de `camara_view`."""

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(username='cam_view_user', password='claveSegura123')

    def test_redirige_si_no_hay_sesion(self):
        response = self.client.get(reverse('camara'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_renderiza_200_con_sesion(self):
        self.client.login(username='cam_view_user', password='claveSegura123')
        response = self.client.get(reverse('camara'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'camara_inteligente/camara.html')


# ---------------------------------------------------------------------------
# Tests de la vista `capturar_objeto`
# ---------------------------------------------------------------------------
class CapturarObjetoViewTests(TestCase):
    """Verifica autenticación, validaciones y respuesta de `capturar_objeto`."""

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(username='cam_captura_user', password='claveSegura123')
        self.client.login(username='cam_captura_user', password='claveSegura123')
        FraseTemplate.objects.create(
            objeto_keyword='lápiz',
            frase_plantilla='El lápiz es largo y amarillo.',
            nivel_dificultad=1,
            recompensa_monedas=5,
        )

    def test_requiere_login(self):
        self.client.logout()
        response = self.client.post(reverse('camara_capturar'), {})
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_metodo_get_no_permitido(self):
        response = self.client.get(reverse('camara_capturar'))
        self.assertEqual(response.status_code, 405)

    @patch.object(services, '_generar_frase_llm', return_value=None)
    @patch.object(services, '_traducir_objeto_llm', return_value=None)
    @patch.object(services, 'analizar_imagen_google_vision')
    def test_captura_exitosa_devuelve_frase_generada(self, mock_vision, mock_traducir_llm, mock_frase_llm):
        mock_vision.return_value = {
            'status': 'success',
            'etiquetas': [{'description': 'pencil', 'score': 0.95, 'vertices': []}],
            'logos': [],
            'texto': None,
        }
        response = self.client.post(reverse('camara_capturar'), {
            'imagen': f'data:image/png;base64,{IMAGEN_PNG_VALIDA_BASE64}',
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['objeto'], 'lápiz')
        self.assertEqual(data['frase_generada'], 'El lápiz es largo y amarillo.')
        self.assertIsNone(data['fuente_calificador'])

    def test_imagen_invalida_no_expone_detalles_internos(self):
        response = self.client.post(reverse('camara_capturar'), {'imagen': 'esto-no-es-base64!!'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'error')
        self.assertNotIn('Traceback', data['message'])
        self.assertNotIn('.py', data['message'])

    @patch.object(services, '_generar_frase_llm', return_value=None)
    @patch.object(services, '_traducir_objeto_llm', return_value=None)
    @patch.object(services, 'analizar_imagen_google_vision')
    def test_punto_objetivo_valido_elige_la_etiqueta_apuntada(self, mock_vision, mock_traducir_llm, mock_frase_llm):
        caja_lapiz = [{'x': 0.0, 'y': 0.0}, {'x': 0.2, 'y': 0.0}, {'x': 0.2, 'y': 0.2}, {'x': 0.0, 'y': 0.2}]
        caja_libro = [{'x': 0.8, 'y': 0.8}, {'x': 1.0, 'y': 0.8}, {'x': 1.0, 'y': 1.0}, {'x': 0.8, 'y': 1.0}]
        mock_vision.return_value = {
            'status': 'success',
            'etiquetas': [
                {'description': 'book', 'score': 0.95, 'vertices': caja_libro},
                {'description': 'pencil', 'score': 0.5, 'vertices': caja_lapiz},
            ],
            'logos': [],
            'texto': None,
        }
        response = self.client.post(reverse('camara_capturar'), {
            'imagen': f'data:image/png;base64,{IMAGEN_PNG_VALIDA_BASE64}',
            'punto_objetivo': '{"x": 0.1, "y": 0.1}',
        })
        data = response.json()
        self.assertEqual(data['objeto'], 'lápiz')

    @patch.object(services, '_generar_frase_llm', return_value=None)
    @patch.object(services, '_traducir_objeto_llm', return_value=None)
    @patch.object(services, 'analizar_imagen_google_vision')
    def test_punto_objetivo_malformado_no_rompe_la_captura(self, mock_vision, mock_traducir_llm, mock_frase_llm):
        mock_vision.return_value = {
            'status': 'success',
            'etiquetas': [{'description': 'pencil', 'score': 0.95, 'vertices': []}],
            'logos': [],
            'texto': None,
        }
        response = self.client.post(reverse('camara_capturar'), {
            'imagen': f'data:image/png;base64,{IMAGEN_PNG_VALIDA_BASE64}',
            'punto_objetivo': 'esto no es JSON válido',
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['objeto'], 'lápiz')


# ---------------------------------------------------------------------------
# Tests de la vista `evaluar_pronunciacion`
# ---------------------------------------------------------------------------
class EvaluarPronunciacionViewTests(TestCase):
    """Verifica autenticación, validaciones y otorgamiento de monedas de `evaluar_pronunciacion`."""

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(username='cam_eval_user', password='claveSegura123', monedas=0)
        self.client.login(username='cam_eval_user', password='claveSegura123')
        self.frase = FraseTemplate.objects.create(
            objeto_keyword='lápiz',
            frase_plantilla='El lápiz es largo y amarillo.',
            nivel_dificultad=1,
            recompensa_monedas=5,
        )

    def test_requiere_login(self):
        self.client.logout()
        response = self.client.post(reverse('camara_evaluar'), {})
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_sin_frase_referencia_devuelve_error(self):
        response = self.client.post(reverse('camara_evaluar'), {'audio': _crear_audio_wav_falso()})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'error')

    @patch.object(services, 'evaluar_pronunciacion_azure')
    def test_pronunciacion_correcta_otorga_monedas(self, mock_evaluar):
        mock_evaluar.return_value = {
            'status': 'success',
            'score_global': 90,
            'score_exactitud': 92,
            'palabras': [],
        }
        response = self.client.post(reverse('camara_evaluar'), {
            'audio': _crear_audio_wav_falso(),
            'frase_referencia': self.frase.frase_plantilla,
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'success')
        self.assertTrue(data['correcta'])
        self.assertEqual(data['monedas_ganadas'], 5)

        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.monedas, 5)

    @patch.object(services, 'evaluar_pronunciacion_azure')
    def test_pronunciacion_incorrecta_no_otorga_monedas(self, mock_evaluar):
        mock_evaluar.return_value = {
            'status': 'success',
            'score_global': 40,
            'score_exactitud': 35,
            'palabras': [],
        }
        response = self.client.post(reverse('camara_evaluar'), {
            'audio': _crear_audio_wav_falso(),
            'frase_referencia': self.frase.frase_plantilla,
        })
        data = response.json()
        self.assertFalse(data['correcta'])
        self.assertEqual(data['monedas_ganadas'], 0)

        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.monedas, 0)
