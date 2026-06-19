from django.db import models
from django.conf import settings

class ConfiguracionGlobal(models.Model):
    # Relación con el usuario
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='configuracion'
    )

    # --- ACCESIBILIDAD Y PREFERENCIAS VISUALES ---
    TIPO_FUENTE_CHOICES = [
        ('OpenDyslexic', 'OpenDyslexic'),
        ('Lexend', 'Lexend'),
        ('Arial', 'Arial'),
        ('Verdana', 'Verdana'),
    ]
    tipo_fuente = models.CharField(
        max_length=50,
        choices=TIPO_FUENTE_CHOICES,
        default='Lexend'
    )

    TAMANO_FUENTE_CHOICES = [
        ('pequeno', 'Pequeño'),
        ('normal', 'Normal'),
        ('grande', 'Grande'),
        ('extra-grande', 'Extra Grande'),
    ]
    tamano_fuente = models.CharField(
        max_length=20,
        choices=TAMANO_FUENTE_CHOICES,
        default='normal'
    )

    ESPACIADO_CHOICES = [
        ('normal', 'Normal'),
        ('medio', 'Medio'),
        ('amplio', 'Amplio'),
    ]
    espaciado_letras = models.CharField(
        max_length=20,
        choices=ESPACIADO_CHOICES,
        default='normal'
    )
    espaciado_palabras = models.CharField(
        max_length=20,
        choices=ESPACIADO_CHOICES,
        default='normal'
    )

    TEMA_CHOICES = [
        ('claro', 'Claro'),
        ('oscuro', 'Oscuro'),
        ('infantil-azul', 'Infantil Azul'),
        ('infantil-verde', 'Infantil Verde'),
    ]
    tema_visual = models.CharField(
        max_length=20,
        choices=TEMA_CHOICES,
        default='infantil-azul'
    )

    # --- CONFIGURACIONES DE AUDIO ---
    VELOCIDAD_NARRACION_CHOICES = [
        ('lenta', 'Lenta'),
        ('normal', 'Normal'),
        ('rapida', 'Rápida'),
    ]
    velocidad_narracion = models.CharField(
        max_length=10,
        choices=VELOCIDAD_NARRACION_CHOICES,
        default='normal'
    )

    TIPO_VOZ_CHOICES = [
        ('nino', 'Niño'),
        ('nina', 'Niña'),
        ('adulto-masculino', 'Adulto Masculino'),
        ('adulto-femenino', 'Adulto Femenino'),
    ]
    tipo_voz = models.CharField(
        max_length=20,
        choices=TIPO_VOZ_CHOICES,
        default='nino'
    )

    volumen_narracion = models.IntegerField(default=80)
    volumen_musica = models.IntegerField(default=50)

    MOTOR_VOZ_CHOICES = [
        ('navegador', 'Navegador (rápido)'),
        ('azure', 'Voz natural (IA)'),
    ]
    motor_voz = models.CharField(
        max_length=10,
        choices=MOTOR_VOZ_CHOICES,
        default='navegador'
    )

    # --- FECHAS DE ACTUALIZACIÓN ---
    actualizado_en = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Configuración de {self.usuario.username}"

    class Meta:
        verbose_name = "Configuración Global"
        verbose_name_plural = "Configuraciones Globales"
