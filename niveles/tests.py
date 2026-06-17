from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from django.core.exceptions import ValidationError

from .models import MisionVocabulario, Nivel, ProgresoEstudiante, ProgresoNivel, Zona
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
        # score=85 → 3 estrellas → RECOMPENSA_PRIMERA_VEZ[3] = 100
        resultado = services.calcular_recompensas(self.usuario, score=85)

        self.usuario.refresh_from_db()
        self.assertEqual(resultado['monedas_ganadas'], services.RECOMPENSA_PRIMERA_VEZ[3])
        self.assertEqual(resultado['monedas_totales'], services.RECOMPENSA_PRIMERA_VEZ[3])
        self.assertEqual(self.usuario.monedas, services.RECOMPENSA_PRIMERA_VEZ[3])
        # El Módulo A no debe modificar racha_dias.
        self.assertEqual(self.usuario.racha_dias, 0)

    def test_calcular_recompensas_no_otorga_monedas_si_no_supera_umbral(self):
        resultado = services.calcular_recompensas(self.usuario, score=40)

        self.usuario.refresh_from_db()
        self.assertEqual(resultado['monedas_ganadas'], 0)
        self.assertEqual(resultado['monedas_totales'], 0)
        self.assertEqual(self.usuario.monedas, 0)
        self.assertEqual(self.usuario.racha_dias, 0)

    def test_calcular_recompensas_repeticion_otorga_monto_fijo(self):
        """Repetir un nivel ya completado debe dar RECOMPENSA_REPETICION, no la de primera vez."""
        resultado = services.calcular_recompensas(self.usuario, score=85, ya_completado=True)

        self.usuario.refresh_from_db()
        self.assertEqual(resultado['monedas_ganadas'], services.RECOMPENSA_REPETICION)
        self.assertLess(resultado['monedas_ganadas'], services.RECOMPENSA_PRIMERA_VEZ[1])

    def test_calcular_recompensas_repeticion_score_bajo_otorga_monto_fijo(self):
        """Incluso con score bajo en repetición se dan las monedas fijas si score > 0."""
        resultado = services.calcular_recompensas(self.usuario, score=40, ya_completado=True)

        self.usuario.refresh_from_db()
        self.assertEqual(resultado['monedas_ganadas'], services.RECOMPENSA_REPETICION)

    def test_calcular_recompensas_repeticion_score_cero_no_otorga_monedas(self):
        """Score = 0 en repetición (sin voz detectada) no debe otorgar monedas."""
        resultado = services.calcular_recompensas(self.usuario, score=0, ya_completado=True)

        self.usuario.refresh_from_db()
        self.assertEqual(resultado['monedas_ganadas'], 0)


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


# ---------------------------------------------------------------------------
# Módulo D: Mapa de Aventura — modelo `Nivel` (zona/orden_en_zona/narrativa_intro)
# ---------------------------------------------------------------------------
class NivelZonaModeloTests(TestCase):
    """Verifica los nuevos campos de `Nivel` para el Mapa de Aventura (D.1)."""

    def test_defaults_de_zona_orden_y_narrativa(self):
        nivel = Nivel.objects.create(numero=99, titulo="Nivel de prueba")
        self.assertEqual(nivel.zona, Nivel.ZONA_BOSQUE)
        self.assertEqual(nivel.orden_en_zona, 1)
        self.assertEqual(nivel.narrativa_intro, '')

    def test_zona_choices_tiene_cinco_opciones(self):
        claves = [clave for clave, _etiqueta in Nivel.ZONA_CHOICES]
        self.assertEqual(len(Nivel.ZONA_CHOICES), 5)
        self.assertEqual(claves, [
            Nivel.ZONA_BOSQUE,
            Nivel.ZONA_MONTANA,
            Nivel.ZONA_VALLE,
            Nivel.ZONA_CASTILLO,
            Nivel.ZONA_REINO,
        ])


# ---------------------------------------------------------------------------
# Módulo D: `obtener_mapa_aventura`
# ---------------------------------------------------------------------------
class ObtenerMapaAventuraTests(TestCase):
    """Tests de `services.obtener_mapa_aventura` (D.1)."""

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(username="mapa_user", password="claveSegura123")
        # Replicamos el estado posterior a la migración de datos 0004:
        # tres niveles del Bosque Encantado, solo el nivel 1 con narrativa_intro.
        self.nivel1 = Nivel.objects.create(
            numero=1, titulo="Las Vocales", zona=Nivel.ZONA_BOSQUE, orden_en_zona=1,
            narrativa_intro="Bienvenido al Bosque Encantado...",
        )
        self.nivel2 = Nivel.objects.create(
            numero=2, titulo="Animales", zona=Nivel.ZONA_BOSQUE, orden_en_zona=2,
        )
        self.nivel3 = Nivel.objects.create(
            numero=3, titulo="Sonidos", zona=Nivel.ZONA_BOSQUE, orden_en_zona=3,
        )

    def test_orden_fijo_de_las_cinco_zonas(self):
        zonas = services.obtener_mapa_aventura(self.usuario)
        claves = [zona['clave'] for zona in zonas]
        self.assertEqual(claves, [
            Nivel.ZONA_BOSQUE,
            Nivel.ZONA_MONTANA,
            Nivel.ZONA_VALLE,
            Nivel.ZONA_CASTILLO,
            Nivel.ZONA_REINO,
        ])
        self.assertEqual(len(zonas), 5)

    def test_agrupa_niveles_existentes_en_bosque_encantado_con_orden_correcto(self):
        zonas = services.obtener_mapa_aventura(self.usuario)
        bosque = zonas[0]
        self.assertEqual(bosque['clave'], Nivel.ZONA_BOSQUE)
        self.assertEqual(len(bosque['niveles']), 3)
        ordenes = [n['orden_en_zona'] for n in bosque['niveles']]
        numeros = [n['numero'] for n in bosque['niveles']]
        self.assertEqual(ordenes, [1, 2, 3])
        self.assertEqual(numeros, [1, 2, 3])

    def test_usuario_sin_nivel_actual_todos_bloqueados_y_bosque_desbloqueado(self):
        # El usuario recién creado no tiene ProgresoEstudiante con nivel_actual.
        zonas = services.obtener_mapa_aventura(self.usuario)
        bosque = zonas[0]
        self.assertTrue(bosque['desbloqueada'])
        for nivel in bosque['niveles']:
            self.assertEqual(nivel['estado'], 'bloqueado')
        # El resto de zonas, sin niveles, no deben estar desbloqueadas.
        for zona in zonas[1:]:
            self.assertFalse(zona['desbloqueada'])

    def test_estado_de_niveles_segun_nivel_actual(self):
        progreso, _creado = ProgresoEstudiante.objects.get_or_create(usuario=self.usuario)
        progreso.nivel_actual = self.nivel2
        progreso.save()

        zonas = services.obtener_mapa_aventura(self.usuario)
        bosque = zonas[0]
        estados_por_numero = {n['numero']: n['estado'] for n in bosque['niveles']}

        self.assertEqual(estados_por_numero[1], 'completado')
        self.assertEqual(estados_por_numero[2], 'actual')
        self.assertEqual(estados_por_numero[3], 'bloqueado')
        self.assertTrue(bosque['desbloqueada'])

    def test_zonas_sin_niveles_devuelven_lista_vacia(self):
        zonas = services.obtener_mapa_aventura(self.usuario)
        for zona in zonas[1:]:
            self.assertEqual(zona['niveles'], [])

    def test_completado_sin_registro_de_estrellas_usa_3_por_defecto(self):
        """Nivel completado sin ProgresoNivel (datos de antes de esta función) -> 3 estrellas."""
        progreso, _creado = ProgresoEstudiante.objects.get_or_create(usuario=self.usuario)
        progreso.nivel_actual = self.nivel2
        progreso.save()

        zonas = services.obtener_mapa_aventura(self.usuario)
        nivel1 = next(n for n in zonas[0]['niveles'] if n['numero'] == 1)
        self.assertEqual(nivel1['estado'], 'completado')
        self.assertEqual(nivel1['mejores_estrellas'], 3)

    def test_completado_con_registro_usa_las_estrellas_guardadas(self):
        progreso, _creado = ProgresoEstudiante.objects.get_or_create(usuario=self.usuario)
        progreso.nivel_actual = self.nivel2
        progreso.save()
        ProgresoNivel.objects.create(progreso=progreso, nivel=self.nivel1, mejores_estrellas=1)

        zonas = services.obtener_mapa_aventura(self.usuario)
        nivel1 = next(n for n in zonas[0]['niveles'] if n['numero'] == 1)
        self.assertEqual(nivel1['mejores_estrellas'], 1)

    def test_nivel_actual_y_bloqueado_no_tienen_estrellas(self):
        progreso, _creado = ProgresoEstudiante.objects.get_or_create(usuario=self.usuario)
        progreso.nivel_actual = self.nivel2
        progreso.save()

        zonas = services.obtener_mapa_aventura(self.usuario)
        estados = {n['numero']: n for n in zonas[0]['niveles']}
        self.assertEqual(estados[2]['mejores_estrellas'], 0)
        self.assertEqual(estados[3]['mejores_estrellas'], 0)


# ---------------------------------------------------------------------------
# Módulo D: `construir_reaccion_avatar`
# ---------------------------------------------------------------------------
class ConstruirReaccionAvatarTests(TestCase):
    """Tests de `services.construir_reaccion_avatar` (D.2)."""

    def test_avanzo_de_nivel_devuelve_tipo_nivel_completado(self):
        reaccion = services.construir_reaccion_avatar(score_global=85, avanzo_de_nivel=True)
        self.assertEqual(reaccion['tipo'], 'nivel_completado')
        self.assertTrue(reaccion['mensaje'])

    def test_score_alto_sin_avance_devuelve_pronunciacion_correcta(self):
        reaccion = services.construir_reaccion_avatar(score_global=80, avanzo_de_nivel=False)
        self.assertEqual(reaccion['tipo'], 'pronunciacion_correcta')
        self.assertTrue(reaccion['mensaje'])

    def test_score_bajo_sin_avance_devuelve_pronunciacion_incorrecta(self):
        reaccion = services.construir_reaccion_avatar(score_global=40, avanzo_de_nivel=False)
        self.assertEqual(reaccion['tipo'], 'pronunciacion_incorrecta')
        self.assertTrue(reaccion['mensaje'])


# ---------------------------------------------------------------------------
# Módulo D: `guardar_progreso_estudiante` devuelve tupla (progreso, avanzo_de_nivel)
# ---------------------------------------------------------------------------
class GuardarProgresoEstudianteServicioTests(TestCase):
    """Tests directos de `services.guardar_progreso_estudiante` (D.2)."""

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(username="progreso_user", password="claveSegura123")
        self.nivel1 = Nivel.objects.create(numero=1, titulo="Inicio", puntos_recompensa=50)
        self.nivel2 = Nivel.objects.create(numero=2, titulo="Siguiente", puntos_recompensa=30)

    def test_score_suficiente_con_siguiente_nivel_avanza(self):
        progreso, avanzo_de_nivel, ya_completado = services.guardar_progreso_estudiante(
            self.usuario, self.nivel1.numero, {'score_global': 85},
        )
        self.assertTrue(avanzo_de_nivel)
        self.assertFalse(ya_completado)
        self.assertEqual(progreso.nivel_actual, self.nivel2)

    def test_score_insuficiente_no_avanza(self):
        progreso, avanzo_de_nivel, ya_completado = services.guardar_progreso_estudiante(
            self.usuario, self.nivel1.numero, {'score_global': 40},
        )
        self.assertFalse(avanzo_de_nivel)
        self.assertFalse(ya_completado)
        self.assertIsNone(progreso.nivel_actual)

    def test_repeticion_detecta_ya_completado(self):
        """Si el nivel está por debajo del nivel_actual, ya_completado debe ser True."""
        progreso, _ = ProgresoEstudiante.objects.get_or_create(usuario=self.usuario)
        progreso.nivel_actual = self.nivel2
        progreso.save()

        _progreso, _avanzo, ya_completado = services.guardar_progreso_estudiante(
            self.usuario, self.nivel1.numero, {'score_global': 85},
        )
        self.assertTrue(ya_completado)

    def test_score_suficiente_guarda_mejores_estrellas(self):
        """Un intento aprobado (score=85 -> 3 estrellas) debe quedar en ProgresoNivel."""
        progreso, _, _ = services.guardar_progreso_estudiante(
            self.usuario, self.nivel1.numero, {'score_global': 85},
        )
        progreso_nivel = ProgresoNivel.objects.get(progreso=progreso, nivel=self.nivel1)
        self.assertEqual(progreso_nivel.mejores_estrellas, 3)

    def test_repeticion_con_peor_score_no_baja_las_estrellas(self):
        """Repetir con menos estrellas que el mejor anterior no debe bajar el registro."""
        progreso, _, _ = services.guardar_progreso_estudiante(
            self.usuario, self.nivel1.numero, {'score_global': 85},  # 3 estrellas
        )
        services.guardar_progreso_estudiante(
            self.usuario, self.nivel1.numero, {'score_global': 70},  # 2 estrellas
        )
        progreso_nivel = ProgresoNivel.objects.get(progreso=progreso, nivel=self.nivel1)
        self.assertEqual(progreso_nivel.mejores_estrellas, 3)


# ---------------------------------------------------------------------------
# Módulo D: `procesar_intento_nivel`
# ---------------------------------------------------------------------------
class ProcesarIntentoNivelTests(TestCase):
    """Tests de `services.procesar_intento_nivel` (D.2)."""

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(username="intento_user", password="claveSegura123")
        self.nivel1 = Nivel.objects.create(numero=1, titulo="Inicio", puntos_recompensa=50)
        self.nivel2 = Nivel.objects.create(numero=2, titulo="Siguiente", puntos_recompensa=30)

    @patch.object(services, 'evaluar_pronunciacion_azure')
    def test_resultado_exitoso_incluye_todas_las_claves_esperadas(self, mock_evaluar):
        mock_evaluar.return_value = {
            'status': 'success',
            'score_global': 85,
            'score_exactitud': 90,
            'score_fluidez': 88,
            'texto_reconocido': 'sol',
            'palabras': [{'palabra': 'sol', 'score': 90}],
        }

        wav_header = (
            b'RIFF' + (36).to_bytes(4, 'little') + b'WAVEfmt '
            + (16).to_bytes(4, 'little')
            + (1).to_bytes(2, 'little') + (1).to_bytes(2, 'little')
            + (16000).to_bytes(4, 'little') + (32000).to_bytes(4, 'little')
            + (2).to_bytes(2, 'little') + (16).to_bytes(2, 'little')
            + b'data' + (0).to_bytes(4, 'little')
        )
        archivo_audio = SimpleUploadedFile("audio.wav", wav_header, content_type="audio/wav")

        resultado = services.procesar_intento_nivel(
            self.usuario, archivo_audio, 'sol', self.nivel1.numero,
        )

        self.assertEqual(resultado['status'], 'success')
        self.assertEqual(resultado['score'], 85)
        self.assertEqual(resultado['score_exactitud'], 90)
        self.assertEqual(resultado['palabras'], [{'palabra': 'sol', 'score': 90}])
        self.assertTrue(resultado['avanzo_de_nivel'])
        # score=85 → 3 estrellas → RECOMPENSA_PRIMERA_VEZ[3] = 100
        self.assertEqual(resultado['monedas_ganadas'], services.RECOMPENSA_PRIMERA_VEZ[3])
        self.assertEqual(resultado['monedas_totales'], services.RECOMPENSA_PRIMERA_VEZ[3])
        self.assertIn('tipo', resultado['reaccion_avatar'])
        self.assertEqual(resultado['reaccion_avatar']['tipo'], 'nivel_completado')
        self.assertEqual(resultado['estrellas'], 3)


# ---------------------------------------------------------------------------
# Módulo D: contexto de `niveles_view` y render del template (mapa de aventura)
# ---------------------------------------------------------------------------
class MapaAventuraViewTests(TestCase):
    """Verifica el contexto `zonas_mapa` y el render del Mapa de Aventura (D.1/D.3)."""

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(username="mapa_view_user", password="claveSegura123")
        self.nivel1 = Nivel.objects.create(
            numero=1, titulo="Las Vocales", zona=Nivel.ZONA_BOSQUE, orden_en_zona=1,
            narrativa_intro="Bienvenido al Bosque Encantado...",
        )
        MisionVocabulario.objects.create(
            nivel=self.nivel1,
            palabra_objetivo="sol",
            tipo="VOZ",
            frase_historia="El sol brilla mucho hoy.",
        )
        self.client.login(username="mapa_view_user", password="claveSegura123")

    def test_contexto_incluye_zonas_mapa_con_cinco_elementos(self):
        response = self.client.get(reverse('niveles'))
        self.assertIn('zonas_mapa', response.context)
        self.assertEqual(len(response.context['zonas_mapa']), 5)

    def test_contexto_incluye_mostrar_puntuacion_detallada(self):
        response = self.client.get(reverse('niveles'))
        self.assertIn('mostrar_puntuacion_detallada', response.context)

    def test_render_no_contiene_mundos_hardcodeados_y_si_elementos_nuevos(self):
        response = self.client.get(reverse('niveles'))
        contenido = response.content.decode()

        self.assertNotIn('Mundo 1', contenido)
        self.assertNotIn('Mundo 2', contenido)
        self.assertIn('modal-narrativa', contenido)
        self.assertIn('resultado-estrellas', contenido)  # siempre visible (B.2)
        self.assertIn('Bosque Encantado', contenido)
        self.assertIn('data-narrativa-intro', contenido)


# ---------------------------------------------------------------------------
# B.3 — Orden automático de niveles al crear (orden_en_zona auto-incremental)
# ---------------------------------------------------------------------------
class OrdenAutomaticoNivelTests(TestCase):
    """Verifica que orden_en_zona se asigne automáticamente al crear un Nivel sin especificarlo."""

    def test_primer_nivel_en_zona_recibe_orden_1(self):
        nivel = Nivel.objects.create(numero=50, titulo="Primero", zona=Nivel.ZONA_MONTANA)
        self.assertEqual(nivel.orden_en_zona, 1)

    def test_segundo_nivel_en_zona_recibe_orden_2(self):
        Nivel.objects.create(numero=51, titulo="A", zona=Nivel.ZONA_MONTANA)
        nivel_b = Nivel.objects.create(numero=52, titulo="B", zona=Nivel.ZONA_MONTANA)
        self.assertEqual(nivel_b.orden_en_zona, 2)

    def test_auto_orden_es_independiente_por_zona(self):
        """Dos zonas distintas tienen sus propias secuencias de orden."""
        Nivel.objects.create(numero=60, titulo="Bosque1", zona=Nivel.ZONA_BOSQUE)
        Nivel.objects.create(numero=61, titulo="Bosque2", zona=Nivel.ZONA_BOSQUE)
        nivel_montana = Nivel.objects.create(numero=70, titulo="Montana1", zona=Nivel.ZONA_MONTANA)
        self.assertEqual(nivel_montana.orden_en_zona, 1)

    def test_orden_explicito_no_es_sobreescrito(self):
        """Si se especifica orden_en_zona explícitamente, el save() no lo cambia."""
        nivel = Nivel.objects.create(numero=80, titulo="Manual", zona=Nivel.ZONA_VALLE, orden_en_zona=99)
        self.assertEqual(nivel.orden_en_zona, 99)


# ---------------------------------------------------------------------------
# B.1+B.2 — score_a_estrellas y lógica de recompensas
# ---------------------------------------------------------------------------
class ScoreAEstrellasTests(TestCase):
    """Verifica la conversión de score a estrellas."""

    def test_score_excelente_da_3_estrellas(self):
        self.assertEqual(services.score_a_estrellas(90), 3)
        self.assertEqual(services.score_a_estrellas(85), 3)

    def test_score_bueno_da_2_estrellas(self):
        self.assertEqual(services.score_a_estrellas(70), 2)
        self.assertEqual(services.score_a_estrellas(80), 2)

    def test_score_bajo_da_1_estrella(self):
        self.assertEqual(services.score_a_estrellas(50), 1)
        self.assertEqual(services.score_a_estrellas(0), 1)


# ---------------------------------------------------------------------------
# Bloqueo de zonas (PROMPT_BLOQUEO_ZONAS.md)
# ---------------------------------------------------------------------------
class ZonaCerradaTests(TestCase):
    """
    Verifica que `Zona.cerrada` bloquee la creación de niveles nuevos a
    nivel de modelo (la protección real), sin afectar la edición de niveles
    ya existentes ni a las zonas que no tienen fila en `Zona` todavía.
    """

    def setUp(self):
        # Las 5 zonas ya vienen sembradas por la migración de datos
        # (0009_seed_zonas) — para estos tests solo ajustamos su estado.
        Zona.objects.filter(clave=Nivel.ZONA_CASTILLO).update(cerrada=True)

    def test_crear_nivel_en_zona_cerrada_lanza_validation_error(self):
        with self.assertRaises(ValidationError):
            Nivel.objects.create(numero=901, titulo='Intento bloqueado', zona=Nivel.ZONA_CASTILLO)

    def test_crear_nivel_en_zona_cerrada_no_lo_guarda(self):
        try:
            Nivel.objects.create(numero=902, titulo='Intento bloqueado', zona=Nivel.ZONA_CASTILLO)
        except ValidationError:
            pass
        self.assertFalse(Nivel.objects.filter(numero=902).exists())

    def test_editar_nivel_existente_en_zona_cerrada_no_lanza_error(self):
        """Cerrar la zona después de crear el nivel no debe impedir editarlo."""
        nivel = Nivel.objects.create(numero=903, titulo='Nivel previo', zona=Nivel.ZONA_VALLE)

        Zona.objects.filter(clave=Nivel.ZONA_VALLE).update(cerrada=True)

        nivel.titulo = 'Nivel previo editado'
        nivel.save()  # no debe lanzar ValidationError
        nivel.refresh_from_db()
        self.assertEqual(nivel.titulo, 'Nivel previo editado')

    def test_crear_nivel_en_zona_sin_fila_zona_no_se_bloquea(self):
        """Si la zona no tiene fila en Zona todavía, cerrada es opcional, no bloquea."""
        Zona.objects.filter(clave=Nivel.ZONA_REINO).delete()
        nivel = Nivel.objects.create(numero=904, titulo='Sin restricción', zona=Nivel.ZONA_REINO)
        self.assertEqual(nivel.zona, Nivel.ZONA_REINO)

    def test_crear_nivel_en_zona_abierta_funciona(self):
        Zona.objects.filter(clave=Nivel.ZONA_CASTILLO).update(cerrada=False)
        nivel = Nivel.objects.create(numero=905, titulo='Ahora sí', zona=Nivel.ZONA_CASTILLO)
        self.assertEqual(nivel.zona, Nivel.ZONA_CASTILLO)

    def test_orden_en_zona_automatico_sigue_funcionando_en_zona_abierta(self):
        Nivel.objects.create(numero=906, titulo='Primero', zona=Nivel.ZONA_VALLE)
        segundo = Nivel.objects.create(numero=907, titulo='Segundo', zona=Nivel.ZONA_VALLE)
        self.assertEqual(segundo.orden_en_zona, 2)


class ZonaModeloTests(TestCase):
    def test_str_devuelve_nombre(self):
        zona = Zona.objects.get(clave=Nivel.ZONA_BOSQUE)
        self.assertEqual(str(zona), 'Bosque Encantado')

    def test_clave_es_unica(self):
        with self.assertRaises(Exception):
            Zona.objects.create(clave=Nivel.ZONA_BOSQUE, nombre='Duplicada', orden=1)

    def test_las_cinco_zonas_quedan_sembradas_por_la_migracion(self):
        self.assertEqual(Zona.objects.count(), 5)
