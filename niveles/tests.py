from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .models import MisionVocabulario, Nivel, ProgresoEstudiante
from . import services

UsuarioCustom = get_user_model()


# ---------------------------------------------------------------------------
# Tests de modelos
# ---------------------------------------------------------------------------
class ModelosNivelesTests(TestCase):
    """Tests básicos de creación y representación de los modelos de `niveles`."""

    def test_creacion_y_str_nivel(self):
        nivel = Nivel.objects.create(
            numero=1,
            titulo="Introducción",
            descripcion="Nivel inicial",
            puntos_recompensa=50,
        )
        self.assertEqual(str(nivel), "Nivel 1: Introducción")
        self.assertEqual(nivel.puntos_recompensa, 50)

    def test_mision_vocabulario_relacion_con_nivel(self):
        nivel = Nivel.objects.create(numero=2, titulo="Animales", puntos_recompensa=30)
        mision = MisionVocabulario.objects.create(
            nivel=nivel,
            palabra_objetivo="perro",
            tipo="VOZ",
            frase_historia="El perro corre en el parque.",
        )
        self.assertIn("perro", str(mision))
        self.assertEqual(mision.nivel, nivel)
        self.assertIn(mision, nivel.misiones.all())

    def test_progreso_estudiante_str_y_relacion_usuario(self):
        usuario = UsuarioCustom.objects.create_user(username="ana", password="claveSegura123")
        progreso = ProgresoEstudiante.objects.create(usuario=usuario)
        self.assertEqual(str(progreso), f"Progreso de {usuario}")
        self.assertEqual(progreso.usuario, usuario)
        self.assertIsNone(progreso.nivel_actual)


# ---------------------------------------------------------------------------
# Tests de la vista `niveles_view`
# ---------------------------------------------------------------------------
class NivelesViewTests(TestCase):
    """Verifica autenticación, render y contexto de `niveles_view`."""

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(username="estudiante", password="claveSegura123")
        self.nivel1 = Nivel.objects.create(numero=1, titulo="Inicio", puntos_recompensa=50)
        MisionVocabulario.objects.create(
            nivel=self.nivel1,
            palabra_objetivo="sol",
            tipo="VOZ",
            frase_historia="El sol brilla mucho hoy.",
        )

    def test_redirige_si_no_hay_sesion(self):
        response = self.client.get(reverse('niveles'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login') if False else '/accounts/login/', response.url)

    def test_renderiza_200_con_sesion(self):
        self.client.login(username="estudiante", password="claveSegura123")
        response = self.client.get(reverse('niveles'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'niveles/niveles.html')

    def test_contexto_incluye_niveles_config_con_url(self):
        self.client.login(username="estudiante", password="claveSegura123")
        response = self.client.get(reverse('niveles'))
        self.assertIn('niveles_config', response.context)
        self.assertEqual(
            response.context['niveles_config']['url_guardar_progreso'],
            reverse('guardar_progreso'),
        )


# ---------------------------------------------------------------------------
# Tests de la capa de servicios
# ---------------------------------------------------------------------------
class ServiciosNivelesTests(TestCase):
    """Tests de `procesar_audio_subido` y `calcular_recompensas`."""

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(
            username="servicio_user", password="claveSegura123", monedas=0,
        )
        self.nivel = Nivel.objects.create(numero=1, titulo="Inicio", puntos_recompensa=50)

    def test_procesar_audio_subido_rechaza_archivo_no_wav(self):
        archivo_falso = SimpleUploadedFile(
            "no_es_audio.txt",
            b"esto no es un archivo de audio valido",
            content_type="text/plain",
        )
        with self.assertRaises(ValueError):
            services.procesar_audio_subido(archivo_falso)

    def test_calcular_recompensas_otorga_monedas_si_supera_umbral(self):
        resultado = services.calcular_recompensas(self.usuario, score=85, nivel_id=self.nivel.numero)

        self.usuario.refresh_from_db()
        self.assertEqual(resultado['monedas_ganadas'], self.nivel.puntos_recompensa)
        self.assertEqual(resultado['monedas_totales'], self.nivel.puntos_recompensa)
        self.assertEqual(self.usuario.monedas, self.nivel.puntos_recompensa)
        # El Módulo A no debe modificar racha_dias.
        self.assertEqual(self.usuario.racha_dias, 0)

    def test_calcular_recompensas_no_otorga_monedas_si_no_supera_umbral(self):
        resultado = services.calcular_recompensas(self.usuario, score=40, nivel_id=self.nivel.numero)

        self.usuario.refresh_from_db()
        self.assertEqual(resultado['monedas_ganadas'], 0)
        self.assertEqual(resultado['monedas_totales'], 0)
        self.assertEqual(self.usuario.monedas, 0)
        self.assertEqual(self.usuario.racha_dias, 0)


# ---------------------------------------------------------------------------
# Tests de la vista `guardar_progreso`
# ---------------------------------------------------------------------------
class GuardarProgresoViewTests(TestCase):
    """Verifica que `guardar_progreso` no exponga errores internos al cliente."""

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(username="grabador", password="claveSegura123")
        self.client.login(username="grabador", password="claveSegura123")
        self.nivel = Nivel.objects.create(numero=1, titulo="Inicio", puntos_recompensa=50)

    def test_requiere_login(self):
        self.client.logout()
        response = self.client.post(reverse('guardar_progreso'), {})
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_post_sin_audio_ni_palabra_objetivo_devuelve_redirect_caso_b(self):
        # Sin archivo de audio -> CASO B (registrar avance), redirige al mapa
        # sin exponer ningún detalle interno.
        response = self.client.post(reverse('guardar_progreso'), {
            'nivel_id': self.nivel.numero,
            'score_obtenido': '10',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('niveles'))

    def test_post_con_audio_invalido_no_expone_str_excepcion(self):
        archivo_falso = SimpleUploadedFile(
            "no_es_audio.txt",
            b"contenido invalido",
            content_type="text/plain",
        )
        response = self.client.post(reverse('guardar_progreso'), {
            'audio': archivo_falso,
            'palabra_objetivo': 'sol',
            'nivel_id': self.nivel.numero,
        })

        self.assertEqual(response.status_code, 500)
        data = response.json()
        self.assertEqual(data['status'], 'error')

        mensaje = data['message']
        # El mensaje debe ser genérico: nunca debe filtrar rutas de archivo,
        # tracebacks ni texto interno de la excepción original.
        self.assertNotIn('Traceback', mensaje)
        self.assertNotIn('.py', mensaje)
        self.assertNotIn('/tmp', mensaje)
        self.assertNotIn('ValueError', mensaje)

    @patch.object(services, 'evaluar_pronunciacion_azure')
    def test_post_con_error_en_azure_no_expone_detalles_internos(self, mock_evaluar):
        mock_evaluar.return_value = {
            'status': 'error',
            'message': 'No se pudo reconocer audio.',
        }

        # Generamos un WAV mínimo válido (cabecera RIFF/WAVE) para pasar la
        # validación de python-magic en `procesar_audio_subido`.
        wav_header = (
            b'RIFF' + (36).to_bytes(4, 'little') + b'WAVEfmt '
            + (16).to_bytes(4, 'little')
            + (1).to_bytes(2, 'little') + (1).to_bytes(2, 'little')
            + (16000).to_bytes(4, 'little') + (32000).to_bytes(4, 'little')
            + (2).to_bytes(2, 'little') + (16).to_bytes(2, 'little')
            + b'data' + (0).to_bytes(4, 'little')
        )
        archivo_audio = SimpleUploadedFile("audio.wav", wav_header, content_type="audio/wav")

        response = self.client.post(reverse('guardar_progreso'), {
            'audio': archivo_audio,
            'palabra_objetivo': 'sol',
            'nivel_id': self.nivel.numero,
        })

        data = response.json()
        self.assertEqual(data['status'], 'error')
        self.assertEqual(data['message'], 'No se pudo reconocer audio.')
