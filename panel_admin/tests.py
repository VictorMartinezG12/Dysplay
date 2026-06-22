from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from avatar.models import CaraAvatar, Item
from camara_inteligente.models import ConfiguracionCamara
from estadisticas.models import RegistroActividad
from recompensas.models import TipoInsignia

Usuario = get_user_model()


class PanelHomeViewTests(TestCase):
    """Fase 0: el panel debe responder 404 a cualquiera que no sea staff,
    sin importar si está logueado, y servir el contenido a quien sí lo es."""

    def setUp(self):
        self.url = reverse('panel_admin:home')
        self.usuario_normal = Usuario.objects.create_user(
            username='estudiante', password='clave12345'
        )
        self.usuario_staff = Usuario.objects.create_user(
            username='admin_dysplay', password='clave12345', is_staff=True
        )

    def test_usuario_anonimo_recibe_404(self):
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.status_code, 404)

    def test_usuario_normal_recibe_404(self):
        self.client.force_login(self.usuario_normal)
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.status_code, 404)

    def test_usuario_staff_accede_al_panel(self):
        self.client.force_login(self.usuario_staff)
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Panel de administración')

    def test_link_del_panel_visible_solo_para_staff(self):
        self.client.force_login(self.usuario_staff)
        respuesta = self.client.get(reverse('home'))
        self.assertContains(respuesta, reverse('panel_admin:home'))

        self.client.force_login(self.usuario_normal)
        respuesta = self.client.get(reverse('home'))
        self.assertNotContains(respuesta, reverse('panel_admin:home'))


class RecursoCrudGenericoTests(TestCase):
    """Fase 1: CRUD genérico sobre un modelo de catálogo simple (TipoInsignia)."""

    def setUp(self):
        self.usuario_staff = Usuario.objects.create_user(
            username='admin_dysplay', password='clave12345', is_staff=True
        )
        self.client.force_login(self.usuario_staff)

    def test_lista_responde_ok(self):
        # Nota: recompensas.0003 ya siembra un TipoInsignia ("Aventurero Diario"),
        # así que la lista no necesariamente está vacía en este punto.
        respuesta = self.client.get(reverse('panel_admin:lista', args=['insignias-tipo']))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Tipos de insignia')

    def test_crear_tipo_insignia(self):
        respuesta = self.client.post(reverse('panel_admin:crear', args=['insignias-tipo']), {
            'nombre': 'Primer nivel completado',
            'descripcion': '',
            'criterio': 'primer_nivel',
            'valor_umbral': 1,
        })
        self.assertEqual(respuesta.status_code, 302)
        self.assertTrue(TipoInsignia.objects.filter(nombre='Primer nivel completado').exists())

    def test_editar_tipo_insignia(self):
        tipo = TipoInsignia.objects.create(nombre='Vieja', criterio='primer_nivel', valor_umbral=1)
        respuesta = self.client.post(
            reverse('panel_admin:editar', args=['insignias-tipo', tipo.pk]),
            {'nombre': 'Nueva', 'descripcion': '', 'criterio': 'racha_7', 'valor_umbral': 7},
        )
        self.assertEqual(respuesta.status_code, 302)
        tipo.refresh_from_db()
        self.assertEqual(tipo.nombre, 'Nueva')

    def test_eliminar_tipo_insignia(self):
        tipo = TipoInsignia.objects.create(nombre='Borrar', criterio='primer_nivel', valor_umbral=1)
        respuesta = self.client.post(reverse('panel_admin:eliminar', args=['insignias-tipo', tipo.pk]))
        self.assertEqual(respuesta.status_code, 302)
        self.assertFalse(TipoInsignia.objects.filter(pk=tipo.pk).exists())

    def test_recurso_inexistente_da_404(self):
        respuesta = self.client.get(reverse('panel_admin:lista', args=['no-existe']))
        self.assertEqual(respuesta.status_code, 404)


class RecursoSingletonTests(TestCase):
    """Fase 1: un recurso singleton (ConfiguracionCamara) no tiene lista ni alta."""

    def setUp(self):
        self.usuario_staff = Usuario.objects.create_user(
            username='admin_dysplay', password='clave12345', is_staff=True
        )
        self.client.force_login(self.usuario_staff)

    def test_lista_redirige_a_editar_y_crea_el_registro_si_falta(self):
        self.assertFalse(ConfiguracionCamara.objects.exists())
        respuesta = self.client.get(reverse('panel_admin:lista', args=['config-camara']))
        self.assertEqual(respuesta.status_code, 302)
        self.assertTrue(ConfiguracionCamara.objects.filter(pk=1).exists())

    def test_no_se_puede_crear_un_segundo_singleton(self):
        respuesta = self.client.get(reverse('panel_admin:crear', args=['config-camara']))
        self.assertEqual(respuesta.status_code, 404)


class RecursoSoloLecturaTests(TestCase):
    """Fase 1: un recurso de solo lectura (RegistroActividad) no tiene alta/edición/borrado."""

    def setUp(self):
        self.usuario_staff = Usuario.objects.create_user(
            username='admin_dysplay', password='clave12345', is_staff=True
        )
        self.estudiante = Usuario.objects.create_user(username='estudiante2', password='clave12345')
        self.registro = RegistroActividad.objects.create(
            usuario=self.estudiante, tipo_actividad='nivel', score=90.0,
        )
        self.client.force_login(self.usuario_staff)

    def test_lista_no_muestra_boton_nuevo(self):
        respuesta = self.client.get(reverse('panel_admin:lista', args=['registros-actividad']))
        self.assertEqual(respuesta.status_code, 200)
        self.assertNotContains(respuesta, '+ Nuevo')

    def test_crear_da_404(self):
        respuesta = self.client.get(reverse('panel_admin:crear', args=['registros-actividad']))
        self.assertEqual(respuesta.status_code, 404)

    def test_eliminar_da_404(self):
        respuesta = self.client.get(
            reverse('panel_admin:eliminar', args=['registros-actividad', self.registro.pk])
        )
        self.assertEqual(respuesta.status_code, 404)


# PNG válido de 1x1 píxel transparente, en base64 — Django's ImageField valida
# el contenido real del archivo (vía Pillow), no basta con bytes arbitrarios.
import base64

from django.core.files.uploadedfile import SimpleUploadedFile

_PNG_1X1 = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
)


def _imagen_de_prueba(nombre='prueba.png'):
    return SimpleUploadedFile(nombre, _PNG_1X1, content_type='image/png')


class AvatarItemFormTests(TestCase):
    """Fase 2: formulario a medida de Item con previsualización en vivo."""

    def setUp(self):
        self.usuario_staff = Usuario.objects.create_user(
            username='admin_dysplay', password='clave12345', is_staff=True
        )
        self.client.force_login(self.usuario_staff)

    def test_formulario_usa_template_a_medida(self):
        respuesta = self.client.get(reverse('panel_admin:crear', args=['items-avatar']))
        self.assertEqual(respuesta.status_code, 200)
        self.assertTemplateUsed(respuesta, 'panel_admin/avatar_item_form.html')
        self.assertContains(respuesta, 'Vista previa en vivo')

    def test_crear_item_sin_mangas(self):
        respuesta = self.client.post(reverse('panel_admin:crear', args=['items-avatar']), {
            'nombre': 'Gorro de prueba',
            'categoria': 'accesorio',
            'descripcion': '',
            'activo': 'on',
            'precio_monedas': 50,
            'imagen': _imagen_de_prueba(),
        })
        self.assertEqual(respuesta.status_code, 302)
        self.assertTrue(Item.objects.filter(nombre='Gorro de prueba').exists())

    def test_crear_item_con_mangas(self):
        respuesta = self.client.post(reverse('panel_admin:crear', args=['items-avatar']), {
            'nombre': 'Chaqueta de prueba',
            'categoria': 'ropa_superior',
            'descripcion': '',
            'activo': 'on',
            'precio_monedas': 80,
            'imagen': _imagen_de_prueba('torso.png'),
            'manga_sup_izq': _imagen_de_prueba('m1.png'),
            'manga_inf_izq': _imagen_de_prueba('m2.png'),
            'manga_sup_der': _imagen_de_prueba('m3.png'),
            'manga_inf_der': _imagen_de_prueba('m4.png'),
        })
        self.assertEqual(respuesta.status_code, 302)
        item = Item.objects.get(nombre='Chaqueta de prueba')
        self.assertEqual(len(item.mangas_urls), 4)


class AvatarCaraFormTests(TestCase):
    """Fase 2: formulario a medida de CaraAvatar."""

    def setUp(self):
        self.usuario_staff = Usuario.objects.create_user(
            username='admin_dysplay', password='clave12345', is_staff=True
        )
        self.client.force_login(self.usuario_staff)

    def test_formulario_usa_template_a_medida(self):
        respuesta = self.client.get(reverse('panel_admin:crear', args=['caras-avatar']))
        self.assertEqual(respuesta.status_code, 200)
        self.assertTemplateUsed(respuesta, 'panel_admin/avatar_cara_form.html')

    def test_crear_cara_neutral(self):
        respuesta = self.client.post(reverse('panel_admin:crear', args=['caras-avatar']), {
            'estado': 'neutral',
            'imagen': _imagen_de_prueba(),
        })
        self.assertEqual(respuesta.status_code, 302)
        self.assertTrue(CaraAvatar.objects.filter(estado='neutral').exists())

    def test_no_se_puede_repetir_estado(self):
        CaraAvatar.objects.create(estado='feliz', imagen=_imagen_de_prueba())
        respuesta = self.client.post(reverse('panel_admin:crear', args=['caras-avatar']), {
            'estado': 'feliz',
            'imagen': _imagen_de_prueba('otra.png'),
        })
        # El form rechaza el duplicado (unique=True) y vuelve a mostrar la página, no redirige.
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(CaraAvatar.objects.filter(estado='feliz').count(), 1)

    def test_editar_cara_sin_parpadeo_no_revienta(self):
        # Bug real encontrado en la Fase 3: object.imagen_parpadeo.url explota
        # con ValueError si el campo está vacío; el template debe protegerlo.
        cara = CaraAvatar.objects.create(estado='triste', imagen=_imagen_de_prueba())
        respuesta = self.client.get(reverse('panel_admin:editar', args=['caras-avatar', cara.pk]))
        self.assertEqual(respuesta.status_code, 200)


class CarasAvatarTemplateTagTests(TestCase):
    """Fase 2: el templatetag que alimenta _svg_personaje.html con las caras reales."""

    def setUp(self):
        self.usuario = Usuario.objects.create_user(username='estudiante3', password='clave12345')

    def test_sin_filas_usa_respaldo_estatico(self):
        self.client.force_login(self.usuario)
        respuesta = self.client.get(reverse('home'))
        self.assertContains(respuesta, 'avatar/cuerpo/caras/feliz_1.svg')

    def test_con_fila_neutral_se_usa_como_respaldo_de_otras_emociones(self):
        CaraAvatar.objects.create(estado='neutral', imagen=_imagen_de_prueba('neutral.png'))
        self.client.force_login(self.usuario)
        respuesta = self.client.get(reverse('home'))
        # 'triste' no tiene fila propia: debe heredar la imagen de 'neutral'.
        self.assertContains(respuesta, 'dp-cara-triste')
        self.assertContains(respuesta, 'neutral')


class HacerAdminCommandTests(TestCase):
    """Fase 3: comando de gestión para otorgar/quitar acceso al panel."""

    def setUp(self):
        self.usuario = Usuario.objects.create_user(
            username='futuro_admin', email='futuro_admin@dysplay.com', password='clave12345',
        )

    def test_otorga_acceso(self):
        from django.core.management import call_command
        self.assertFalse(self.usuario.is_staff)
        call_command('hacer_admin', 'futuro_admin@dysplay.com')
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.is_staff)

    def test_quita_acceso(self):
        from django.core.management import call_command
        self.usuario.is_staff = True
        self.usuario.save()
        call_command('hacer_admin', 'futuro_admin@dysplay.com', '--quitar')
        self.usuario.refresh_from_db()
        self.assertFalse(self.usuario.is_staff)

    def test_correo_inexistente_da_error_claro(self):
        from django.core.management import CommandError, call_command
        with self.assertRaises(CommandError):
            call_command('hacer_admin', 'no-existe@dysplay.com')
