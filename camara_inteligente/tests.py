from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from niveles.models import Nivel, ProgresoEstudiante, ProgresoNivel

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

    def test_imagen_valida_retorna_bytes_y_mime_type(self):
        import base64
        data_url = f'data:image/png;base64,{IMAGEN_PNG_VALIDA_BASE64}'
        imagen_bytes, mime_type = services.validar_imagen_base64(data_url)
        self.assertEqual(imagen_bytes, base64.b64decode(IMAGEN_PNG_VALIDA_BASE64))
        self.assertEqual(mime_type, 'image/png')

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
# Tests de `_sanear_punto_objetivo` / `_sanear_clase_offline`
# ---------------------------------------------------------------------------
class SanearEntradasClienteTests(TestCase):
    """Tests de las funciones defensivas que sanean entradas enviadas por el cliente."""

    def test_sanear_punto_objetivo_valido(self):
        self.assertEqual(services._sanear_punto_objetivo({'x': 0.5, 'y': 0.3}), {'x': 0.5, 'y': 0.3})

    def test_sanear_punto_objetivo_acota_fuera_de_rango(self):
        self.assertEqual(services._sanear_punto_objetivo({'x': 1.5, 'y': -0.2}), {'x': 1.0, 'y': 0.0})

    def test_sanear_punto_objetivo_invalido_devuelve_none(self):
        self.assertIsNone(services._sanear_punto_objetivo('no es un dict'))
        self.assertIsNone(services._sanear_punto_objetivo({'x': 'no es numero', 'y': 0.5}))
        self.assertIsNone(services._sanear_punto_objetivo(None))

    def test_sanear_clase_offline_valida(self):
        self.assertEqual(services._sanear_clase_offline('bottle'), 'bottle')
        self.assertEqual(services._sanear_clase_offline('  Bottle  '), 'bottle')

    def test_sanear_clase_offline_invalida_devuelve_none(self):
        self.assertIsNone(services._sanear_clase_offline(''))
        self.assertIsNone(services._sanear_clase_offline('   '))
        self.assertIsNone(services._sanear_clase_offline(None))
        self.assertIsNone(services._sanear_clase_offline(123))
        self.assertIsNone(services._sanear_clase_offline('x' * (services.LONGITUD_MAXIMA_CLASE_OFFLINE + 1)))


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
        # Con 35+ niveles completados se alcanza la dificultad máxima (5).
        progreso = ProgresoEstudiante.objects.create(usuario=self.usuario)
        for i in range(35):
            nivel = Nivel.objects.create(numero=100 + i, titulo=f'Nivel {i}', puntos_recompensa=50)
            ProgresoNivel.objects.create(progreso=progreso, nivel=nivel, mejores_estrellas=2)
        self.assertEqual(services._nivel_dificultad_usuario(self.usuario), 5)


# ---------------------------------------------------------------------------
# Tests de `_generar_objeto_y_frase_gemini` (mockeando el cliente de Gemini,
# sin red real)
# ---------------------------------------------------------------------------
class GenerarObjetoYFraseGeminiTests(TestCase):
    """Tests de `services._generar_objeto_y_frase_gemini`."""

    def _mock_respuesta_gemini(self, texto):
        respuesta = MagicMock()
        respuesta.text = texto
        return respuesta

    @patch.object(services.genai, 'Client')
    def test_exito_devuelve_objeto_y_frase(self, mock_clase_cliente):
        mock_cliente = MagicMock()
        mock_cliente.models.generate_content.return_value = self._mock_respuesta_gemini(
            '{"objeto": "lápiz", "frase": "El lápiz amarillo escribe bonito."}'
        )
        mock_clase_cliente.return_value = mock_cliente

        resultado = services._generar_objeto_y_frase_gemini(b'fakebytes', 'image/jpeg', 2, None)

        self.assertEqual(resultado, {'objeto': 'lápiz', 'frase': 'El lápiz amarillo escribe bonito.'})

    @patch.object(services.genai, 'Client')
    def test_respuesta_envuelta_en_markdown_se_parsea_igual(self, mock_clase_cliente):
        mock_cliente = MagicMock()
        mock_cliente.models.generate_content.return_value = self._mock_respuesta_gemini(
            '```json\n{"objeto": "gato", "frase": "El gato duerme en la silla."}\n```'
        )
        mock_clase_cliente.return_value = mock_cliente

        resultado = services._generar_objeto_y_frase_gemini(b'fakebytes', 'image/jpeg', 1, None)

        self.assertEqual(resultado['objeto'], 'gato')

    @patch.object(services.genai, 'Client')
    def test_json_invalido_devuelve_none(self, mock_clase_cliente):
        mock_cliente = MagicMock()
        mock_cliente.models.generate_content.return_value = self._mock_respuesta_gemini('esto no es JSON')
        mock_clase_cliente.return_value = mock_cliente

        self.assertIsNone(services._generar_objeto_y_frase_gemini(b'fakebytes', 'image/jpeg', 1, None))

    @patch.object(services.genai, 'Client')
    def test_falla_la_conexion_devuelve_none(self, mock_clase_cliente):
        mock_clase_cliente.side_effect = TimeoutError('la API no respondió a tiempo')

        self.assertIsNone(services._generar_objeto_y_frase_gemini(b'fakebytes', 'image/jpeg', 1, None))

    @patch.object(services.genai, 'Client')
    def test_frase_degenerada_devuelve_none(self, mock_clase_cliente):
        mock_cliente = MagicMock()
        mock_cliente.models.generate_content.return_value = self._mock_respuesta_gemini(
            '{"objeto": "peine", "frase": "peina peina peina peina peina peina."}'
        )
        mock_clase_cliente.return_value = mock_cliente

        self.assertIsNone(services._generar_objeto_y_frase_gemini(b'fakebytes', 'image/jpeg', 1, None))

    @patch.object(services.genai, 'Client')
    def test_objeto_o_frase_vacios_devuelve_none(self, mock_clase_cliente):
        mock_cliente = MagicMock()
        mock_cliente.models.generate_content.return_value = self._mock_respuesta_gemini(
            '{"objeto": "", "frase": "Una frase cualquiera."}'
        )
        mock_clase_cliente.return_value = mock_cliente

        self.assertIsNone(services._generar_objeto_y_frase_gemini(b'fakebytes', 'image/jpeg', 1, None))


# ---------------------------------------------------------------------------
# Tests de `generar_objeto_y_frase`
# ---------------------------------------------------------------------------
class GenerarObjetoYFraseTests(TestCase):
    """Tests de `services.generar_objeto_y_frase` (modo normal, con Gemini mockeado)."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

        self.frase_facil = FraseTemplate.objects.create(
            objeto_keyword='lápiz',
            frase_plantilla='Frase fácil del lápiz.',
            nivel_dificultad=1,
            recompensa_monedas=5,
        )

    @patch.object(services, '_generar_objeto_y_frase_gemini')
    def test_gemini_exitoso_devuelve_objeto_y_frase_y_autoguarda(self, mock_gemini):
        mock_gemini.return_value = {'objeto': 'delfín', 'frase': 'El delfín salta en el mar azul.'}

        resultado = services.generar_objeto_y_frase(b'fakebytes', 'image/jpeg', 3, usuario_id=1)

        self.assertEqual(resultado['objeto'], 'delfín')
        self.assertEqual(resultado['frase_generada'], 'El delfín salta en el mar azul.')
        self.assertIsNone(resultado['caja_deteccion'])
        self.assertIsNone(resultado['fuente_calificador'])
        self.assertTrue(
            FraseTemplate.objects.filter(objeto_keyword='delfín', creada_automaticamente=True).exists()
        )

    @patch.object(services, '_generar_objeto_y_frase_gemini', return_value=None)
    def test_gemini_falla_con_clase_offline_cae_a_diccionario_y_frase_template(self, mock_gemini):
        resultado = services.generar_objeto_y_frase(
            b'fakebytes', 'image/jpeg', 1, usuario_id=1, clase_offline='pencil',
        )

        self.assertEqual(resultado['objeto'], 'lápiz')
        self.assertEqual(resultado['frase_generada'], self.frase_facil.frase_plantilla)

    @patch.object(services, '_generar_objeto_y_frase_gemini', return_value=None)
    def test_gemini_falla_sin_clase_offline_usa_objeto_generico(self, mock_gemini):
        resultado = services.generar_objeto_y_frase(b'fakebytes', 'image/jpeg', 1, usuario_id=1)

        self.assertEqual(resultado['objeto'], services.OBJETO_GENERICO_SIN_IDENTIFICAR)
        self.assertIn(services.OBJETO_GENERICO_SIN_IDENTIFICAR, resultado['frase_generada'])


# ---------------------------------------------------------------------------
# Tests del eco de corto plazo por estudiante en `generar_objeto_y_frase`
# ---------------------------------------------------------------------------
class EcoCortoPlazoGenerarObjetoYFraseTests(TestCase):
    """Tests del eco de 15 minutos por estudiante, indexado por `clase_offline`."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    @patch.object(services, '_generar_objeto_y_frase_gemini')
    def test_misma_clase_mismo_usuario_repite_frase_sin_invocar_gemini_de_nuevo(self, mock_gemini):
        mock_gemini.return_value = {'objeto': 'lápiz', 'frase': 'El lápiz amarillo escribe bonito.'}

        primera = services.generar_objeto_y_frase(b'fakebytes', 'image/jpeg', 1, usuario_id=42, clase_offline='pencil')
        mock_gemini.assert_called_once()

        mock_gemini.reset_mock()
        segunda = services.generar_objeto_y_frase(b'fakebytes', 'image/jpeg', 1, usuario_id=42, clase_offline='pencil')

        self.assertEqual(primera['frase_generada'], segunda['frase_generada'])
        mock_gemini.assert_not_called()

    @patch.object(services, '_generar_objeto_y_frase_gemini')
    def test_mismo_objeto_distinto_usuario_no_comparte_eco(self, mock_gemini):
        mock_gemini.return_value = {'objeto': 'lápiz', 'frase': 'El lápiz amarillo escribe bonito.'}

        services.generar_objeto_y_frase(b'fakebytes', 'image/jpeg', 1, usuario_id=1, clase_offline='pencil')
        self.assertEqual(mock_gemini.call_count, 1)

        services.generar_objeto_y_frase(b'fakebytes', 'image/jpeg', 1, usuario_id=2, clase_offline='pencil')
        self.assertEqual(mock_gemini.call_count, 2)

    @patch.object(services, '_generar_objeto_y_frase_gemini')
    def test_sin_clase_offline_nunca_hay_eco(self, mock_gemini):
        mock_gemini.return_value = {'objeto': 'lápiz', 'frase': 'El lápiz amarillo escribe bonito.'}

        services.generar_objeto_y_frase(b'fakebytes', 'image/jpeg', 1, usuario_id=1)
        services.generar_objeto_y_frase(b'fakebytes', 'image/jpeg', 1, usuario_id=1)

        self.assertEqual(mock_gemini.call_count, 2)


# ---------------------------------------------------------------------------
# Tests de "modo económico" (`ConfiguracionCamara`) en `generar_objeto_y_frase`
# ---------------------------------------------------------------------------
class ModoEconomicoGenerarObjetoYFraseTests(TestCase):
    """Tests del modo económico: nunca llama a Gemini, usa diccionario fijo + FraseTemplate/FRASE_SOLO_NOMBRE."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        ConfiguracionCamara.objects.create(pk=1, modo_economico=True)

    @patch.object(services, '_generar_objeto_y_frase_gemini')
    def test_modo_economico_no_llama_a_gemini_y_usa_diccionario(self, mock_gemini):
        resultado = services.generar_objeto_y_frase(
            b'fakebytes', 'image/jpeg', 1, usuario_id=1, clase_offline='pencil',
        )

        mock_gemini.assert_not_called()
        self.assertEqual(resultado['objeto'], 'lápiz')

    @patch.object(services, '_generar_objeto_y_frase_gemini')
    def test_modo_economico_usa_frase_template_guardada_si_existe(self, mock_gemini):
        FraseTemplate.objects.create(
            objeto_keyword='lápiz',
            frase_plantilla='Frase curada del lápiz.',
            nivel_dificultad=1,
            recompensa_monedas=8,
        )
        resultado = services.generar_objeto_y_frase(
            b'fakebytes', 'image/jpeg', 1, usuario_id=1, clase_offline='pencil',
        )

        self.assertEqual(resultado['frase_generada'], 'Frase curada del lápiz.')
        self.assertEqual(resultado['recompensa_monedas'], 8)
        mock_gemini.assert_not_called()

    @patch.object(services, '_generar_objeto_y_frase_gemini')
    def test_modo_economico_sin_frase_template_usa_frase_solo_nombre(self, mock_gemini):
        resultado = services.generar_objeto_y_frase(
            b'fakebytes', 'image/jpeg', 1, usuario_id=1, clase_offline='pencil',
        )

        self.assertIn('lápiz', resultado['frase_generada'])
        self.assertIn('Dilo en voz alta', resultado['frase_generada'])
        self.assertEqual(resultado['recompensa_monedas'], services.RECOMPENSA_MONEDAS_FALLBACK)
        mock_gemini.assert_not_called()

    @patch.object(services, '_generar_objeto_y_frase_gemini')
    def test_modo_economico_sin_clase_offline_devuelve_none(self, mock_gemini):
        resultado = services.generar_objeto_y_frase(b'fakebytes', 'image/jpeg', 1, usuario_id=1)

        self.assertIsNone(resultado)
        mock_gemini.assert_not_called()


# ---------------------------------------------------------------------------
# Tests de auto-guardado de `FraseTemplate` generadas con éxito por Gemini
# ---------------------------------------------------------------------------
class GuardarFraseTemplateAutomaticaTests(TestCase):
    """Tests de `services._guardar_frase_template_automatica`."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_frase_exitosa_se_guarda_como_frase_template_automatica(self):
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
        cache.clear()
        self.addCleanup(cache.clear)

    def test_requiere_login(self):
        self.client.logout()
        response = self.client.post(reverse('camara_capturar'), {})
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_metodo_get_no_permitido(self):
        response = self.client.get(reverse('camara_capturar'))
        self.assertEqual(response.status_code, 405)

    @patch.object(services, '_generar_objeto_y_frase_gemini')
    def test_captura_exitosa_devuelve_frase_generada(self, mock_gemini):
        mock_gemini.return_value = {'objeto': 'lápiz', 'frase': 'El lápiz es largo y amarillo.'}

        response = self.client.post(reverse('camara_capturar'), {
            'imagen': f'data:image/png;base64,{IMAGEN_PNG_VALIDA_BASE64}',
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['objeto'], 'lápiz')
        self.assertEqual(data['frase_generada'], 'El lápiz es largo y amarillo.')
        self.assertIsNone(data['fuente_calificador'])
        self.assertIsNone(data['caja_deteccion'])

    def test_imagen_invalida_no_expone_detalles_internos(self):
        response = self.client.post(reverse('camara_capturar'), {'imagen': 'esto-no-es-base64!!'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'error')
        self.assertNotIn('Traceback', data['message'])
        self.assertNotIn('.py', data['message'])

    @patch.object(services, '_generar_objeto_y_frase_gemini')
    def test_clase_offline_se_envia_al_servicio(self, mock_gemini):
        mock_gemini.return_value = {'objeto': 'botella', 'frase': 'La botella tiene agua fresca.'}

        response = self.client.post(reverse('camara_capturar'), {
            'imagen': f'data:image/png;base64,{IMAGEN_PNG_VALIDA_BASE64}',
            'clase_offline': 'bottle',
        })
        data = response.json()
        self.assertEqual(data['status'], 'success')

        # Segunda captura con la misma clase_offline debe usar el eco (no vuelve a llamar a Gemini).
        mock_gemini.reset_mock()
        response_2 = self.client.post(reverse('camara_capturar'), {
            'imagen': f'data:image/png;base64,{IMAGEN_PNG_VALIDA_BASE64}',
            'clase_offline': 'bottle',
        })
        self.assertEqual(response_2.json()['frase_generada'], data['frase_generada'])
        mock_gemini.assert_not_called()

    @patch.object(services, '_generar_objeto_y_frase_gemini', return_value=None)
    def test_modo_economico_sin_clase_offline_devuelve_error_limpio(self, mock_gemini):
        ConfiguracionCamara.objects.create(pk=1, modo_economico=True)

        response = self.client.post(reverse('camara_capturar'), {
            'imagen': f'data:image/png;base64,{IMAGEN_PNG_VALIDA_BASE64}',
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'error')
        mock_gemini.assert_not_called()


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
