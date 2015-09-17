from sentry.plugins import plugins


def enable_plugin_for_tenant(project, tenant):
    plugin = plugins.get('hipchat')

    # Make sure the plugin itself is enabled.
    plugin.set_option('enabled', True, project)

    # Add our tenant to the plugin.
    active = set(plugin.get_option('active_projects', project) or ())
    if tenant.id not in active:
        active.add(tenant.id)
        tenant.projects.add(project)
    plugin.set_option('enabled', sorted(active), project)


def disable_plugin_for_tenant(project, tenant):
    plugin = plugins.get('hipchat')

    # Remove our tenant to the plugin.
    active = set(plugin.get_option('active_projects', project) or ())
    if tenant.id in active:
        tenant.projects.remove(project)
        active.discard(tenant.id)
    plugin.set_option('enabled', sorted(active), project)

    # If the last tenant is gone, we disable the entire plugin.
    if not active:
        plugin.set_option('enabled', False, project)
