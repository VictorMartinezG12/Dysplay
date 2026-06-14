from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from . import services
from .models import FragmentoHistoria, Historia, ProgresoHistoria

UsuarioCustom = get_user_model()


# ---------------------------------------------------------------------------
# Tests de modelos
# ---------------------------------------------------------------------------
class ModelosHistoriasTests(TestCase):
    """Tests básicos de los modelos del módulo `historias`."""

    fixtures = ['historias_inicial']

    def test_historia_str_es_su_titulo(self):
        historia = Historia.objects.get(pk=1)
        self.assertEqual(str(historia), 'El dragón perdido')

    def test_fragmento_unique_together_historia_y_orden(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                FragmentoHistoria.objects.create(historia_id=1, orden=1, texto_narracion='Duplicado')

    def test_progreso_unique_together_usuario_y_historia(self):
        usuario = UsuarioCustom.objects.create_user(username='ana_modelos', password='claveSegura123')
        historia = Historia.objects.get(pk=1)
        ProgresoHistoria.objects.create(usuario=usuario, historia=historia)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ProgresoHistoria.objects.create(usuario=usuario, historia=historia)


# ---------------------------------------------------------------------------
# Tests de `obtener_historias_disponibles` (desbloqueo secuencial)
# ---------------------------------------------------------------------------
class ObtenerHistoriasDisponiblesTests(TestCase):
    """Tests de `services.obtener_historias_disponibles`."""

    fixtures = ['historias_inicial']

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(username='ana_carrusel', password='claveSegura123')

    def test_solo_la_primera_historia_esta_disponible_al_inicio(self):
        historias = services.obtener_historias_disponibles(self.usuario)
        estados = {h['id']: h['estado'] for h in historias}

        self.assertEqual(estados[1], 'disponible')
        self.assertEqual(estados[2], 'bloqueada')
        self.assertEqual(estados[3], 'bloqueada')

    def test_completar_una_historia_desbloquea_la_siguiente(self):
        ProgresoHistoria.objects.create(usuario=self.usuario, historia_id=1, completada=True)

        historias = services.obtener_historias_disponibles(self.usuario)
        estados = {h['id']: h['estado'] for h in historias}

        self.assertEqual(estados[1], 'completada')
        self.assertEqual(estados[2], 'disponible')
        self.assertEqual(estados[3], 'bloqueada')


# ---------------------------------------------------------------------------
# Tests de `procesar_respuesta_fragmento` con ramificación (tipo='elegir')
# ---------------------------------------------------------------------------
class ProcesarRespuestaElegirTests(TestCase):
    """Tests de la ramificación narrativa de la historia 1 (tipo='elegir')."""

    fixtures = ['historias_inicial']

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(username='ana_elegir', password='claveSegura123', monedas=0)
        self.historia1 = Historia.objects.get(pk=1)

    def test_opcion_correcta_lleva_al_fragmento_de_su_rama(self):
        resultado = services.procesar_respuesta_fragmento(self.usuario, self.historia1, fragmento_id=1, opcion_id=1)

        self.assertEqual(resultado['status'], 'success')
        self.assertTrue(resultado['correcta'])
        self.assertEqual(resultado['siguiente_fragmento']['id'], 2)
        self.assertFalse(resultado['completada_ahora'])

    def test_opcion_incorrecta_lleva_a_la_rama_alternativa(self):
        resultado = services.procesar_respuesta_fragmento(self.usuario, self.historia1, fragmento_id=1, opcion_id=2)

        self.assertEqual(resultado['status'], 'success')
        self.assertFalse(resultado['correcta'])
        self.assertEqual(resultado['siguiente_fragmento']['id'], 3)

    def test_completar_historia_otorga_monedas_y_marca_progreso(self):
        services.procesar_respuesta_fragmento(self.usuario, self.historia1, fragmento_id=1, opcion_id=1)
        resultado = services.procesar_respuesta_fragmento(self.usuario, self.historia1, fragmento_id=2)

        self.assertTrue(resultado['completada_ahora'])
        self.assertEqual(resultado['monedas_ganadas'], self.historia1.recompensa_monedas)

        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.monedas, self.historia1.recompensa_monedas)

        progreso = ProgresoHistoria.objects.get(usuario=self.usuario, historia=self.historia1)
        self.assertTrue(progreso.completada)
        self.assertIsNotNone(progreso.fecha_fin)


# ---------------------------------------------------------------------------
# Tests de `procesar_respuesta_fragmento` con texto (tipo='escribir')
# ---------------------------------------------------------------------------
class ProcesarRespuestaEscribirTests(TestCase):
    """Tests de la evaluación normalizada de respuestas escritas (historia 2)."""

    fixtures = ['historias_inicial']

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(username='ana_escribir', password='claveSegura123')
        self.historia2 = Historia.objects.get(pk=2)
        ProgresoHistoria.objects.create(usuario=self.usuario, historia=self.historia2, fragmento_actual_id=4)

    def test_respuesta_con_tildes_y_mayusculas_se_considera_correcta(self):
        resultado = services.procesar_respuesta_fragmento(
            self.usuario, self.historia2, fragmento_id=4, texto_respuesta='LÚNA',
        )

        self.assertEqual(resultado['status'], 'success')
        self.assertTrue(resultado['correcta'])
        self.assertEqual(resultado['siguiente_fragmento']['id'], 5)

    def test_respuesta_vacia_devuelve_error(self):
        resultado = services.procesar_respuesta_fragmento(
            self.usuario, self.historia2, fragmento_id=4, texto_respuesta='   ',
        )
        self.assertEqual(resultado['status'], 'error')

    def test_respuesta_incorrecta_continua_la_historia(self):
        resultado = services.procesar_respuesta_fragmento(
            self.usuario, self.historia2, fragmento_id=4, texto_respuesta='marte',
        )

        self.assertEqual(resultado['status'], 'success')
        self.assertFalse(resultado['correcta'])
        self.assertEqual(resultado['siguiente_fragmento']['id'], 5)


# ---------------------------------------------------------------------------
# Tests de `procesar_respuesta_fragmento` con voz (tipo='pronunciar')
# ---------------------------------------------------------------------------
class ProcesarRespuestaPronunciarTests(TestCase):
    """Tests de la evaluación de pronunciación (historia 3), mockeando Azure Speech."""

    fixtures = ['historias_inicial']

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(username='ana_pronunciar', password='claveSegura123')
        self.historia3 = Historia.objects.get(pk=3)
        ProgresoHistoria.objects.create(usuario=self.usuario, historia=self.historia3, fragmento_actual_id=6)
        self.audio = SimpleUploadedFile('audio.wav', b'contenido', content_type='audio/wav')

    @patch.object(services, 'procesar_audio_subido')
    @patch.object(services, 'evaluar_pronunciacion_azure')
    def test_pronunciacion_correcta_marca_correcta_y_avanza(self, mock_evaluar, mock_procesar):
        mock_procesar.return_value = '/tmp/audio_falso.wav'
        mock_evaluar.return_value = {'status': 'success', 'score_global': 90, 'palabras': []}

        resultado = services.procesar_respuesta_fragmento(
            self.usuario, self.historia3, fragmento_id=6, archivo_audio=self.audio,
        )

        self.assertEqual(resultado['status'], 'success')
        self.assertTrue(resultado['correcta'])
        self.assertEqual(resultado['siguiente_fragmento']['id'], 7)

    @patch.object(services, 'procesar_audio_subido')
    @patch.object(services, 'evaluar_pronunciacion_azure')
    def test_pronunciacion_insuficiente_marca_incorrecta(self, mock_evaluar, mock_procesar):
        mock_procesar.return_value = '/tmp/audio_falso.wav'
        mock_evaluar.return_value = {'status': 'success', 'score_global': 40, 'palabras': []}

        resultado = services.procesar_respuesta_fragmento(
            self.usuario, self.historia3, fragmento_id=6, archivo_audio=self.audio,
        )

        self.assertEqual(resultado['status'], 'success')
        self.assertFalse(resultado['correcta'])


# ---------------------------------------------------------------------------
# Tests de la vista `historias_view`
# ---------------------------------------------------------------------------
class HistoriasViewTests(TestCase):
    """Verifica autenticación, render y contexto de `historias_view`."""

    fixtures = ['historias_inicial']

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(username='ana_vista', password='claveSegura123')

    def test_redirige_si_no_hay_sesion(self):
        response = self.client.get(reverse('historias'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_renderiza_carrusel_sin_lectura(self):
        self.client.login(username='ana_vista', password='claveSegura123')
        response = self.client.get(reverse('historias'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'historias/historias.html')
        self.assertIsNone(response.context['lectura'])

    def test_abre_la_lectura_de_una_historia_disponible(self):
        self.client.login(username='ana_vista', password='claveSegura123')
        response = self.client.get(reverse('historias'), {'historia': 1})

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.context['lectura'])
        self.assertEqual(response.context['lectura']['historia']['id'], 1)

    def test_no_permite_abrir_una_historia_bloqueada(self):
        self.client.login(username='ana_vista', password='claveSegura123')
        response = self.client.get(reverse('historias'), {'historia': 3})

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['lectura'])


# ---------------------------------------------------------------------------
# Tests de la vista `evaluar_fragmento`
# ---------------------------------------------------------------------------
class EvaluarFragmentoViewTests(TestCase):
    """Verifica autenticación, métodos permitidos y respuestas de `evaluar_fragmento`."""

    fixtures = ['historias_inicial']

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(username='ana_evaluar', password='claveSegura123')
        self.client.login(username='ana_evaluar', password='claveSegura123')

    def test_requiere_login(self):
        self.client.logout()
        response = self.client.post(reverse('historias_evaluar', args=[1]), {})
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_metodo_get_no_permitido(self):
        response = self.client.get(reverse('historias_evaluar', args=[1]))
        self.assertEqual(response.status_code, 405)

    def test_falta_fragmento_id_devuelve_error_sin_excepcion(self):
        response = self.client.post(reverse('historias_evaluar', args=[1]), {})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'error')

    def test_responder_opcion_correcta_devuelve_siguiente_fragmento(self):
        response = self.client.post(reverse('historias_evaluar', args=[1]), {
            'fragmento_id': 1,
            'opcion_id': 1,
        })

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'success')
        self.assertTrue(data['correcta'])
        self.assertEqual(data['siguiente_fragmento']['id'], 2)
