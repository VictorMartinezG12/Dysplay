import datetime
import json
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import services
from .models import FragmentoHistoria, Historia, HistoriaGenerada, ProgresoHistoria

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


# ---------------------------------------------------------------------------
# Tests de `crear_historia_desde_ia` (generación completa vía Azure OpenAI)
# ---------------------------------------------------------------------------
def _construir_respuesta_azure_mock(contenido_json):
    """Construye un mock de la respuesta de `cliente.chat.completions.create` con el JSON dado."""
    mensaje_mock = MagicMock()
    mensaje_mock.content = json.dumps(contenido_json)
    opcion_mock = MagicMock()
    opcion_mock.message = mensaje_mock
    respuesta_mock = MagicMock()
    respuesta_mock.choices = [opcion_mock]
    return respuesta_mock


class CrearHistoriaDesdeIATests(TestCase):
    """Tests de `services.crear_historia_desde_ia`, sin llamadas reales a Azure OpenAI."""

    fixtures = ['historias_inicial']

    def setUp(self):
        self.estructura_valida = {
            'titulo': 'El bosque encantado',
            'fragmentos': [
                {
                    'texto_narracion': 'Había una vez un bosque mágico.',
                    'tipo_respuesta': 'elegir',
                    'pregunta_interactiva': '¿Qué hace el protagonista?',
                    'opciones': [
                        {'texto': 'Explora el bosque', 'es_correcta': True},
                        {'texto': 'Se va a casa', 'es_correcta': False},
                    ],
                },
                {
                    'texto_narracion': 'El bosque tenía muchos árboles altos.',
                    'tipo_respuesta': '',
                    'pregunta_interactiva': '',
                    'opciones': [],
                },
            ],
        }

    @patch('historias.services.AzureOpenAI')
    def test_generacion_exitosa_crea_historia_fragmentos_y_opciones(self, mock_azure_cls):
        mock_cliente = MagicMock()
        mock_cliente.chat.completions.create.return_value = _construir_respuesta_azure_mock(self.estructura_valida)
        mock_azure_cls.return_value = mock_cliente

        orden_maximo_previo = Historia.objects.order_by('-orden').first().orden

        resultado = services.crear_historia_desde_ia(tema='un bosque encantado', nivel_dificultad=2)

        self.assertEqual(resultado['status'], 'success')
        historia = Historia.objects.get(pk=resultado['historia_id'])
        self.assertEqual(historia.titulo, 'El bosque encantado')
        self.assertEqual(historia.orden, orden_maximo_previo + 1)
        self.assertEqual(historia.nivel_dificultad, 'facil')

        fragmentos = list(historia.fragmentos.order_by('orden'))
        self.assertEqual(len(fragmentos), 2)
        self.assertEqual(fragmentos[0].tipo_respuesta, 'elegir')
        self.assertEqual(fragmentos[0].opciones.count(), 2)
        self.assertTrue(fragmentos[0].opciones.filter(es_correcta=True).exists())
        self.assertEqual(fragmentos[1].tipo_respuesta, '')

    @patch('historias.services.AzureOpenAI')
    def test_fallo_de_api_no_crea_ninguna_historia(self, mock_azure_cls):
        mock_cliente = MagicMock()
        mock_cliente.chat.completions.create.side_effect = TimeoutError('tiempo agotado')
        mock_azure_cls.return_value = mock_cliente

        cantidad_previa = Historia.objects.count()

        resultado = services.crear_historia_desde_ia(tema='un dragón', nivel_dificultad=3)

        self.assertEqual(resultado['status'], 'error')
        self.assertEqual(Historia.objects.count(), cantidad_previa)

    @patch('historias.services.AzureOpenAI')
    def test_json_malformado_no_crashea_y_retorna_error(self, mock_azure_cls):
        mensaje_mock = MagicMock()
        mensaje_mock.content = 'esto no es json valido {{{'
        opcion_mock = MagicMock()
        opcion_mock.message = mensaje_mock
        respuesta_mock = MagicMock()
        respuesta_mock.choices = [opcion_mock]

        mock_cliente = MagicMock()
        mock_cliente.chat.completions.create.return_value = respuesta_mock
        mock_azure_cls.return_value = mock_cliente

        cantidad_previa = Historia.objects.count()

        resultado = services.crear_historia_desde_ia(tema='un gato', nivel_dificultad=1)

        self.assertEqual(resultado['status'], 'error')
        self.assertEqual(Historia.objects.count(), cantidad_previa)

    @patch('historias.services.AzureOpenAI')
    def test_estructura_inesperada_sin_fragmentos_retorna_error(self, mock_azure_cls):
        mock_cliente = MagicMock()
        mock_cliente.chat.completions.create.return_value = _construir_respuesta_azure_mock({'titulo': 'Sin fragmentos'})
        mock_azure_cls.return_value = mock_cliente

        cantidad_previa = Historia.objects.count()

        resultado = services.crear_historia_desde_ia(tema='algo raro', nivel_dificultad=4)

        self.assertEqual(resultado['status'], 'error')
        self.assertEqual(Historia.objects.count(), cantidad_previa)


# ---------------------------------------------------------------------------
# Tests de `crear_historia_generada_desde_ia` (Módulo F: historias del niño)
# ---------------------------------------------------------------------------
class CrearHistoriaGeneradaDesdeIATests(TestCase):
    """Tests de `services.crear_historia_generada_desde_ia`, sin llamadas reales a Azure OpenAI."""

    fixtures = ['historias_inicial']

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(username='nino_ia', password='claveSegura123')
        self.estructura_valida = {
            'titulo': 'El gato y el perro',
            'fragmentos': [
                {
                    'texto_narracion': 'Un gato y un perro eran amigos.',
                    'tipo_respuesta': 'elegir',
                    'pregunta_interactiva': '¿Quiénes eran amigos?',
                    'opciones': [
                        {'texto': 'El gato y el perro', 'es_correcta': True},
                        {'texto': 'El pez y el pájaro', 'es_correcta': False},
                    ],
                },
                {
                    'texto_narracion': 'Jugaron juntos todo el día.',
                    'tipo_respuesta': '',
                    'pregunta_interactiva': '',
                    'opciones': [],
                },
            ],
        }

    @patch('historias.services.AzureOpenAI')
    def test_generacion_exitosa_crea_historia_generada_con_fragmentos_y_opciones(self, mock_azure_cls):
        mock_cliente = MagicMock()
        mock_cliente.chat.completions.create.return_value = _construir_respuesta_azure_mock(self.estructura_valida)
        mock_azure_cls.return_value = mock_cliente

        resultado = services.crear_historia_generada_desde_ia(self.usuario, 'gato, perro')

        self.assertEqual(resultado['status'], 'success')
        historia_generada = HistoriaGenerada.objects.get(pk=resultado['historia_generada_id'])
        self.assertEqual(historia_generada.usuario, self.usuario)
        self.assertEqual(historia_generada.palabras_clave, 'gato, perro')

        fragmentos = list(historia_generada.fragmentos.order_by('orden'))
        self.assertEqual(len(fragmentos), 2)
        self.assertEqual(fragmentos[0].tipo_respuesta, 'elegir')
        self.assertEqual(fragmentos[0].opciones.count(), 2)

    def test_rechaza_palabras_clave_con_caracteres_no_permitidos(self):
        resultado = services.crear_historia_generada_desde_ia(self.usuario, 'gato`; DROP TABLE {}')

        self.assertEqual(resultado['status'], 'error')
        self.assertEqual(HistoriaGenerada.objects.filter(usuario=self.usuario).count(), 0)

    def test_rechaza_palabras_clave_demasiado_largas(self):
        resultado = services.crear_historia_generada_desde_ia(self.usuario, 'gato ' * 30)

        self.assertEqual(resultado['status'], 'error')
        self.assertEqual(HistoriaGenerada.objects.filter(usuario=self.usuario).count(), 0)

    @patch('historias.services.AzureOpenAI')
    def test_rechaza_la_sexta_historia_generada_en_24_horas(self, mock_azure_cls):
        mock_cliente = MagicMock()
        mock_cliente.chat.completions.create.return_value = _construir_respuesta_azure_mock(self.estructura_valida)
        mock_azure_cls.return_value = mock_cliente

        for _ in range(services.LIMITE_HISTORIAS_GENERADAS_POR_USUARIO_24H):
            resultado = services.crear_historia_generada_desde_ia(self.usuario, 'gato, perro')
            self.assertEqual(resultado['status'], 'success')

        resultado_extra = services.crear_historia_generada_desde_ia(self.usuario, 'gato, perro')

        self.assertEqual(resultado_extra['status'], 'error')
        self.assertEqual(
            HistoriaGenerada.objects.filter(usuario=self.usuario).count(),
            services.LIMITE_HISTORIAS_GENERADAS_POR_USUARIO_24H,
        )

    @patch('historias.services.AzureOpenAI')
    def test_rechaza_por_tope_global_diario(self, mock_azure_cls):
        mock_cliente = MagicMock()
        mock_cliente.chat.completions.create.return_value = _construir_respuesta_azure_mock(self.estructura_valida)
        mock_azure_cls.return_value = mock_cliente

        otro_usuario = UsuarioCustom.objects.create_user(username='otro_nino', password='claveSegura123')
        for indice in range(services.TOPE_GLOBAL_HISTORIAS_GENERADAS_24H):
            HistoriaGenerada.objects.create(usuario=otro_usuario, palabras_clave=f'tema {indice}')

        resultado = services.crear_historia_generada_desde_ia(self.usuario, 'gato, perro')

        self.assertEqual(resultado['status'], 'error')
        mock_cliente.chat.completions.create.assert_not_called()


# ---------------------------------------------------------------------------
# Tests de lectura/evaluación de `HistoriaGenerada` (sin recompensas)
# ---------------------------------------------------------------------------
class HistoriaGeneradaLecturaYEvaluacionTests(TestCase):
    """Verifica el acceso (propietario/expiración) y que nunca se otorgan recompensas."""

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(
            username='nino_lectura', password='claveSegura123', monedas=0,
        )
        self.otro_usuario = UsuarioCustom.objects.create_user(username='otro_lectura', password='claveSegura123')

        self.historia_generada = HistoriaGenerada.objects.create(
            usuario=self.usuario, palabras_clave='sol, luna', fragmento_actual=1,
        )
        self.fragmento_1 = services.FragmentoGenerado.objects.create(
            historia_generada=self.historia_generada,
            orden=1,
            texto_narracion='Había un sol y una luna.',
            tipo_respuesta='elegir',
            pregunta_interactiva='¿Qué brilla de día?',
        )
        self.opcion_correcta = services.OpcionGenerada.objects.create(
            fragmento=self.fragmento_1, texto='El sol', es_correcta=True,
        )
        services.OpcionGenerada.objects.create(
            fragmento=self.fragmento_1, texto='La luna', es_correcta=False,
        )
        self.fragmento_2 = services.FragmentoGenerado.objects.create(
            historia_generada=self.historia_generada,
            orden=2,
            texto_narracion='Fin de la historia.',
            tipo_respuesta='',
        )

    def test_no_se_puede_acceder_a_historia_generada_de_otro_usuario(self):
        resultado = services.obtener_historia_generada_vigente(self.otro_usuario, self.historia_generada.id)
        self.assertIsNone(resultado)

    def test_no_se_puede_acceder_a_historia_generada_expirada(self):
        self.historia_generada.fecha_expiracion = timezone.now() - datetime.timedelta(hours=1)
        self.historia_generada.save()

        resultado = services.obtener_historia_generada_vigente(self.usuario, self.historia_generada.id)
        self.assertIsNone(resultado)

    def test_completar_historia_generada_no_otorga_monedas_ni_insignias(self):
        resultado_1 = services.procesar_respuesta_fragmento_generado(
            self.usuario, self.historia_generada, fragmento_id=self.fragmento_1.id, opcion_id=self.opcion_correcta.id,
        )
        self.assertEqual(resultado_1['status'], 'success')
        self.assertFalse(resultado_1['completada_ahora'])
        self.assertNotIn('monedas_ganadas', resultado_1)
        self.assertNotIn('insignia_nueva', resultado_1)

        resultado_2 = services.procesar_respuesta_fragmento_generado(
            self.usuario, self.historia_generada, fragmento_id=self.fragmento_2.id,
        )

        self.assertEqual(resultado_2['status'], 'success')
        self.assertTrue(resultado_2['completada_ahora'])
        self.assertNotIn('monedas_ganadas', resultado_2)
        self.assertNotIn('insignia_nueva', resultado_2)

        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.monedas, 0)

        self.historia_generada.refresh_from_db()
        self.assertTrue(self.historia_generada.completada)


# ---------------------------------------------------------------------------
# Tests de las vistas de historias generadas
# ---------------------------------------------------------------------------
class HistoriaGeneradaViewsTests(TestCase):
    """Verifica autenticación y contrato JSON de los endpoints de historias generadas."""

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(username='nino_vistas', password='claveSegura123')
        self.client.login(username='nino_vistas', password='claveSegura123')

    @patch('historias.services.AzureOpenAI')
    def test_generar_mia_devuelve_id_de_historia_generada(self, mock_azure_cls):
        estructura_valida = {
            'titulo': 'Historia corta',
            'fragmentos': [
                {'texto_narracion': 'Narración.', 'tipo_respuesta': '', 'pregunta_interactiva': '', 'opciones': []},
            ],
        }
        mock_cliente = MagicMock()
        mock_cliente.chat.completions.create.return_value = _construir_respuesta_azure_mock(estructura_valida)
        mock_azure_cls.return_value = mock_cliente

        response = self.client.post(reverse('historias_generar_mia'), {'palabras_clave': 'sol, luna'})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'success')
        self.assertIn('historia_generada_id', data)

    def test_generar_mia_rechaza_palabras_clave_invalidas_sin_llamar_ia(self):
        response = self.client.post(reverse('historias_generar_mia'), {'palabras_clave': '<script>'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'error')
        self.assertEqual(HistoriaGenerada.objects.filter(usuario=self.usuario).count(), 0)

    def test_generar_mia_requiere_login(self):
        self.client.logout()
        response = self.client.post(reverse('historias_generar_mia'), {'palabras_clave': 'sol, luna'})
        self.assertEqual(response.status_code, 302)

    def test_listar_historias_generadas_devuelve_solo_las_vigentes(self):
        HistoriaGenerada.objects.create(usuario=self.usuario, palabras_clave='vigente')
        expirada = HistoriaGenerada.objects.create(usuario=self.usuario, palabras_clave='expirada')
        expirada.fecha_expiracion = timezone.now() - datetime.timedelta(hours=1)
        expirada.save()

        response = self.client.get(reverse('historias_generadas_listar'))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        palabras = [h['palabras_clave'] for h in data['historias']]
        self.assertIn('vigente', palabras)
        self.assertNotIn('expirada', palabras)


# ---------------------------------------------------------------------------
# Test del comando de limpieza
# ---------------------------------------------------------------------------
class LimpiarHistoriasGeneradasCommandTests(TestCase):
    """Verifica que el comando borre solo las historias generadas expiradas (con cascada)."""

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(username='nino_cleanup', password='claveSegura123')

    def test_borra_expiradas_y_conserva_vigentes(self):
        vigente = HistoriaGenerada.objects.create(usuario=self.usuario, palabras_clave='vigente')
        expirada = HistoriaGenerada.objects.create(usuario=self.usuario, palabras_clave='expirada')
        expirada.fecha_expiracion = timezone.now() - datetime.timedelta(hours=1)
        expirada.save()

        fragmento_expirado = services.FragmentoGenerado.objects.create(
            historia_generada=expirada, orden=1, texto_narracion='Texto.',
        )
        services.OpcionGenerada.objects.create(fragmento=fragmento_expirado, texto='Opción', es_correcta=True)

        call_command('limpiar_historias_generadas')

        self.assertFalse(HistoriaGenerada.objects.filter(pk=expirada.id).exists())
        self.assertTrue(HistoriaGenerada.objects.filter(pk=vigente.id).exists())
        self.assertFalse(services.FragmentoGenerado.objects.filter(pk=fragmento_expirado.id).exists())
