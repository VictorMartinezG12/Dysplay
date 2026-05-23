from django.contrib.auth.models import AbstractUser
from django.db import models


class UsuarioCustom(AbstractUser):
    es_estudiante = models.BooleanField(default=True)
    es_padre = models.BooleanField(default=False)
    es_profesor = models.BooleanField(default=False)

    monedas = models.IntegerField(default=0)
    racha_dias = models.IntegerField(default=0)
    ultima_fecha_conexion = models.DateField(null=True, blank=True)

    correo_tutor = models.EmailField(
        max_length=254,
        blank=True,
        null=True,
        help_text="Correo del tutor para reportes automatizados."
    )

    def __str__(self):
        return self.username

