from .models import Avatar, ReaccionAvatar, InventarioAvatar
from .reactions import obtener_reaccion
from recompensas.models import Insignia, MascotaUsuario
from recompensas.services import get_evento_activo
import json

def avatar_global(request):
    if request.user.is_authenticated:
        avatar_obj, created = Avatar.objects.get_or_create(usuario=request.user)

        inventario = InventarioAvatar.objects.filter(
            avatar=avatar_obj,
            equipado=True
        ).select_related('item')

        equipados = {
            inv.item.categoria: inv.item
            for inv in inventario
        }

        reacciones = ReaccionAvatar.objects.filter(
            activo=True
        ).values(
            'tipo_evento',
            'emocion',
            'mensaje'
        )

        reacciones_dict = {
            r['tipo_evento']: {
                'emocion': r['emocion'],
                'mensaje': r['mensaje']
            }
            for r in reacciones
        }

        # Insignias pendientes de mostrar (NO se marcan como mostradas aquí;
        # eso lo hace `obtener_insignias_pendientes` cuando se invoque
        # explícitamente desde una vista).
        insignias_pendientes = Insignia.objects.filter(
            usuario=request.user,
            mostrada=False
        ).select_related('tipo_insignia')

        # Mascota adoptada por el usuario, si existe.
        try:
            mascota_usuario = MascotaUsuario.objects.select_related('mascota').get(usuario=request.user)
        except MascotaUsuario.DoesNotExist:
            mascota_usuario = None

        # Frase contextual de bienvenida: usa la frase personalizada del
        # avatar si el usuario la definió; de lo contrario, una variante
        # aleatoria del catálogo de reacciones.
        if avatar_obj.frase_bienvenida:
            avatar_frase_contextual = avatar_obj.frase_bienvenida
        else:
            avatar_frase_contextual = obtener_reaccion('bienvenida_diaria')

        return {
            'avatar_user': avatar_obj,
            'avatar_equipados': equipados,
            'reacciones_json': json.dumps(reacciones_dict),
            'insignias_pendientes': insignias_pendientes,
            'mascota_usuario': mascota_usuario,
            'monedas_usuario': request.user.monedas,
            'racha_dias': request.user.racha_dias,
            'evento_activo': get_evento_activo(),
            'avatar_frase_contextual': avatar_frase_contextual,
        }

    return {}