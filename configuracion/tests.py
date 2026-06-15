from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import ConfiguracionGlobal

UsuarioCustom = get_user_model()


class ConfiguracionGlobalModeloTest(TestCase):
    """Pruebas del modelo `ConfiguracionGlobal`."""

    def test_se_crea_con_valores_por_defecto(self):
        """Al crear una configuración para un usuario, los campos deben tomar sus defaults."""
        usuario = UsuarioCustom.objects.create_user(username="estudiante_config", password="claveSegura123")
        config = ConfiguracionGlobal.objects.create(usuario=usuario)

        self.assertEqual(config.tipo_fuente, 'Lexend')
        self.assertEqual(config.tamano_fuente, 'normal')
        self.assertEqual(config.espaciado_letras, 'normal')
        self.assertEqual(config.espaciado_palabras, 'normal')
        self.assertEqual(config.tema_visual, 'infantil-azul')
        self.assertEqual(config.velocidad_narracion, 'normal')
        self.assertEqual(config.tipo_voz, 'nino')
        self.assertEqual(config.volumen_narracion, 80)
        self.assertEqual(config.volumen_musica, 50)


class VerConfiguracionVistaTest(TestCase):
    """Pruebas de la vista `configuracion:ver` (GET)."""

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(username="estudiante_vista", password="claveSegura123")

    def test_requiere_login(self):
        """Un usuario anónimo debe ser redirigido al intentar ver la configuración."""
        respuesta = self.client.get(reverse('configuracion:ver'))
        self.assertNotEqual(respuesta.status_code, 200)

    def test_usuario_autenticado_puede_ver_panel(self):
        """Un usuario autenticado puede acceder al panel de configuración y ve el formulario."""
        self.client.login(username="estudiante_vista", password="claveSegura123")
        respuesta = self.client.get(reverse('configuracion:ver'))

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, '<form')
        self.assertContains(respuesta, 'tema_visual')


class GuardarConfiguracionVistaTest(TestCase):
    """Pruebas de la vista `configuracion:ver` (POST) y de `services.guardar_configuracion`."""

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(username="estudiante_post", password="claveSegura123")
        self.client.login(username="estudiante_post", password="claveSegura123")

    def test_post_guarda_los_campos_de_accesibilidad(self):
        """Un POST válido con los 9 campos + correo_tutor actualiza ConfiguracionGlobal y el usuario."""
        datos = {
            'tipo_fuente': 'OpenDyslexic',
            'tamano_fuente': 'grande',
            'espaciado_letras': 'amplio',
            'espaciado_palabras': 'medio',
            'tema_visual': 'oscuro',
            'velocidad_narracion': 'lenta',
            'tipo_voz': 'nina',
            'volumen_narracion': '60',
            'volumen_musica': '30',
            'correo_tutor': 'tutor@example.com',
        }

        respuesta = self.client.post(reverse('configuracion:ver'), datos)
        self.assertEqual(respuesta.status_code, 302)

        config = ConfiguracionGlobal.objects.get(usuario=self.usuario)
        self.assertEqual(config.tipo_fuente, 'OpenDyslexic')
        self.assertEqual(config.tamano_fuente, 'grande')
        self.assertEqual(config.espaciado_letras, 'amplio')
        self.assertEqual(config.espaciado_palabras, 'medio')
        self.assertEqual(config.tema_visual, 'oscuro')
        self.assertEqual(config.velocidad_narracion, 'lenta')
        self.assertEqual(config.tipo_voz, 'nina')
        self.assertEqual(config.volumen_narracion, 60)
        self.assertEqual(config.volumen_musica, 30)

        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.correo_tutor, 'tutor@example.com')

    def test_volumen_fuera_de_rango_se_acota_y_choice_invalido_se_conserva(self):
        """volumen_narracion > 100 se acota a 100 y un tema_visual inválido conserva el valor previo."""
        config_inicial = ConfiguracionGlobal.objects.create(
            usuario=self.usuario,
            tema_visual='infantil-verde',
        )

        datos = {
            'tipo_fuente': 'Lexend',
            'tamano_fuente': 'normal',
            'espaciado_letras': 'normal',
            'espaciado_palabras': 'normal',
            'tema_visual': 'tema_que_no_existe',
            'velocidad_narracion': 'normal',
            'tipo_voz': 'nino',
            'volumen_narracion': '150',
            'volumen_musica': '50',
        }

        self.client.post(reverse('configuracion:ver'), datos)

        config_inicial.refresh_from_db()
        self.assertEqual(config_inicial.volumen_narracion, 100)
        self.assertEqual(config_inicial.tema_visual, 'infantil-verde')
