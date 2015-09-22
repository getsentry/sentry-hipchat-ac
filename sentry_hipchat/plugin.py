import sentry_hipchat
from urllib import quote as url_quote

from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import escape

from sentry.plugins import plugins
from sentry.plugins.bases.notify import NotifyPlugin
from sentry.utils.http import absolute_uri

from .cards import make_event_notification


COLORS = {
    'ALERT': 'red',
    'ERROR': 'red',
    'WARNING': 'yellow',
    'INFO': 'green',
    'DEBUG': 'purple',
}


def enable_plugin_for_tenant(project, tenant):
    rv = False
    plugin = plugins.get('hipchat')

    # Make sure the plugin itself is enabled.
    plugin.enable(project)

    # Add our tenant to the plugin.
    active = set(plugin.get_option('tenants', project) or ())
    if tenant.id not in active:
        active.add(tenant.id)
        tenant.projects.add(project)
        rv = True
    plugin.set_option('tenants', sorted(active), project)

    return rv


def disable_plugin_for_tenant(project, tenant):
    rv = False
    plugin = plugins.get('hipchat')

    # Remove our tenant to the plugin.
    active = set(plugin.get_option('tenants', project) or ())
    if tenant.id in active:
        tenant.projects.remove(project)
        active.discard(tenant.id)
        rv = True
    plugin.set_option('tenants', sorted(active), project)

    # If the last tenant is gone, we disable the entire plugin.
    if not active:
        plugin.disable(project)

    return rv


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
        return bool(self.get_option('tenants', project))

    def configure(self, request, project=None):
        return render_to_string('hipchat_sentry_configure_plugin.html', dict(
            on_premise='.getsentry.com' not in request.META['HTTP_HOST'],
            tenants=list(project.hipchat_tenant_set.all()),
            descriptor=absolute_uri('/api/hipchat/'),
            install_url='https://www.hipchat.com/addons/install?url=' +
            url_quote(absolute_uri('/api/hipchat/'))))

    def disable(self, project=None, user=None):
        was_enabled = self.get_option('enabled', project)
        NotifyPlugin.disable(self, project, user)

        if project is not None and was_enabled:
            for tenant in Tenant.objects.filter(projects__in=[project]):
                disable_plugin_for_tenant(project, tenant)

    def on_alert(self, alert, **kwargs):
        project = alert.project

        tenants = Tenant.objects.filter(project=project)
        for tenant in tenants:
            ctx = Context.for_tenant(tenant)
            message = (
                '[ALERT] %(project_name)s %(message)s'
                '[<a href="%(link)s">view</a>]'
            ) % {
                'project_name': '<strong>%s</strong>' % escape(project.name),
                'message': escape(alert.message),
                'link': alert.get_absolute_url(),
            }
            color = COLORS['ALERT']
            ctx.send_notification(message, color=color, notify=True)

    def notify_users(self, group, event, fail_silently=False):
        tenants = Tenant.objects.filter(project=event.project)
        for tenant in tenants:
            ctx = Context.for_tenant(tenant)
            ctx.send_notification(**make_event_notification(
                group, event, tenant))

            MentionedEvent.objects.mention(
                project=event.project,
                group=group,
                tenant=self.tenant,
                event=event,
            )
            ctx.push_main_glance()


from .models import Tenant, Context, MentionedEvent
