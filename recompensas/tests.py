"""
Tests del módulo `recompensas`.

Cubre los modelos básicos del sistema de recompensas unificado y la capa de
servicios (`recompensas/services.py`): otorgamiento de monedas, racha diaria,
verificación/otorgamiento de insignias, insignias pendientes, el signal que
conecta `ProgresoEstudiante` con la verificación de insignias y las claves
nuevas expuestas por el context processor `avatar.context_processors.avatar_global`.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from avatar.context_processors import avatar_global
from niveles.models import Nivel, ProgresoEstudiante, ProgresoNivel
from django.db.models.signals import post_save

from . import services
from .models import (
    Coleccionable,
    ColeccionableUsuario,
    EventoEspecial,
    Insignia,
    Mascota,
    MascotaUsuario,
    TipoInsignia,
)
from .signals import manejar_progreso_guardado

UsuarioCustom = get_user_model()


# ---------------------------------------------------------------------------
# Tests de modelos
# ---------------------------------------------------------------------------
class ModelosRecompensasTests(TestCase):
    """Tests básicos de creación y representación de los modelos de `recompensas`."""

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(
            username="modelo_user", password="claveSegura123",
        )

    def test_creacion_tipo_insignia_e_insignia(self):
        tipo = TipoInsignia.objects.create(
            nombre="Primeros Pasos",
            descripcion="Completaste tu primer nivel.",
            criterio="primer_nivel",
            valor_umbral=1,
        )
        insignia = Insignia.objects.create(usuario=self.usuario, tipo_insignia=tipo)

        self.assertEqual(str(tipo), "Primeros Pasos")
        self.assertIn(str(self.usuario), str(insignia))
        self.assertFalse(insignia.mostrada)

    def test_creacion_mascota_y_mascota_usuario(self):
        mascota = Mascota.objects.create(nombre="Chispa", especie="dragon", precio_monedas=200)
        mascota_usuario = MascotaUsuario.objects.create(usuario=self.usuario, mascota=mascota)

        self.assertIn("Chispa", str(mascota))
        self.assertEqual(mascota_usuario.mascota, mascota)
        self.assertEqual(mascota_usuario.nivel_afecto, 0)

    def test_creacion_coleccionable_y_coleccionable_usuario(self):
        coleccionable = Coleccionable.objects.create(
            nombre="Carta Dorada", tipo="carta", precio_monedas=50,
        )
        relacion = ColeccionableUsuario.objects.create(usuario=self.usuario, coleccionable=coleccionable)

        self.assertIn("Carta Dorada", str(coleccionable))
        self.assertEqual(relacion.coleccionable, coleccionable)

    def test_creacion_evento_especial(self):
        hoy = timezone.localdate()
        evento = EventoEspecial.objects.create(
            nombre="Navidad 2026",
            tipo="navidad",
            fecha_inicio=hoy,
            fecha_fin=hoy + timedelta(days=10),
            activo=True,
        )
        self.assertIn("Navidad 2026", str(evento))
        self.assertTrue(evento.activo)


# ---------------------------------------------------------------------------
# Tests de `otorgar_monedas`
# ---------------------------------------------------------------------------
class OtorgarMonedasTests(TestCase):
    """Tests de `services.otorgar_monedas`."""

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(
            username="monedas_user", password="claveSegura123", monedas=10,
        )

    def test_otorgar_monedas_suma_correctamente(self):
        saldo = services.otorgar_monedas(self.usuario, 50, concepto="prueba")

        self.usuario.refresh_from_db()
        self.assertEqual(saldo, 60)
        self.assertEqual(self.usuario.monedas, 60)

    def test_otorgar_monedas_resta_correctamente(self):
        saldo = services.otorgar_monedas(self.usuario, -5, concepto="compra")

        self.usuario.refresh_from_db()
        self.assertEqual(saldo, 5)
        self.assertEqual(self.usuario.monedas, 5)

    def test_otorgar_monedas_repetidas_son_acumulativas(self):
        """Llamadas repetidas con el mismo valor deben acumularse (uso de F())."""
        services.otorgar_monedas(self.usuario, 10, concepto="repeticion_1")
        services.otorgar_monedas(self.usuario, 10, concepto="repeticion_2")
        saldo_final = services.otorgar_monedas(self.usuario, 10, concepto="repeticion_3")

        self.usuario.refresh_from_db()
        self.assertEqual(saldo_final, 40)
        self.assertEqual(self.usuario.monedas, 40)


# ---------------------------------------------------------------------------
# Tests de `actualizar_racha`
# ---------------------------------------------------------------------------
class ActualizarRachaTests(TestCase):
    """Tests de `services.actualizar_racha`."""

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(
            username="racha_user", password="claveSegura123",
        )
        self.hoy = timezone.localdate()

    def test_primera_conexion_inicia_racha_en_1(self):
        self.usuario.ultima_fecha_conexion = None
        self.usuario.racha_dias = 0
        self.usuario.save(update_fields=['ultima_fecha_conexion', 'racha_dias'])

        cambio = services.actualizar_racha(self.usuario)

        self.usuario.refresh_from_db()
        self.assertTrue(cambio)
        self.assertEqual(self.usuario.racha_dias, 1)
        self.assertEqual(self.usuario.ultima_fecha_conexion, self.hoy)

    def test_conexion_ayer_incrementa_racha(self):
        self.usuario.ultima_fecha_conexion = self.hoy - timedelta(days=1)
        self.usuario.racha_dias = 4
        self.usuario.save(update_fields=['ultima_fecha_conexion', 'racha_dias'])

        cambio = services.actualizar_racha(self.usuario)

        self.usuario.refresh_from_db()
        self.assertTrue(cambio)
        self.assertEqual(self.usuario.racha_dias, 5)
        self.assertEqual(self.usuario.ultima_fecha_conexion, self.hoy)

    def test_salto_de_mas_de_un_dia_reinicia_racha_a_1(self):
        self.usuario.ultima_fecha_conexion = self.hoy - timedelta(days=5)
        self.usuario.racha_dias = 10
        self.usuario.save(update_fields=['ultima_fecha_conexion', 'racha_dias'])

        cambio = services.actualizar_racha(self.usuario)

        self.usuario.refresh_from_db()
        self.assertTrue(cambio)
        self.assertEqual(self.usuario.racha_dias, 1)
        self.assertEqual(self.usuario.ultima_fecha_conexion, self.hoy)

    def test_conexion_ya_registrada_hoy_no_cambia_nada(self):
        self.usuario.ultima_fecha_conexion = self.hoy
        self.usuario.racha_dias = 3
        self.usuario.save(update_fields=['ultima_fecha_conexion', 'racha_dias'])

        cambio = services.actualizar_racha(self.usuario)

        self.usuario.refresh_from_db()
        self.assertFalse(cambio)
        self.assertEqual(self.usuario.racha_dias, 3)
        self.assertEqual(self.usuario.ultima_fecha_conexion, self.hoy)


# ---------------------------------------------------------------------------
# Tests de `verificar_y_otorgar_insignias`
# ---------------------------------------------------------------------------
class VerificarYOtorgarInsigniasTests(TestCase):
    """Tests de `services.verificar_y_otorgar_insignias` en aislamiento.

    Se desconecta temporalmente el signal `post_save` de `ProgresoEstudiante`
    para probar la función de servicio de forma unitaria, sin que el propio
    signal otorgue la insignia antes de la llamada explícita. La integración
    signal -> servicio se cubre en `SignalProgresoEstudianteTests`.
    """

    def setUp(self):
        post_save.disconnect(manejar_progreso_guardado, sender=ProgresoEstudiante)

        self.usuario = UsuarioCustom.objects.create_user(
            username="insignia_user", password="claveSegura123",
        )
        self.nivel_1 = Nivel.objects.create(numero=1, titulo="Inicio", puntos_recompensa=50)
        self.nivel_2 = Nivel.objects.create(numero=2, titulo="Avanzado", puntos_recompensa=50)

        self.tipo_primer_nivel = TipoInsignia.objects.create(
            nombre="Primeros Pasos",
            descripcion="Completaste tu primer nivel.",
            criterio="primer_nivel",
            valor_umbral=1,
        )

    def tearDown(self):
        post_save.connect(manejar_progreso_guardado, sender=ProgresoEstudiante)

    def test_sin_progreso_no_otorga_insignias(self):
        insignias_nuevas = services.verificar_y_otorgar_insignias(self.usuario)

        self.assertEqual(insignias_nuevas, [])
        self.assertEqual(Insignia.objects.filter(usuario=self.usuario).count(), 0)

    def test_otorga_insignia_primer_nivel_al_cumplir_criterio(self):
        # El criterio 'primer_nivel' se cumple al completar 5 niveles en total.
        progreso = ProgresoEstudiante.objects.create(usuario=self.usuario)
        for i in range(5):
            nivel = Nivel.objects.create(numero=10 + i, titulo=f"Nivel {i}", puntos_recompensa=50)
            ProgresoNivel.objects.create(progreso=progreso, nivel=nivel, mejores_estrellas=2)

        insignias_nuevas = services.verificar_y_otorgar_insignias(self.usuario)

        self.assertEqual(len(insignias_nuevas), 1)
        self.assertEqual(insignias_nuevas[0].tipo_insignia, self.tipo_primer_nivel)
        self.assertFalse(insignias_nuevas[0].mostrada)
        self.assertTrue(
            Insignia.objects.filter(usuario=self.usuario, tipo_insignia=self.tipo_primer_nivel).exists()
        )

    def test_no_otorga_insignia_si_no_se_cumple_criterio(self):
        # Con menos de 5 niveles completados no se cumple 'primer_nivel'.
        progreso = ProgresoEstudiante.objects.create(usuario=self.usuario)
        for i in range(3):
            nivel = Nivel.objects.create(numero=10 + i, titulo=f"Nivel {i}", puntos_recompensa=50)
            ProgresoNivel.objects.create(progreso=progreso, nivel=nivel, mejores_estrellas=2)

        insignias_nuevas = services.verificar_y_otorgar_insignias(self.usuario)

        self.assertEqual(insignias_nuevas, [])
        self.assertEqual(Insignia.objects.filter(usuario=self.usuario).count(), 0)

    def test_no_duplica_insignia_ya_obtenida(self):
        progreso = ProgresoEstudiante.objects.create(usuario=self.usuario)
        for i in range(5):
            nivel = Nivel.objects.create(numero=10 + i, titulo=f"Nivel {i}", puntos_recompensa=50)
            ProgresoNivel.objects.create(progreso=progreso, nivel=nivel, mejores_estrellas=2)

        primera_pasada = services.verificar_y_otorgar_insignias(self.usuario)
        self.assertEqual(len(primera_pasada), 1)

        # Una segunda evaluación con el mismo progreso no debe crear duplicados.
        segunda_pasada = services.verificar_y_otorgar_insignias(self.usuario)

        self.assertEqual(segunda_pasada, [])
        self.assertEqual(
            Insignia.objects.filter(usuario=self.usuario, tipo_insignia=self.tipo_primer_nivel).count(),
            1,
        )


# ---------------------------------------------------------------------------
# Tests de `obtener_insignias_pendientes`
# ---------------------------------------------------------------------------
class ObtenerInsigniasPendientesTests(TestCase):
    """Tests de `services.obtener_insignias_pendientes`."""

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(
            username="pendientes_user", password="claveSegura123",
        )
        self.tipo = TipoInsignia.objects.create(
            nombre="Primeros Pasos",
            descripcion="Completaste tu primer nivel.",
            criterio="primer_nivel",
            valor_umbral=1,
        )

    def test_retorna_pendientes_y_las_marca_como_mostradas(self):
        insignia = Insignia.objects.create(usuario=self.usuario, tipo_insignia=self.tipo, mostrada=False)

        pendientes = services.obtener_insignias_pendientes(self.usuario)

        self.assertEqual(len(pendientes), 1)
        self.assertEqual(pendientes[0].pk, insignia.pk)

        insignia.refresh_from_db()
        self.assertTrue(insignia.mostrada)

    def test_segunda_llamada_no_retorna_insignias_ya_mostradas(self):
        Insignia.objects.create(usuario=self.usuario, tipo_insignia=self.tipo, mostrada=False)

        primera = services.obtener_insignias_pendientes(self.usuario)
        segunda = services.obtener_insignias_pendientes(self.usuario)

        self.assertEqual(len(primera), 1)
        self.assertEqual(segunda, [])

    def test_sin_insignias_pendientes_retorna_lista_vacia(self):
        pendientes = services.obtener_insignias_pendientes(self.usuario)
        self.assertEqual(pendientes, [])


# ---------------------------------------------------------------------------
# Tests del signal post_save de ProgresoEstudiante
# ---------------------------------------------------------------------------
class SignalProgresoEstudianteTests(TestCase):
    """Verifica que guardar `ProgresoEstudiante` dispare la verificación de insignias."""

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(
            username="signal_user", password="claveSegura123",
        )
        self.nivel_1 = Nivel.objects.create(numero=1, titulo="Inicio", puntos_recompensa=50)
        self.nivel_2 = Nivel.objects.create(numero=2, titulo="Avanzado", puntos_recompensa=50)

        self.tipo_primer_nivel = TipoInsignia.objects.create(
            nombre="Primeros Pasos",
            descripcion="Completaste tu primer nivel.",
            criterio="primer_nivel",
            valor_umbral=1,
        )

    def test_guardar_progreso_dispara_otorgamiento_de_insignia(self):
        progreso = ProgresoEstudiante.objects.create(usuario=self.usuario)

        # Sin ProgresoNivel aún no cumple el criterio.
        self.assertFalse(
            Insignia.objects.filter(usuario=self.usuario, tipo_insignia=self.tipo_primer_nivel).exists()
        )

        # Al agregar 5 ProgresoNivel y re-guardar el progreso, el signal
        # `post_save` -> `verificar_y_otorgar_insignias` debe otorgar la insignia.
        for i in range(5):
            nivel = Nivel.objects.create(numero=10 + i, titulo=f"Nivel {i}", puntos_recompensa=50)
            ProgresoNivel.objects.create(progreso=progreso, nivel=nivel, mejores_estrellas=2)
        progreso.save()

        self.assertTrue(
            Insignia.objects.filter(usuario=self.usuario, tipo_insignia=self.tipo_primer_nivel).exists()
        )

    def test_guardar_progreso_no_duplica_insignia_en_guardados_repetidos(self):
        progreso = ProgresoEstudiante.objects.create(usuario=self.usuario)
        for i in range(5):
            nivel = Nivel.objects.create(numero=10 + i, titulo=f"Nivel {i}", puntos_recompensa=50)
            ProgresoNivel.objects.create(progreso=progreso, nivel=nivel, mejores_estrellas=2)

        # El primer save() dispara el signal y otorga la insignia.
        progreso.save()
        self.assertEqual(
            Insignia.objects.filter(usuario=self.usuario, tipo_insignia=self.tipo_primer_nivel).count(),
            1,
        )

        # Guardados posteriores no deben crear duplicados.
        progreso.save()
        progreso.save()

        self.assertEqual(
            Insignia.objects.filter(usuario=self.usuario, tipo_insignia=self.tipo_primer_nivel).count(),
            1,
        )


# ---------------------------------------------------------------------------
# Tests del context processor `avatar_global`
# ---------------------------------------------------------------------------
class AvatarGlobalContextProcessorTests(TestCase):
    """Verifica las claves nuevas y existentes de `avatar.context_processors.avatar_global`."""

    def setUp(self):
        self.factory = RequestFactory()
        self.usuario = UsuarioCustom.objects.create_user(
            username="contexto_user", password="claveSegura123", monedas=15,
        )
        self.usuario.racha_dias = 3
        self.usuario.save(update_fields=['racha_dias'])

    def test_usuario_autenticado_incluye_claves_antiguas_y_nuevas(self):
        request = self.factory.get('/')
        request.user = self.usuario

        contexto = avatar_global(request)

        # Claves preexistentes que no deben eliminarse ni renombrarse.
        self.assertIn('avatar_user', contexto)
        self.assertIn('avatar_equipados', contexto)
        self.assertIn('reacciones_json', contexto)

        # Claves nuevas del Módulo B.
        self.assertIn('insignias_pendientes', contexto)
        self.assertIn('mascota_usuario', contexto)
        self.assertIn('monedas_usuario', contexto)
        self.assertIn('racha_dias', contexto)
        self.assertIn('evento_activo', contexto)

        self.assertEqual(contexto['monedas_usuario'], 15)
        self.assertEqual(contexto['racha_dias'], 3)
        self.assertIsNone(contexto['mascota_usuario'])
        self.assertIsNone(contexto['evento_activo'])
        self.assertEqual(list(contexto['insignias_pendientes']), [])

    def test_usuario_con_mascota_adoptada_aparece_en_contexto(self):
        mascota = Mascota.objects.create(nombre="Chispa", especie="dragon", precio_monedas=200)
        MascotaUsuario.objects.create(usuario=self.usuario, mascota=mascota)

        request = self.factory.get('/')
        request.user = self.usuario

        contexto = avatar_global(request)

        self.assertIsNotNone(contexto['mascota_usuario'])
        self.assertEqual(contexto['mascota_usuario'].mascota, mascota)

    def test_usuario_anonimo_no_falla_y_retorna_diccionario_vacio(self):
        from django.contrib.auth.models import AnonymousUser

        request = self.factory.get('/')
        request.user = AnonymousUser()

        contexto = avatar_global(request)

        self.assertEqual(contexto, {})


# ---------------------------------------------------------------------------
# Tests de la vista `insignias_pendientes_view` (Módulo K - Celebraciones)
# ---------------------------------------------------------------------------
class InsigniasPendientesVistaTests(TestCase):
    """Tests de `recompensas.views.insignias_pendientes_view`."""

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(
            username="celebracion_user", password="claveSegura123",
        )
        self.tipo = TipoInsignia.objects.create(
            nombre="Primeros Pasos",
            descripcion="Completaste tu primer nivel.",
            criterio="primer_nivel",
            valor_umbral=1,
        )
        self.url = '/recompensas/insignias-pendientes/'

    def test_usuario_con_insignias_pendientes_las_devuelve_y_las_marca_como_mostradas(self):
        insignia = Insignia.objects.create(usuario=self.usuario, tipo_insignia=self.tipo, mostrada=False)

        self.client.login(username="celebracion_user", password="claveSegura123")
        respuesta = self.client.post(self.url)

        self.assertEqual(respuesta.status_code, 200)
        datos = respuesta.json()
        self.assertEqual(len(datos['insignias']), 1)

        insignia_devuelta = datos['insignias'][0]
        self.assertEqual(insignia_devuelta['nombre'], self.tipo.nombre)
        self.assertEqual(insignia_devuelta['descripcion'], self.tipo.descripcion)
        self.assertEqual(insignia_devuelta['imagen'], '')

        insignia.refresh_from_db()
        self.assertTrue(insignia.mostrada)

    def test_usuario_sin_insignias_pendientes_devuelve_lista_vacia(self):
        self.client.login(username="celebracion_user", password="claveSegura123")
        respuesta = self.client.post(self.url)

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json(), {'insignias': []})

    def test_usuario_no_autenticado_redirige_a_login(self):
        respuesta = self.client.post(self.url)

        self.assertEqual(respuesta.status_code, 302)
        self.assertIn('/accounts/login/', respuesta.url)

    def test_metodo_get_no_permitido(self):
        self.client.login(username="celebracion_user", password="claveSegura123")
        respuesta = self.client.get(self.url)

        self.assertEqual(respuesta.status_code, 405)
