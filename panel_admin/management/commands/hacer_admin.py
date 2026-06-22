from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    """Marca un usuario existente como staff para que pueda entrar a /panel/.

    Uso: python manage.py hacer_admin correo@ejemplo.com

    El usuario tiene que existir ya (haber iniciado sesión al menos una vez
    con Google) — este comando no crea cuentas nuevas, solo activa el
    acceso al panel sobre una cuenta real ya existente.
    """

    help = 'Marca a un usuario existente como staff para que pueda entrar al panel de administración (/panel/).'

    def add_arguments(self, parser):
        parser.add_argument('correo', help='Correo del usuario a convertir en administrador del panel.')
        parser.add_argument(
            '--quitar', action='store_true',
            help='En vez de otorgar el acceso, lo revoca (is_staff=False).',
        )

    def handle(self, *args, **opciones):
        Usuario = get_user_model()
        correo = opciones['correo']

        try:
            usuario = Usuario.objects.get(email=correo)
        except Usuario.DoesNotExist:
            raise CommandError(
                f"No existe ningún usuario con el correo '{correo}'. "
                'Iniciá sesión una vez en la app con ese correo (Google) antes de correr este comando.'
            )

        nuevo_valor = not opciones['quitar']

        if usuario.is_staff == nuevo_valor:
            estado = 'ya es' if nuevo_valor else 'ya no es'
            self.stdout.write(self.style.WARNING(f'{correo} {estado} administrador del panel.'))
            return

        usuario.is_staff = nuevo_valor
        usuario.save(update_fields=['is_staff'])

        if nuevo_valor:
            self.stdout.write(self.style.SUCCESS(f'{correo} ahora puede entrar a /panel/.'))
        else:
            self.stdout.write(self.style.SUCCESS(f'{correo} ya no tiene acceso a /panel/.'))
