import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from camara_inteligente import services as camara_services
from camara_inteligente.models import FraseTemplate
from desafio import services as desafio_services
from historias import services as historias_services
from historias.models import Historia, ProgresoHistoria
from niveles import services as niveles_services
from niveles.models import MisionVocabulario, Nivel, ProgresoEstudiante, ProgresoNivel
from recompensas.models import Coleccionable, ColeccionableUsuario, Insignia, TipoInsignia

from . import services
from .models import RegistroActividad

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
# Tests del modelo `RegistroActividad`
# ---------------------------------------------------------------------------
class RegistroActividadModelTests(TestCase):
    """Tests básicos del modelo `RegistroActividad` y su manager."""

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(username='est_user', password='claveSegura123')

    def test_registrar_crea_registro_con_fecha_automatica(self):
        registro = RegistroActividad.objects.registrar(
            self.usuario, RegistroActividad.TIPO_NIVEL, 85, zona=Nivel.ZONA_BOSQUE,
        )
        self.assertEqual(registro.fecha, timezone.localdate())
        self.assertEqual(registro.score, 85)
        self.assertEqual(registro.zona, Nivel.ZONA_BOSQUE)

    def test_str_incluye_usuario_y_tipo(self):
        registro = RegistroActividad.objects.registrar(self.usuario, RegistroActividad.TIPO_CAMARA, 75)
        self.assertIn(self.usuario.username, str(registro))
        self.assertIn('Cámara', str(registro))


# ---------------------------------------------------------------------------
# Tests de `construir_datos_semana`
# ---------------------------------------------------------------------------
class ConstruirDatosSemanaTests(TestCase):
    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(username='semana_user', password='claveSegura123')

    def test_cuenta_actividades_por_dia(self):
        hoy = timezone.localdate()
        ayer = hoy - datetime.timedelta(days=1)

        r1 = RegistroActividad.objects.registrar(self.usuario, RegistroActividad.TIPO_NIVEL, 80)
        r2 = RegistroActividad.objects.registrar(self.usuario, RegistroActividad.TIPO_NIVEL, 90)
        RegistroActividad.objects.filter(pk__in=[r1.pk, r2.pk]).update(fecha=ayer)

        RegistroActividad.objects.registrar(self.usuario, RegistroActividad.TIPO_CAMARA, 70)

        datos = services.construir_datos_semana(self.usuario)
        self.assertEqual(len(datos), 7)

        dato_ayer = next(d for d in datos if d['fecha'] == ayer)
        dato_hoy = next(d for d in datos if d['fecha'] == hoy)

        self.assertEqual(dato_ayer['cantidad'], 2)
        self.assertEqual(dato_hoy['cantidad'], 1)
        self.assertTrue(dato_hoy['es_hoy'])
        self.assertEqual(dato_ayer['altura_porcentaje'], 100)
        self.assertEqual(dato_hoy['altura_porcentaje'], 50)

    def test_sin_actividad_devuelve_ceros(self):
        datos = services.construir_datos_semana(self.usuario)
        self.assertTrue(all(d['cantidad'] == 0 for d in datos))


# ---------------------------------------------------------------------------
# Tests de `construir_progreso_por_zona`
# ---------------------------------------------------------------------------
class ConstruirProgresoPorZonaTests(TestCase):
    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(username='zona_user', password='claveSegura123')
        self.nivel1 = Nivel.objects.create(numero=1, titulo='Uno', zona=Nivel.ZONA_BOSQUE)
        self.nivel2 = Nivel.objects.create(numero=2, titulo='Dos', zona=Nivel.ZONA_BOSQUE)
        self.nivel3 = Nivel.objects.create(numero=3, titulo='Tres', zona=Nivel.ZONA_MONTANA)

    def test_porcentaje_completado_por_zona(self):
        progreso = ProgresoEstudiante.objects.create(usuario=self.usuario)
        # Marcar los dos niveles del bosque como completados via ProgresoNivel.
        ProgresoNivel.objects.create(progreso=progreso, nivel=self.nivel1, mejores_estrellas=3)
        ProgresoNivel.objects.create(progreso=progreso, nivel=self.nivel2, mejores_estrellas=2)
        resultado = services.construir_progreso_por_zona(progreso)

        bosque = next(z for z in resultado if z['clave'] == Nivel.ZONA_BOSQUE)
        montana = next(z for z in resultado if z['clave'] == Nivel.ZONA_MONTANA)

        self.assertEqual(bosque['porcentaje'], 100)
        self.assertEqual(montana['porcentaje'], 0)

    def test_sin_nivel_actual_todo_en_cero(self):
        progreso = ProgresoEstudiante.objects.create(usuario=self.usuario)
        resultado = services.construir_progreso_por_zona(progreso)
        self.assertTrue(all(z['porcentaje'] == 0 for z in resultado))

    def test_zonas_sin_niveles_no_aparecen(self):
        progreso = ProgresoEstudiante.objects.create(usuario=self.usuario)
        resultado = services.construir_progreso_por_zona(progreso)
        claves = [z['clave'] for z in resultado]
        self.assertNotIn(Nivel.ZONA_VALLE, claves)


# ---------------------------------------------------------------------------
# Tests de `construir_areas_mejora`
# ---------------------------------------------------------------------------
class ConstruirAreasMejoraTests(TestCase):
    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(username='mejora_user', password='claveSegura123')

    def test_zona_con_score_promedio_bajo_aparece(self):
        RegistroActividad.objects.registrar(self.usuario, RegistroActividad.TIPO_NIVEL, 40, zona=Nivel.ZONA_BOSQUE)
        RegistroActividad.objects.registrar(self.usuario, RegistroActividad.TIPO_NIVEL, 50, zona=Nivel.ZONA_BOSQUE)

        areas = services.construir_areas_mejora(self.usuario)
        bosque = next(a for a in areas if a['clave'] == Nivel.ZONA_BOSQUE)
        self.assertEqual(bosque['score_promedio'], 45)

    def test_zona_con_buen_score_no_aparece(self):
        RegistroActividad.objects.registrar(self.usuario, RegistroActividad.TIPO_NIVEL, 90, zona=Nivel.ZONA_BOSQUE)
        areas = services.construir_areas_mejora(self.usuario)
        claves = [a['clave'] for a in areas]
        self.assertNotIn(Nivel.ZONA_BOSQUE, claves)

    def test_zona_sin_registros_no_aparece(self):
        self.assertEqual(services.construir_areas_mejora(self.usuario), [])


# ---------------------------------------------------------------------------
# Tests de `construir_calendario_progreso` (H.2)
# ---------------------------------------------------------------------------
class ConstruirCalendarioProgresoTests(TestCase):
    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(username='calendario_user', password='claveSegura123')

    def test_estructura_de_semanas_y_dias(self):
        calendario = services.construir_calendario_progreso(self.usuario)
        self.assertEqual(len(calendario), services.SEMANAS_CALENDARIO)
        for semana in calendario:
            self.assertEqual(len(semana), 7)

    def test_marca_dia_con_actividad(self):
        RegistroActividad.objects.registrar(self.usuario, RegistroActividad.TIPO_NIVEL, 80)
        hoy = timezone.localdate()

        calendario = services.construir_calendario_progreso(self.usuario)
        dia_hoy = next(d for semana in calendario for d in semana if d['fecha'] == hoy)
        self.assertTrue(dia_hoy['tiene_actividad'])
        self.assertTrue(dia_hoy['es_hoy'])

    def test_dias_futuros_marcados(self):
        calendario = services.construir_calendario_progreso(self.usuario)
        hoy = timezone.localdate()
        dias_futuros = [d for semana in calendario for d in semana if d['fecha'] > hoy]
        self.assertTrue(all(d['es_futuro'] for d in dias_futuros))


# ---------------------------------------------------------------------------
# Tests de `construir_galeria_coleccionables` (H.3)
# ---------------------------------------------------------------------------
class ConstruirGaleriaColeccionablesTests(TestCase):
    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(username='galeria_user', password='claveSegura123')
        self.coleccionable1 = Coleccionable.objects.create(nombre='Dragón Dorado', tipo='animal')
        self.coleccionable2 = Coleccionable.objects.create(nombre='Carta Mágica', tipo='carta')
        ColeccionableUsuario.objects.create(usuario=self.usuario, coleccionable=self.coleccionable1)

    def test_agrupa_por_tipo_y_marca_obtenidos(self):
        galeria = services.construir_galeria_coleccionables(self.usuario)
        tipos = {g['tipo'] for g in galeria}
        self.assertEqual(tipos, {'animal', 'carta'})

        grupo_animal = next(g for g in galeria if g['tipo'] == 'animal')
        self.assertTrue(grupo_animal['items'][0]['obtenido'])

        grupo_carta = next(g for g in galeria if g['tipo'] == 'carta')
        self.assertFalse(grupo_carta['items'][0]['obtenido'])


# ---------------------------------------------------------------------------
# Tests de `construir_insignias`
# ---------------------------------------------------------------------------
class ConstruirInsigniasTests(TestCase):
    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(username='insignia_user', password='claveSegura123')
        self.tipo_insignia = TipoInsignia.objects.create(nombre='Primera Racha', criterio='racha_7')
        Insignia.objects.create(usuario=self.usuario, tipo_insignia=self.tipo_insignia)

    def test_lista_insignias_con_nombre_y_fecha(self):
        insignias = services.construir_insignias(self.usuario)
        self.assertEqual(len(insignias), 1)
        self.assertEqual(insignias[0]['nombre'], 'Primera Racha')
        self.assertIsNotNone(insignias[0]['fecha_obtenida'])

    def test_insignia_recien_obtenida_es_nueva(self):
        insignias = services.construir_insignias(self.usuario)
        self.assertTrue(insignias[0]['es_nueva'])

    def test_insignia_antigua_no_es_nueva(self):
        fecha_antigua = timezone.now() - datetime.timedelta(days=services.DIAS_INSIGNIA_NUEVA + 1)
        Insignia.objects.filter(usuario=self.usuario).update(fecha_obtenida=fecha_antigua)
        insignias = services.construir_insignias(self.usuario)
        self.assertFalse(insignias[0]['es_nueva'])


# ---------------------------------------------------------------------------
# Tests de `construir_contexto_estadisticas`
# ---------------------------------------------------------------------------
class ConstruirContextoEstadisticasTests(TestCase):
    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(
            username='contexto_user', password='claveSegura123', racha_dias=5,
        )
        self.nivel1 = Nivel.objects.create(numero=1, titulo='Inicio', zona=Nivel.ZONA_BOSQUE)
        self.nivel2 = Nivel.objects.create(numero=2, titulo='Avance', zona=Nivel.ZONA_BOSQUE)
        progreso = ProgresoEstudiante.objects.create(usuario=self.usuario, nivel_actual=self.nivel2)
        ProgresoNivel.objects.create(progreso=progreso, nivel=self.nivel1, mejores_estrellas=3)
        RegistroActividad.objects.registrar(self.usuario, RegistroActividad.TIPO_NIVEL, 80, zona=Nivel.ZONA_BOSQUE)

    def test_contiene_todas_las_claves_esperadas(self):
        contexto = services.construir_contexto_estadisticas(self.usuario)
        claves_esperadas = {
            'nivel_actual_numero', 'nivel_actual_titulo', 'puntuacion_total', 'racha_dias',
            'lecciones_completadas', 'progreso_general_porcentaje', 'palabras_pronunciadas',
            'historias_completadas', 'insignias', 'coleccionables', 'datos_semana',
            'progreso_por_zona', 'areas_mejora', 'calendario',
        }
        self.assertEqual(set(contexto.keys()), claves_esperadas)

    def test_valores_basicos_correctos(self):
        contexto = services.construir_contexto_estadisticas(self.usuario)
        self.assertEqual(contexto['nivel_actual_numero'], 2)
        self.assertEqual(contexto['nivel_actual_titulo'], 'Avance')
        self.assertEqual(contexto['racha_dias'], 5)
        self.assertEqual(contexto['lecciones_completadas'], 1)
        self.assertEqual(contexto['palabras_pronunciadas'], 1)
        self.assertEqual(contexto['puntuacion_total'], 80)
        self.assertEqual(contexto['progreso_general_porcentaje'], 50)


# ---------------------------------------------------------------------------
# Tests de la vista `estadisticas_view`
# ---------------------------------------------------------------------------
class EstadisticasViewTests(TestCase):
    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(username='vista_user', password='claveSegura123')

    def test_redirige_si_no_hay_sesion(self):
        response = self.client.get(reverse('estadisticas'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_renderiza_200_con_sesion(self):
        self.client.login(username='vista_user', password='claveSegura123')
        response = self.client.get(reverse('estadisticas'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'estadisticas/estadisticas.html')
        self.assertIn('datos_semana', response.context)
        self.assertIn('calendario', response.context)
        self.assertIn('coleccionables', response.context)


# ---------------------------------------------------------------------------
# Tests de integración: RegistroActividad creado desde otros módulos
# ---------------------------------------------------------------------------
class RegistroActividadDesdeNivelesTests(TestCase):
    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(
            username='hook_nivel_user', password='claveSegura123', monedas=0,
        )
        self.nivel = Nivel.objects.create(
            numero=1, titulo='Inicio', puntos_recompensa=50, zona=Nivel.ZONA_MONTANA,
        )

    @patch.object(niveles_services, 'evaluar_pronunciacion_azure')
    def test_intento_nivel_exitoso_registra_actividad_con_zona(self, mock_evaluar):
        mock_evaluar.return_value = {
            'status': 'success', 'score_global': 90, 'score_exactitud': 92, 'palabras': [],
        }

        niveles_services.procesar_intento_nivel(self.usuario, _crear_audio_wav_falso(), 'sol', self.nivel.numero)

        registro = RegistroActividad.objects.get(usuario=self.usuario)
        self.assertEqual(registro.tipo_actividad, RegistroActividad.TIPO_NIVEL)
        self.assertEqual(registro.zona, Nivel.ZONA_MONTANA)
        self.assertEqual(registro.score, 90)


class RegistroActividadDesdeHistoriasTests(TestCase):
    fixtures = ['historias_inicial']

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(username='hook_historia_user', password='claveSegura123')
        self.historia3 = Historia.objects.get(pk=3)
        ProgresoHistoria.objects.create(usuario=self.usuario, historia=self.historia3, fragmento_actual_id=6)

    @patch.object(historias_services, 'procesar_audio_subido')
    @patch.object(historias_services, 'evaluar_pronunciacion_azure')
    def test_pronunciar_exitoso_registra_actividad(self, mock_evaluar, mock_procesar):
        mock_procesar.return_value = '/tmp/audio_falso.wav'
        mock_evaluar.return_value = {'status': 'success', 'score_global': 85, 'palabras': []}

        audio = SimpleUploadedFile('audio.wav', b'contenido', content_type='audio/wav')
        historias_services.procesar_respuesta_fragmento(
            self.usuario, self.historia3, fragmento_id=6, archivo_audio=audio,
        )

        registro = RegistroActividad.objects.get(usuario=self.usuario)
        self.assertEqual(registro.tipo_actividad, RegistroActividad.TIPO_HISTORIA)
        self.assertEqual(registro.score, 85)
        self.assertEqual(registro.zona, '')


class RegistroActividadDesdeDesafioTests(TestCase):
    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(
            username='hook_desafio_user', password='claveSegura123', monedas=0,
        )
        self.nivel = Nivel.objects.create(
            numero=1, titulo='Inicio', puntos_recompensa=50, zona=Nivel.ZONA_VALLE,
        )
        self.mision = MisionVocabulario.objects.create(
            nivel=self.nivel, palabra_objetivo='sol', tipo='VOZ', frase_historia='El sol brilla.',
        )
        Coleccionable.objects.create(nombre='Pluma Mágica', tipo='objeto_magico')

    @patch.object(desafio_services, 'evaluar_pronunciacion_azure')
    def test_intento_desafio_exitoso_registra_actividad_con_zona(self, mock_evaluar):
        mock_evaluar.return_value = {
            'status': 'success', 'score_global': 90, 'score_exactitud': 92, 'palabras': [],
        }

        desafio_services.procesar_intento_desafio(self.usuario, _crear_audio_wav_falso(), self.mision.id)

        registro = RegistroActividad.objects.get(usuario=self.usuario)
        self.assertEqual(registro.tipo_actividad, RegistroActividad.TIPO_DESAFIO)
        self.assertEqual(registro.zona, Nivel.ZONA_VALLE)
        self.assertEqual(registro.score, 90)


class RegistroActividadDesdeCamaraTests(TestCase):
    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(
            username='hook_camara_user', password='claveSegura123', monedas=0,
        )
        self.frase = FraseTemplate.objects.create(
            objeto_keyword='lápiz', frase_plantilla='El lápiz es largo.', nivel_dificultad=1, recompensa_monedas=5,
        )

    @patch.object(camara_services, 'evaluar_pronunciacion_azure')
    def test_evaluacion_camara_exitosa_registra_actividad(self, mock_evaluar):
        mock_evaluar.return_value = {
            'status': 'success', 'score_global': 80, 'score_exactitud': 82, 'palabras': [],
        }

        camara_services.procesar_evaluacion_pronunciacion(
            self.usuario, _crear_audio_wav_falso(), self.frase.frase_plantilla,
        )

        registro = RegistroActividad.objects.get(usuario=self.usuario)
        self.assertEqual(registro.tipo_actividad, RegistroActividad.TIPO_CAMARA)
        self.assertEqual(registro.score, 80)
