from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Avatar, CasaAvatar, InventarioAvatar, Item
from .reactions import REACCIONES, obtener_reaccion
from .services import (
    ItemYaPoseidoError,
    SlotInvalidoError,
    colocar_item_en_casa,
    comprar_item_para_avatar,
    obtener_items_tienda_casa,
    obtener_o_crear_casa,
)
from recompensas.services import SaldoInsuficienteError

UsuarioCustom = get_user_model()


class AvatarModelTests(TestCase):
    """Tests para los modelos extendidos/nuevos del Módulo C (C.1)."""

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(
            username='estudiante1', password='claveSegura123'
        )

    def test_avatar_valores_por_defecto_frase_y_personalidad(self):
        avatar = Avatar.objects.create(usuario=self.usuario)
        self.assertEqual(avatar.frase_bienvenida, '')
        self.assertEqual(avatar.personalidad, 'animado')

    def test_item_categorias_habitacion_y_fondo_disponibles(self):
        item_habitacion = Item.objects.create(
            nombre='Cama acogedora', categoria='habitacion', precio_monedas=50
        )
        item_fondo = Item.objects.create(
            nombre='Fondo de bosque', categoria='fondo', precio_monedas=30
        )
        self.assertEqual(item_habitacion.categoria, 'habitacion')
        self.assertEqual(item_fondo.categoria, 'fondo')
        self.assertEqual(item_habitacion.precio_monedas, 50)
        self.assertIsNone(item_habitacion.evento_especial)

    def test_casa_avatar_se_crea_con_slots_vacios(self):
        avatar = Avatar.objects.create(usuario=self.usuario)
        casa = CasaAvatar.objects.create(avatar=avatar)
        self.assertIsNone(casa.cama)
        self.assertIsNone(casa.cuadro)
        self.assertIsNone(casa.alfombra)
        self.assertIsNone(casa.lampara)
        self.assertEqual(str(casa), f"Casa de {self.usuario.username}")

    def test_casa_avatar_relacion_one_to_one_con_avatar(self):
        avatar = Avatar.objects.create(usuario=self.usuario)
        casa = obtener_o_crear_casa(avatar)
        self.assertEqual(avatar.casa, casa)
        # Llamar de nuevo no debe crear una segunda casa.
        casa_obtenida_de_nuevo = obtener_o_crear_casa(avatar)
        self.assertEqual(casa.pk, casa_obtenida_de_nuevo.pk)
        self.assertEqual(CasaAvatar.objects.filter(avatar=avatar).count(), 1)


class ReactionsTests(TestCase):
    """Tests para el catálogo de reacciones (C.2)."""

    def test_reacciones_contiene_los_siete_tipos_esperados(self):
        tipos_esperados = {
            'pronunciacion_correcta',
            'pronunciacion_incorrecta',
            'nivel_completado',
            'racha_activa',
            'insignia_nueva',
            'bienvenida_diaria',
            'historia_completada',
        }
        self.assertEqual(set(REACCIONES.keys()), tipos_esperados)

    def test_obtener_reaccion_devuelve_frase_valida(self):
        frase = obtener_reaccion('nivel_completado')
        self.assertIn(frase, REACCIONES['nivel_completado'])

    def test_obtener_reaccion_tipo_inexistente_devuelve_none(self):
        self.assertIsNone(obtener_reaccion('evento_que_no_existe'))

    def test_obtener_reaccion_formatea_placeholders(self):
        frase = obtener_reaccion('racha_activa', dias=5)
        self.assertIn('5', frase)
        self.assertNotIn('{dias}', frase)


class AvatarServicesTests(TestCase):
    """Tests para la lógica de negocio de la casa del avatar (C.3)."""

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(
            username='comprador', password='claveSegura123', monedas=100
        )
        self.avatar = Avatar.objects.create(usuario=self.usuario)
        self.item_cama = Item.objects.create(
            nombre='Cama de nubes',
            categoria='habitacion',
            precio_monedas=40,
            activo=True,
        )
        self.item_fondo = Item.objects.create(
            nombre='Fondo estrellado',
            categoria='fondo',
            precio_monedas=200,
            activo=True,
        )

    def test_comprar_item_descuenta_monedas_y_desbloquea_item(self):
        inventario = comprar_item_para_avatar(
            self.usuario, self.avatar, self.item_cama.id
        )

        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.monedas, 60)
        self.assertTrue(inventario.desbloqueado)
        self.assertTrue(
            InventarioAvatar.objects.filter(
                avatar=self.avatar, item=self.item_cama, desbloqueado=True
            ).exists()
        )

    def test_comprar_item_con_slot_lo_coloca_en_la_casa(self):
        comprar_item_para_avatar(
            self.usuario, self.avatar, self.item_cama.id, slot='cama'
        )
        casa = obtener_o_crear_casa(self.avatar)
        self.assertEqual(casa.cama_id, self.item_cama.id)

    def test_comprar_item_saldo_insuficiente_no_modifica_nada(self):
        with self.assertRaises(SaldoInsuficienteError):
            comprar_item_para_avatar(
                self.usuario, self.avatar, self.item_fondo.id
            )

        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.monedas, 100)
        self.assertFalse(
            InventarioAvatar.objects.filter(
                avatar=self.avatar, item=self.item_fondo
            ).exists()
        )

    def test_comprar_item_ya_poseido_lanza_error(self):
        comprar_item_para_avatar(self.usuario, self.avatar, self.item_cama.id)

        with self.assertRaises(ItemYaPoseidoError):
            comprar_item_para_avatar(self.usuario, self.avatar, self.item_cama.id)

    def test_comprar_item_slot_invalido_lanza_error(self):
        with self.assertRaises(SlotInvalidoError):
            comprar_item_para_avatar(
                self.usuario, self.avatar, self.item_cama.id, slot='ventana'
            )

    def test_colocar_item_en_casa_sin_cobrar(self):
        InventarioAvatar.objects.create(
            avatar=self.avatar, item=self.item_cama, desbloqueado=True
        )

        casa = colocar_item_en_casa(self.avatar, self.item_cama.id, 'cama')

        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.monedas, 100)  # No se cobró nada.
        self.assertEqual(casa.cama_id, self.item_cama.id)

    def test_colocar_item_no_poseido_lanza_error(self):
        with self.assertRaises(InventarioAvatar.DoesNotExist):
            colocar_item_en_casa(self.avatar, self.item_cama.id, 'cama')

    def test_obtener_items_tienda_casa_excluye_poseidos(self):
        items_tienda = obtener_items_tienda_casa(self.avatar)
        self.assertIn(self.item_cama, items_tienda)
        self.assertIn(self.item_fondo, items_tienda)

        comprar_item_para_avatar(self.usuario, self.avatar, self.item_cama.id)

        items_tienda = obtener_items_tienda_casa(self.avatar)
        self.assertNotIn(self.item_cama, items_tienda)
        self.assertIn(self.item_fondo, items_tienda)

    def test_obtener_items_tienda_casa_solo_incluye_categorias_casa(self):
        Item.objects.create(
            nombre='Sombrero', categoria='accesorio', precio_monedas=10, activo=True
        )
        items_tienda = obtener_items_tienda_casa(self.avatar)
        categorias = {item.categoria for item in items_tienda}
        self.assertTrue(categorias.issubset({'habitacion', 'fondo'}))


class CasaAvatarViewsTests(TestCase):
    """Tests para las vistas de la casa del avatar (login_required y manejo de errores)."""

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(
            username='visitante', password='claveSegura123', monedas=100
        )
        self.avatar = Avatar.objects.create(usuario=self.usuario)
        self.item_cama = Item.objects.create(
            nombre='Cama de nubes',
            categoria='habitacion',
            precio_monedas=40,
            activo=True,
        )

    def test_casa_avatar_requiere_login(self):
        url = reverse('avatar:casa')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

    def test_casa_avatar_renderiza_para_usuario_autenticado(self):
        self.client.force_login(self.usuario)
        response = self.client.get(reverse('avatar:casa'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'avatar/casa.html')
        self.assertIn('casa', response.context)
        self.assertIn('items_tienda', response.context)
        self.assertIn('items_disponibles', response.context)

    def test_comprar_item_requiere_login(self):
        url = reverse('avatar:comprar_item')
        response = self.client.post(url, {'item_id': self.item_cama.id})
        self.assertEqual(response.status_code, 302)

    def test_comprar_item_exitoso(self):
        self.client.force_login(self.usuario)
        url = reverse('avatar:comprar_item')
        response = self.client.post(url, {'item_id': self.item_cama.id})
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertTrue(data['exito'])
        self.assertEqual(data['monedas'], 60)

    def test_comprar_item_inexistente_no_expone_excepcion_interna(self):
        self.client.force_login(self.usuario)
        url = reverse('avatar:comprar_item')
        response = self.client.post(url, {'item_id': 999999})

        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertFalse(data['exito'])
        # El mensaje debe ser amigable, sin texto de excepción de Python.
        self.assertNotIn('DoesNotExist', data['mensaje'])
        self.assertNotIn('Traceback', data['mensaje'])

    def test_comprar_item_saldo_insuficiente_responde_400_sin_exponer_error(self):
        item_caro = Item.objects.create(
            nombre='Trono dorado', categoria='habitacion', precio_monedas=99999, activo=True
        )
        self.client.force_login(self.usuario)
        url = reverse('avatar:comprar_item')
        response = self.client.post(url, {'item_id': item_caro.id})

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['exito'])
        self.assertNotIn('SaldoInsuficienteError', data['mensaje'])

    def test_comprar_item_sin_item_id_responde_400(self):
        self.client.force_login(self.usuario)
        url = reverse('avatar:comprar_item')
        response = self.client.post(url, {})

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['exito'])

    def test_colocar_item_requiere_login(self):
        url = reverse('avatar:colocar_item')
        response = self.client.post(url, {'item_id': self.item_cama.id, 'slot': 'cama'})
        self.assertEqual(response.status_code, 302)

    def test_colocar_item_no_poseido_responde_400_sin_exponer_error(self):
        self.client.force_login(self.usuario)
        url = reverse('avatar:colocar_item')
        response = self.client.post(url, {'item_id': self.item_cama.id, 'slot': 'cama'})

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['exito'])
        self.assertNotIn('DoesNotExist', data['mensaje'])

    def test_colocar_item_exitoso_tras_compra(self):
        comprar_item_para_avatar(self.usuario, self.avatar, self.item_cama.id)

        self.client.force_login(self.usuario)
        url = reverse('avatar:colocar_item')
        response = self.client.post(
            url, {'item_id': self.item_cama.id, 'slot': 'cama'}
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['exito'])

        casa = CasaAvatar.objects.get(avatar=self.avatar)
        self.assertEqual(casa.cama_id, self.item_cama.id)

    def test_colocar_item_slot_invalido_responde_400(self):
        comprar_item_para_avatar(self.usuario, self.avatar, self.item_cama.id)

        self.client.force_login(self.usuario)
        url = reverse('avatar:colocar_item')
        response = self.client.post(
            url, {'item_id': self.item_cama.id, 'slot': 'ventana'}
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['exito'])


class AvatarContextProcessorTests(TestCase):
    """Tests para la nueva clave `avatar_frase_contextual` del context processor (C.2)."""

    def setUp(self):
        self.usuario = UsuarioCustom.objects.create_user(
            username='lector', password='claveSegura123'
        )

    def test_frase_contextual_usa_frase_personalizada_si_existe(self):
        Avatar.objects.create(
            usuario=self.usuario, frase_bienvenida='¡Hola, campeón personalizado!'
        )
        self.client.force_login(self.usuario)
        response = self.client.get(reverse('avatar:personalizar'))

        self.assertEqual(
            response.context['avatar_frase_contextual'],
            '¡Hola, campeón personalizado!',
        )

    def test_frase_contextual_usa_reaccion_aleatoria_si_no_hay_personalizada(self):
        Avatar.objects.create(usuario=self.usuario)
        self.client.force_login(self.usuario)
        response = self.client.get(reverse('avatar:personalizar'))

        self.assertIn(
            response.context['avatar_frase_contextual'],
            REACCIONES['bienvenida_diaria'],
        )

    def test_base_template_incluye_scripts_de_avatar(self):
        Avatar.objects.create(usuario=self.usuario)
        self.client.force_login(self.usuario)
        response = self.client.get(reverse('avatar:personalizar'))

        contenido = response.content.decode()
        self.assertIn('id="avatar-reacciones-data"', contenido)
        self.assertIn('id="avatar-frase-contextual-data"', contenido)
