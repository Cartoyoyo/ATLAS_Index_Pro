def classFactory(iface):
    from .plugin import ATLASIndexProPlugin
    return ATLASIndexProPlugin(iface)
