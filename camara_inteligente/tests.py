from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from niveles.models import Nivel, ProgresoEstudiante

from . import services
from .models import FraseTemplate

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
# Tests de `generar_frase_objeto`
# ---------------------------------------------------------------------------
class GenerarFraseObjetoTests(TestCase):
    """Tests de `services.generar_frase_objeto`."""

    def setUp(self):
        # Se desactiva el LLM en estos tests (parchando `generar_frase_llm` para
        # que siempre devuelva `None`) para ejercitar el flujo de respaldo con
        # `FraseTemplate`/`FRASE_GENERICA`, que es lo que verifican estos tests.
        parche_llm = patch.object(services, 'generar_frase_llm', return_value=None)
        parche_llm.start()
        self.addCleanup(parche_llm.stop)

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

    def test_sin_etiquetas_devuelve_none(self):
        self.assertIsNone(services.generar_frase_objeto([], 1))

    def test_filtra_por_nivel_del_usuario(self):
        etiquetas = [{'description': 'pencil', 'score': 0.9}]
        resultado = services.generar_frase_objeto(etiquetas, nivel_usuario=1)
        self.assertEqual(resultado['objeto'], 'lápiz')
        self.assertEqual(resultado['frase_generada'], self.frase_facil.frase_plantilla)

    def test_sin_frase_en_su_nivel_usa_cualquier_nivel_del_objeto(self):
        self.frase_facil.delete()
        etiquetas = [{'description': 'pencil', 'score': 0.9}]
        resultado = services.generar_frase_objeto(etiquetas, nivel_usuario=1)
        self.assertEqual(resultado['frase_generada'], self.frase_dificil.frase_plantilla)

    def test_etiqueta_sin_traduccion_devuelve_frase_generica(self):
        etiquetas = [{'description': 'unknown_object_xyz', 'score': 0.8}]
        resultado = services.generar_frase_objeto(etiquetas, nivel_usuario=1)
        self.assertEqual(resultado['objeto'], 'unknown_object_xyz')
        self.assertIn('unknown_object_xyz', resultado['frase_generada'])
        self.assertEqual(resultado['recompensa_monedas'], services.RECOMPENSA_MONEDAS_FALLBACK)


# ---------------------------------------------------------------------------
# Tests de `generar_frase_llm` (Azure OpenAI) y su cacheo
# ---------------------------------------------------------------------------
class GenerarFraseLlmTests(TestCase):
    """Tests de `services.generar_frase_llm`, mockeando `AzureOpenAI` (sin red real)."""

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
    def test_exito_genera_y_cachea_la_frase(self, mock_clase_cliente):
        mock_cliente = MagicMock()
        mock_cliente.chat.completions.create.return_value = self._mock_respuesta_llm(
            'El lápiz amarillo escribe en el cuaderno.'
        )
        mock_clase_cliente.return_value = mock_cliente

        resultado = services.generar_frase_llm('lápiz', 1)

        self.assertEqual(resultado, 'El lápiz amarillo escribe en el cuaderno.')
        self.assertEqual(mock_cliente.chat.completions.create.call_count, 1)
        self.assertEqual(cache.get('frase_llm_camara_lápiz_1'), resultado)

    @patch.object(services, 'AzureOpenAI')
    def test_fallo_de_api_devuelve_none_y_cae_a_frasetemplate(self, mock_clase_cliente):
        mock_clase_cliente.side_effect = TimeoutError('la API no respondió a tiempo')

        resultado_llm = services.generar_frase_llm('lápiz', 1)
        self.assertIsNone(resultado_llm)

        FraseTemplate.objects.create(
            objeto_keyword='lápiz',
            frase_plantilla='El lápiz es largo y amarillo.',
            nivel_dificultad=1,
            recompensa_monedas=5,
        )
        etiquetas = [{'description': 'pencil', 'score': 0.9}]
        resultado = services.generar_frase_objeto(etiquetas, nivel_usuario=1)
        self.assertEqual(resultado['frase_generada'], 'El lápiz es largo y amarillo.')
        self.assertEqual(resultado['recompensa_monedas'], 5)

    @patch.object(services, 'AzureOpenAI')
    def test_segunda_llamada_usa_cache_y_no_invoca_de_nuevo_al_llm(self, mock_clase_cliente):
        mock_cliente = MagicMock()
        mock_cliente.chat.completions.create.return_value = self._mock_respuesta_llm(
            'El gato duerme en la silla.'
        )
        mock_clase_cliente.return_value = mock_cliente

        primera = services.generar_frase_llm('gato', 2)
        segunda = services.generar_frase_llm('gato', 2)

        self.assertEqual(primera, segunda)
        self.assertEqual(mock_cliente.chat.completions.create.call_count, 1)


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

    @patch.object(services, 'generar_frase_llm', return_value=None)
    @patch.object(services, 'analizar_imagen_google_vision')
    def test_captura_exitosa_devuelve_frase_generada(self, mock_vision, mock_llm):
        mock_vision.return_value = {
            'status': 'success',
            'etiquetas': [{'description': 'pencil', 'score': 0.95}],
        }
        response = self.client.post(reverse('camara_capturar'), {
            'imagen': f'data:image/png;base64,{IMAGEN_PNG_VALIDA_BASE64}',
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['objeto'], 'lápiz')
        self.assertEqual(data['frase_generada'], 'El lápiz es largo y amarillo.')

    def test_imagen_invalida_no_expone_detalles_internos(self):
        response = self.client.post(reverse('camara_capturar'), {'imagen': 'esto-no-es-base64!!'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'error')
        self.assertNotIn('Traceback', data['message'])
        self.assertNotIn('.py', data['message'])


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
