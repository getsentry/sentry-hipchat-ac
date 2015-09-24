import logging
import sentry_hipchat_ac
from urllib import quote as url_quote
from urlparse import urlparse

from django.conf import settings
from django.template.loader import render_to_string
from django.template.context import RequestContext
from django.utils.html import escape
from django.http import HttpResponseRedirect

from sentry.plugins import plugins
from sentry.plugins.bases.notify import NotifyPlugin
from sentry.utils.http import absolute_uri
from django.core.urlresolvers import reverse

from .cards import make_event_notification


ADDON_HOST_IDENT = urlparse(settings.SENTRY_URL_PREFIX).hostname
if ADDON_HOST_IDENT in ('localhost', '127.0.0.1'):
    ADDON_HOST_IDENT = 'app.dev.getsentry.com'
ON_PREMISE = ADDON_HOST_IDENT == 'app.getsentry.com'

COLORS = {
    'ALERT': 'red',
    'ERROR': 'red',
    'WARNING': 'yellow',
    'INFO': 'green',
    'DEBUG': 'purple',
}


def enable_plugin_for_tenant(project, tenant):
    rv = False
    plugin = plugins.get('hipchat-ac')

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
    plugin = plugins.get('hipchat-ac')

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
    author = 'Sentry'
    author_url = 'https://github.com/getsentry/sentry-hipchat-ac'
    version = sentry_hipchat_ac.VERSION
    description = "Event notification to HipChat."
    resource_links = [
        ('Bug Tracker', 'https://github.com/getsentry/sentry-hipchat-ac/issues'),
        ('Source', 'https://github.com/getsentry/sentry-hipchat-ac'),
    ]
    slug = 'hipchat-ac'
    # TODO: shorten the title
    title = 'HipChat with Atlassian Connect'
    conf_title = title
    conf_key = 'hipchat-ac'
    timeout = getattr(settings, 'SENTRY_HIPCHAT_TIMEOUT', 3)

    def is_configured(self, project):
        return bool(self.get_option('tenants', project))

    def configure(self, request, project=None):
        if request.method == 'POST' and project is not None:
            try:
                test_results = self.test_configuration(project)
            except Exception as exc:
                if hasattr(exc, 'read') and callable(exc.read):
                    test_results = '%s\n%s' % (exc, exc.read())
                else:
                    logging.exception('HipChat Plugin raised an error during test')
                    test_results = 'There was an internal error with the Plugin'
            if not test_results:
                test_results = 'No errors returned'
            return HttpResponseRedirect(request.get_current_url())
        return render_to_string('sentry_hipchat_ac/configure_plugin.html', dict(
            plugin=self,
            plugin_test_results=test_results,
            on_premise=ON_PREMISE,
            tenants=list(project.hipchat_tenant_set.all()),
            descriptor=absolute_uri(reverse('sentry-hipchat-ac-descriptor')),
            install_url='https://www.hipchat.com/addons/install?url=' +
            url_quote(absolute_uri(reverse('sentry-hipchat-ac-descriptor')))),
            context_instance=RequestContext(request))

    def get_url_module(self):
        return 'sentry_hipchat_ac.urls'

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
        tenants = Tenant.objects.filter(projects=event.project)
        for tenant in tenants:
            ctx = Context.for_tenant(tenant)
            ctx.send_notification(**make_event_notification(
                group, event, tenant))

            MentionedEvent.objects.mention(
                project=event.project,
                group=group,
                tenant=tenant,
                event=event,
            )
            ctx.push_recent_events_glance()


from .models import Tenant, Context, MentionedEvent
