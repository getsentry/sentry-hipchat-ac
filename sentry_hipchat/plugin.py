import sentry_hipchat

from django.conf import settings
from django.template.loader import render_to_string

from sentry.plugins import plugins
from sentry.plugins.bases.notify import NotifyPlugin
from sentry.utils.http import absolute_uri

from .models import Tenant


def enable_plugin_for_tenant(project, tenant):
    plugin = plugins.get('hipchat')

    # Make sure the plugin itself is enabled.
    plugin.enable(project)

    # Add our tenant to the plugin.
    active = set(plugin.get_option('active_projects', project) or ())
    if tenant.id not in active:
        active.add(tenant.id)
        tenant.projects.add(project)
    plugin.set_option('active_projects', sorted(active), project)


def disable_plugin_for_tenant(project, tenant):
    plugin = plugins.get('hipchat')

    # Remove our tenant to the plugin.
    active = set(plugin.get_option('active_projects', project) or ())
    if tenant.id in active:
        tenant.projects.remove(project)
        active.discard(tenant.id)
    plugin.set_option('active_projects', sorted(active), project)

    # If the last tenant is gone, we disable the entire plugin.
    if not active:
        plugin.disable(project)


class HipchatNotifier(NotifyPlugin):
    author = 'Functional Software Inc.'
    author_url = 'https://github.com/getsentry/sentry-hipchat'
    version = sentry_hipchat.VERSION
    description = "Event notification to Hipchat."
    resource_links = [
        ('Bug Tracker', 'https://github.com/getsentry/sentry-hipchat/issues'),
        ('Source', 'https://github.com/getsentry/sentry-hipchat'),
    ]
    slug = 'hipchat'
    title = 'Hipchat'
    conf_title = title
    conf_key = 'hipchat'
    timeout = getattr(settings, 'SENTRY_HIPCHAT_TIMEOUT', 3)

    def is_configured(self, project):
        return all((self.get_option(k, project) for k in ('room', 'token')))

    def configure(self, request, project=None):
        return render_to_string('hipchat_sentry_configure_plugin.html', dict(
            on_premise='.getsentry.com' not in request.META['HTTP_HOST'],
            tenants=list(project.hipchat_tenant_set.all()),
            descriptor=absolute_uri('/api/hipchat/')))

    def disable(self, project=None, user=None):
        NotifyPlugin.disable(self, project, user)

        if project is not None:
            for tenant in Tenant.objects.filter(projects__in=[project]):
                disable_plugin_for_tenant(project, tenant)

    def on_alert(self, alert, **kwargs):
        pass

    def notify_users(self, group, event, fail_silently=False):
        pass
