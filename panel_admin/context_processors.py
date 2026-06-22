def modulos_panel(request):
    """Inyecta el sidebar (grupos del registro) en toda plantilla que extiende
    panel_admin/base_panel.html, para no repetirlo en cada vista.

    Solo se activa dentro de /panel/ (evita correr en cada request del resto
    de la app, que no la necesita).
    """
    if not request.path.startswith('/panel/'):
        return {}

    from .registry import grupos_para_sidebar
    return {'grupos_sidebar': grupos_para_sidebar()}
