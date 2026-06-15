from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from . import services
from .models import ReporteEnviado

UsuarioCustom = get_user_model()


# ---------------------------------------------------------------------------
# Tests del modelo `ReporteEnviado`
# ---------------------------------------------------------------------------
class ModeloReporteEnviadoTests(TestCase):
    """Tests básicos del modelo `ReporteEnviado`."""

    def test_creacion_y_str(self):
        usuario = UsuarioCustom.objects.create_user(username='estudiante1', password='clave123')

        reporte = ReporteEnviado.objects.create(
            usuario=usuario,
            correo_destino='tutor@example.com',
            tipo_envio=ReporteEnviado.TIPO_MANUAL,
        )

        self.assertTrue(reporte.exitoso)
        self.assertEqual(reporte.tipo_envio, ReporteEnviado.TIPO_MANUAL)
        self.assertIn('tutor@example.com', str(reporte))


# ---------------------------------------------------------------------------
# Tests del servicio `enviar_reporte_progreso`
# ---------------------------------------------------------------------------
class EnviarReporteProgresoTests(TestCase):
    """Tests del servicio de envío del reporte de progreso por correo."""

    def test_sin_correo_tutor_no_envia_nada(self):
        usuario = UsuarioCustom.objects.create_user(
            username='estudiante_sin_correo', password='clave123', correo_tutor='',
        )

        resultado = services.enviar_reporte_progreso(usuario, ReporteEnviado.TIPO_MANUAL)

        self.assertEqual(resultado['status'], 'sin_correo')
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(ReporteEnviado.objects.count(), 0)

    def test_con_correo_tutor_envia_email_y_registra(self):
        usuario = UsuarioCustom.objects.create_user(
            username='estudiante_con_correo', password='clave123', correo_tutor='tutor@example.com',
        )

        resultado = services.enviar_reporte_progreso(usuario, ReporteEnviado.TIPO_MANUAL)

        self.assertEqual(resultado['status'], 'success')
        self.assertEqual(len(mail.outbox), 1)

        correo_enviado = mail.outbox[0]
        self.assertEqual(correo_enviado.to, ['tutor@example.com'])
        self.assertTrue(any(tipo == 'text/html' for _contenido, tipo in correo_enviado.alternatives))

        reporte = ReporteEnviado.objects.get()
        self.assertTrue(reporte.exitoso)
        self.assertEqual(reporte.correo_destino, 'tutor@example.com')
        self.assertEqual(reporte.tipo_envio, ReporteEnviado.TIPO_MANUAL)


# ---------------------------------------------------------------------------
# Tests de la vista `enviar_reporte_view`
# ---------------------------------------------------------------------------
class EnviarReporteViewTests(TestCase):
    """Tests de la vista que envía el reporte manualmente."""

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(
            username='estudiante_vista', password='clave123', correo_tutor='tutor@example.com',
        )
        self.url = reverse('reportes:enviar')

    def test_requiere_login(self):
        respuesta = self.client.post(self.url)
        self.assertNotEqual(respuesta.status_code, 200)
        self.assertIn('/accounts/login', respuesta.url)

    def test_post_autenticado_redirige_con_resultado_exitoso(self):
        self.client.force_login(self.usuario)

        respuesta = self.client.post(self.url)

        url_esperada = reverse('estadisticas')
        self.assertRedirects(respuesta, f"{url_esperada}?reporte=success")
        self.assertEqual(len(mail.outbox), 1)


# ---------------------------------------------------------------------------
# Tests del management command de envío en lote
# ---------------------------------------------------------------------------
class EnviarReportesProgresoCommandTests(TestCase):
    """Tests del comando `enviar_reportes_progreso`."""

    def test_solo_envia_a_usuarios_con_correo_tutor(self):
        UsuarioCustom.objects.create_user(
            username='con_correo', password='clave123', correo_tutor='tutor@example.com',
        )
        UsuarioCustom.objects.create_user(
            username='sin_correo', password='clave123', correo_tutor='',
        )

        call_command('enviar_reportes_progreso')

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(ReporteEnviado.objects.count(), 1)
