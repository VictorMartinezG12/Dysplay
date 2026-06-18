from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from niveles.models import MisionVocabulario, Nivel, ProgresoEstudiante
from recompensas.models import Coleccionable
from . import services
from .models import ConfiguracionDesafio, DesafioDiario, ProgresoDesafio

UsuarioCustom = get_user_model()


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
class ModelosDesafioTests(TestCase):
    """Tests básicos de los modelos del módulo `desafio`."""

    def test_configuracion_desafio_es_singleton(self):
        configuracion1 = ConfiguracionDesafio.obtener_configuracion()

        configuracion2 = ConfiguracionDesafio(zona_activa=Nivel.ZONA_MONTANA)
        configuracion2.save()

        self.assertEqual(configuracion1.pk, 1)
        self.assertEqual(configuracion2.pk, 1)
        self.assertEqual(ConfiguracionDesafio.objects.count(), 1)

    def test_desafio_diario_str_incluye_fecha(self):
        desafio = DesafioDiario.objects.create(fecha=timezone.localdate())
        self.assertIn(str(desafio.fecha), str(desafio))

    def test_progreso_desafio_unique_together_por_usuario_y_desafio(self):
        usuario = UsuarioCustom.objects.create_user(username="ana_desafio", password="claveSegura123")
        desafio = DesafioDiario.objects.create(fecha=timezone.localdate())
        ProgresoDesafio.objects.create(usuario=usuario, desafio=desafio)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ProgresoDesafio.objects.create(usuario=usuario, desafio=desafio)


# ---------------------------------------------------------------------------
# Tests de la vista `desafio_view`
# ---------------------------------------------------------------------------
class DesafioViewTests(TestCase):
    """Verifica autenticación, render y contexto de `desafio_view`."""

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(username="estudiante_e", password="claveSegura123")
        self.nivel = Nivel.objects.create(numero=1, titulo="Inicio", puntos_recompensa=50)
        MisionVocabulario.objects.create(
            nivel=self.nivel,
            palabra_objetivo="sol",
            tipo="VOZ",
            frase_historia="El sol brilla mucho hoy.",
        )

    def test_redirige_si_no_hay_sesion(self):
        response = self.client.get(reverse('desafio'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_renderiza_200_con_sesion(self):
        self.client.login(username="estudiante_e", password="claveSegura123")
        response = self.client.get(reverse('desafio'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'desafio/desafio.html')

    def test_contexto_incluye_desafio_config_con_url_evaluar(self):
        self.client.login(username="estudiante_e", password="claveSegura123")
        response = self.client.get(reverse('desafio'))
        self.assertEqual(
            response.context['desafio_config']['url_evaluar'],
            reverse('desafio_evaluar'),
        )


# ---------------------------------------------------------------------------
# Tests de `obtener_o_crear_desafio_de_hoy`
# ---------------------------------------------------------------------------
class ObtenerOCrearDesafioDeHoyTests(TestCase):
    """Tests de `services.obtener_o_crear_desafio_de_hoy`."""

    def setUp(self):
        self.nivel = Nivel.objects.create(numero=1, titulo="Inicio", puntos_recompensa=50)
        for indice in range(4):
            MisionVocabulario.objects.create(
                nivel=self.nivel,
                palabra_objetivo=f"palabra{indice}",
                tipo="VOZ",
                frase_historia=f"Esta es la frase número {indice}.",
            )

    def test_no_asigna_ejercicios_automaticamente(self):
        # Los ejercicios ya no se fijan al crear el DesafioDiario: se
        # personalizan por usuario (ver PersonalizacionEjerciciosTests).
        desafio = services.obtener_o_crear_desafio_de_hoy()

        self.assertEqual(desafio.fecha, timezone.localdate())
        self.assertEqual(desafio.ejercicios_obligatorios.count(), 0)
        self.assertEqual(desafio.ejercicios_opcionales.count(), 0)

    def test_es_idempotente_para_el_mismo_dia(self):
        desafio1 = services.obtener_o_crear_desafio_de_hoy()
        desafio2 = services.obtener_o_crear_desafio_de_hoy()
        self.assertEqual(desafio1.pk, desafio2.pk)


# ---------------------------------------------------------------------------
# Tests de personalización de ejercicios por nivel del usuario
# ---------------------------------------------------------------------------
class PersonalizacionEjerciciosTests(TestCase):
    """Tests de `services._nivel_numero_usuario` y `_obtener_ejercicios_desafio`."""

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(username="nivel_user", password="claveSegura123")
        self.nivel1 = Nivel.objects.create(numero=1, titulo="Inicio", puntos_recompensa=50)
        self.nivel3 = Nivel.objects.create(numero=3, titulo="Avanzado", puntos_recompensa=50)
        self.mision_nivel1 = MisionVocabulario.objects.create(
            nivel=self.nivel1, palabra_objetivo="sol", tipo="VOZ", frase_historia="El sol brilla.",
        )
        self.mision_nivel3 = MisionVocabulario.objects.create(
            nivel=self.nivel3, palabra_objetivo="estrella", tipo="VOZ", frase_historia="La estrella brilla.",
        )

    def test_sin_progreso_devuelve_nivel_1(self):
        self.assertEqual(services._nivel_numero_usuario(self.usuario), 1)

    def test_nivel_actual_se_respeta(self):
        ProgresoEstudiante.objects.create(usuario=self.usuario, nivel_actual=self.nivel3)
        self.assertEqual(services._nivel_numero_usuario(self.usuario), 3)

    def test_usuario_sin_progreso_no_recibe_ejercicios_de_nivel_superior(self):
        desafio = services.obtener_o_crear_desafio_de_hoy()
        obligatorios, opcionales = services._obtener_ejercicios_desafio(self.usuario, desafio)
        ids_asignados = {mision.id for mision in obligatorios + opcionales}

        self.assertIn(self.mision_nivel1.id, ids_asignados)
        self.assertNotIn(self.mision_nivel3.id, ids_asignados)

    def test_usuario_en_nivel_avanzado_si_puede_recibir_ejercicios_de_su_nivel(self):
        ProgresoEstudiante.objects.create(usuario=self.usuario, nivel_actual=self.nivel3)
        desafio = services.obtener_o_crear_desafio_de_hoy()
        obligatorios, opcionales = services._obtener_ejercicios_desafio(self.usuario, desafio)
        ids_asignados = {mision.id for mision in obligatorios + opcionales}

        self.assertIn(self.mision_nivel3.id, ids_asignados)

    def test_seleccion_es_determinista_para_el_mismo_usuario_y_dia(self):
        desafio = services.obtener_o_crear_desafio_de_hoy()
        primera = services._obtener_ejercicios_desafio(self.usuario, desafio)
        segunda = services._obtener_ejercicios_desafio(self.usuario, desafio)
        self.assertEqual(
            [mision.id for mision in primera[0] + primera[1]],
            [mision.id for mision in segunda[0] + segunda[1]],
        )

    def test_override_admin_tiene_prioridad_sobre_la_personalizacion(self):
        desafio = services.obtener_o_crear_desafio_de_hoy()
        desafio.ejercicios_obligatorios.set([self.mision_nivel3])

        obligatorios, opcionales = services._obtener_ejercicios_desafio(self.usuario, desafio)

        self.assertEqual([mision.id for mision in obligatorios], [self.mision_nivel3.id])
        self.assertEqual(opcionales, [])


# ---------------------------------------------------------------------------
# Tests de `procesar_intento_desafio`
# ---------------------------------------------------------------------------
class ProcesarIntentoDesafioTests(TestCase):
    """Tests de `services.procesar_intento_desafio`."""

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(username="reto_user", password="claveSegura123", monedas=0)
        self.nivel = Nivel.objects.create(numero=1, titulo="Inicio", puntos_recompensa=50)
        self.mision = MisionVocabulario.objects.create(
            nivel=self.nivel,
            palabra_objetivo="sol",
            tipo="VOZ",
            frase_historia="El sol brilla mucho hoy.",
        )
        Coleccionable.objects.create(nombre="Pluma Mágica", tipo="objeto_magico")

    def test_mision_id_invalido_devuelve_error(self):
        resultado = services.procesar_intento_desafio(self.usuario, _crear_audio_wav_falso(), 'no-es-un-id')
        self.assertEqual(resultado['status'], 'error')

    @patch.object(services, 'evaluar_pronunciacion_azure')
    def test_completar_unico_ejercicio_completa_el_desafio_y_otorga_monedas(self, mock_evaluar):
        mock_evaluar.return_value = {
            'status': 'success',
            'score_global': 90,
            'score_exactitud': 92,
            'palabras': [{'palabra': 'sol', 'score': 92}],
        }

        desafio = services.obtener_o_crear_desafio_de_hoy()

        resultado = services.procesar_intento_desafio(self.usuario, _crear_audio_wav_falso(), self.mision.id)

        self.assertEqual(resultado['status'], 'success')
        self.assertTrue(resultado['ejercicio_superado'])
        self.assertTrue(resultado['desafio_completado_ahora'])
        self.assertEqual(resultado['monedas_ganadas'], desafio.recompensa_monedas)

        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.monedas, desafio.recompensa_monedas)

        progreso = ProgresoDesafio.objects.get(usuario=self.usuario, desafio=desafio)
        self.assertTrue(progreso.completado)
        self.assertIsNotNone(progreso.fecha_completado)

    @patch.object(services, 'evaluar_pronunciacion_azure')
    def test_no_permite_repetir_un_desafio_ya_completado(self, mock_evaluar):
        mock_evaluar.return_value = {
            'status': 'success',
            'score_global': 90,
            'score_exactitud': 92,
            'palabras': [{'palabra': 'sol', 'score': 92}],
        }

        services.obtener_o_crear_desafio_de_hoy()
        services.procesar_intento_desafio(self.usuario, _crear_audio_wav_falso(), self.mision.id)

        resultado = services.procesar_intento_desafio(self.usuario, _crear_audio_wav_falso(), self.mision.id)
        self.assertEqual(resultado['status'], 'error')
        self.assertEqual(resultado['message'], 'El desafío de hoy ya está completado.')

    def test_mision_que_no_pertenece_al_desafio_de_hoy_devuelve_error(self):
        # El usuario no tiene ProgresoEstudiante (nivel 1 por defecto), así
        # que una misión de un nivel superior queda fuera de su selección
        # personalizada y debe rechazarse como ejercicio ajeno al desafío.
        services.obtener_o_crear_desafio_de_hoy()

        nivel_superior = Nivel.objects.create(numero=5, titulo="Avanzado", puntos_recompensa=50)
        otra_mision = MisionVocabulario.objects.create(
            nivel=nivel_superior,
            palabra_objetivo="luna",
            tipo="VOZ",
            frase_historia="La luna brilla por la noche.",
        )

        resultado = services.procesar_intento_desafio(self.usuario, _crear_audio_wav_falso(), otra_mision.id)
        self.assertEqual(resultado['status'], 'error')
        self.assertEqual(resultado['message'], 'Este ejercicio no pertenece al desafío de hoy.')


# ---------------------------------------------------------------------------
# Tests de la vista `evaluar_ejercicio`
# ---------------------------------------------------------------------------
class EvaluarEjercicioViewTests(TestCase):
    """Verifica que `evaluar_ejercicio` requiera sesión y no exponga errores internos."""

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(username="reto_view_user", password="claveSegura123")
        self.client.login(username="reto_view_user", password="claveSegura123")
        self.nivel = Nivel.objects.create(numero=1, titulo="Inicio", puntos_recompensa=50)
        self.mision = MisionVocabulario.objects.create(
            nivel=self.nivel,
            palabra_objetivo="sol",
            tipo="VOZ",
            frase_historia="El sol brilla mucho hoy.",
        )

    def test_requiere_login(self):
        self.client.logout()
        response = self.client.post(reverse('desafio_evaluar'), {})
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_metodo_get_no_permitido(self):
        response = self.client.get(reverse('desafio_evaluar'))
        self.assertEqual(response.status_code, 405)

    def test_sin_audio_devuelve_error_sin_lanzar_excepcion(self):
        response = self.client.post(reverse('desafio_evaluar'), {'mision_id': self.mision.id})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'error')

    def test_audio_invalido_no_expone_detalles_internos(self):
        archivo_falso = SimpleUploadedFile(
            "no_es_audio.txt",
            b"contenido invalido",
            content_type="text/plain",
        )
        response = self.client.post(reverse('desafio_evaluar'), {
            'audio': archivo_falso,
            'mision_id': self.mision.id,
        })

        self.assertEqual(response.status_code, 500)
        data = response.json()
        self.assertEqual(data['status'], 'error')

        mensaje = data['message']
        self.assertNotIn('Traceback', mensaje)
        self.assertNotIn('.py', mensaje)
        self.assertNotIn('ValueError', mensaje)
