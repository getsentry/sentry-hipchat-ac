import re
import json
import requests
from functools import update_wrapper
from django import forms
from django.conf import settings
from django.views.generic import View
from django.core.urlresolvers import reverse
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from sentry.utils.http import absolute_uri
from sentry.models import Organization, Team

from .utils import JsonResponse, IS_DEBUG
from .models import Tenant, Context
from .plugin import enable_plugin_for_tenant, disable_plugin_for_tenant
from .cards import make_event_notification, make_generic_notification, \
     make_subscription_update_notification


_link_pattern = re.escape(settings.SENTRY_URL_PREFIX) \
    .replace('https\\:', 'https?\\:') + '/'
_link_re = re.compile(_link_pattern +
    r'(?P<org>[^/]+)/(?P<proj>[^/]+)/group/'
    r'(?P<group>[^/]+)(/events/(?P<event>[^/]+)|/?)')


ICON = 'https://beta.getsentry.com/_static/sentry/images/favicon.ico'
ICON2X = 'https://beta.getsentry.com/_static/sentry/images/favicon.ico'


class DescriptorView(View):

    def get(self, request):
        return JsonResponse({
            'key': 'hipchat-sentry',
            'name': 'Sentry for Hipchat',
            'description': 'Sentry integration for Hipchat.',
            'links': {
                'self': absolute_uri(reverse('sentry-hipchat-descriptor')),
            },
            'icon': {
                'url': ICON,
            },
            'capabilities': {
                'installable': {
                    'allowRoom': True,
                    'allowGlobal': False,
                    'callbackUrl': absolute_uri(reverse(
                        'sentry-hipchat-installable')),
                },
                'hipchatApiConsumer': {
                    'scopes': ['send_notification', 'view_room'],
                },
                'configurable': {
                    'url': absolute_uri(reverse('sentry-hipchat-config')),
                },
                'webhook': [
                    {
                        'event': 'room_message',
                        'url': absolute_uri(reverse('sentry-hipchat-link-message')),
                        'pattern': _link_pattern,
                        'authentication': 'jwt',
                    },
                ],
                'webPanel': [
                    {
                        'key': 'sentry.sidebar.event-details',
                        'name': {
                            'value': 'Sentry Event Details',
                        },
                        'location': 'hipchat.sidebar.right',
                        'url': absolute_uri(reverse(
                            'sentry-hipchat-event-details')),
                    },
                    {
                        'key': 'sentry.sidebar.recent-events',
                        'name': {
                            'value': 'Recent Sentry Events',
                        },
                        'location': 'hipchat.sidebar.right',
                        'url': absolute_uri(reverse(
                            'sentry-hipchat-recent-events')),
                    },
                ],
                'action': [
                    {
                        'key': 'message.sentry.event-details',
                        'name': {
                            'value': 'Show details',
                        },
                        'target': 'sentry.sidebar.event-details',
                        'location': 'hipchat.message.action',
                        'conditions': [
                            {
                                'condition': 'card_matches',
                                'params': {
                                    'metadata': [
                                        {'attr': 'sentry_message_type',
                                         'eq': 'event'},
                                     ]
                                }
                            }
                        ],
                    }
                ],
                'glance': [
                    {
                        'name': {
                            'value': 'Sentry',
                        },
                        'queryUrl': absolute_uri(reverse(
                            'sentry-hipchat-main-glance')),
                        'key': 'sentry-main-glance',
                        'target': 'sentry.sidebar.recent-events',
                        'icon': {
                            'url': ICON,
                            'url@2x': ICON2X,
                        },
                        'conditions': [],
                    }
                ],
            },
            'vendor': {
                'url': 'https://www.getsentry.com/',
                'name': 'Sentry',
            }
        })


class InstallableView(View):

    @method_decorator(csrf_exempt)
    def dispatch(self, *args, **kwargs):
        return View.dispatch(self, *args, **kwargs)

    def post(self, request):
        data = json.loads(request.body) or {}

        room_id = data.get('roomId', None)
        if room_id is None:
            return HttpResponse('This add-on can only be installed in '
                                'individual rooms.', status=400)

        capdoc = requests.get(data['capabilitiesUrl'], timeout=10).json()
        if capdoc['links'].get('self') != data['capabilitiesUrl']:
            return HttpResponse('Mismatch on capabilities URL',
                                status=400)

        # Make sure we clean up an old existing tenant if we have one.
        try:
            old_tenant = Tenant.objects.get(pk=data['oauthId'])
        except Tenant.DoesNotExist:
            pass
        else:
            old_tenant.delete()

        tenant = Tenant.objects.create(
            id=data['oauthId'],
            room_id=room_id,
            secret=data['oauthSecret'],
            capdoc=capdoc,
        )
        tenant.update_room_info()

        return HttpResponse('', status=201)

    def delete(self, request, oauth_id):
        try:
            tenant = Tenant.objects.get(pk=oauth_id)
            tenant.delete()
        except Tenant.DoesNotExist:
            pass
        return HttpResponse('', status=201)


class GrantAccessForm(forms.Form):
    orgs = forms.MultipleChoiceField(widget=forms.CheckboxSelectMultiple,
                                     label='Organizations',
                                     required=False)

    def __init__(self, tenant, request):
        self.user = request.user
        self.tenant = tenant
        self.all_orgs = Organization.objects.get_for_user(request.user)
        org_choices = [(str(x.id), x.name) for x in self.all_orgs]
        if request.method == 'POST':
            forms.Form.__init__(self, request.POST)
        else:
            forms.Form.__init__(self)
        self.fields['orgs'].choices = org_choices

    def clean_orgs(self):
        rv = [org for org in self.all_orgs if str(org.id) in
              self.cleaned_data['orgs']]
        if not rv:
            raise forms.ValidationError('You need to select at least one '
                                        'organization to give access to.')
        return rv

    def save_changes(self):
        self.tenant.auth_user = self.user
        self.tenant.organizations = self.cleaned_data['orgs']
        self.tenant.save()
        notify_tenant_added(self.tenant)


class ProjectSelectForm(forms.Form):
    projects = forms.MultipleChoiceField(widget=forms.CheckboxSelectMultiple,
                                         label='Projects', required=False)

    def __init__(self, tenant, request):
        self.tenant = tenant
        project_choices = []
        self.projects_by_id = {}

        for org in tenant.organizations.all():
            teams = Team.objects.get_for_user(org, tenant.auth_user,
                                              with_projects=True)
            for team, projects in teams:
                for project in projects:
                    project_choices.append((str(project.id), '%s/%s' % (
                        org.name, project.name)))
                    self.projects_by_id[str(project.id)] = project

        project_choices.sort(key=lambda x: x[1].lower())

        if request.method == 'POST':
            forms.Form.__init__(self, request.POST)
        else:
            forms.Form.__init__(self, initial={
                'projects': [str(x.id) for x in tenant.projects.all()],
            })

        self.fields['projects'].choices = project_choices

    def clean_projects(self):
        return set(self.cleaned_data['projects'])

    def save_changes(self):
        new_projects = []
        removed_projects = []

        for project_id, project in self.projects_by_id.iteritems():
            if project_id in self.cleaned_data['projects']:
                if enable_plugin_for_tenant(project, self.tenant):
                    new_projects.append(project)
            else:
                if disable_plugin_for_tenant(project, self.tenant):
                    removed_projects.append(project)

        if new_projects or removed_projects:
            ctx = Context.for_tenant(self.tenant)
            ctx.send_notification(**make_subscription_update_notification(
                new_projects, removed_projects))


def webhook(f):
    @csrf_exempt
    def new_f(request, *args, **kwargs):
        data = json.loads(request.body) or {}
        context = Context.for_request(request, data)
        return f(request, context, data, *args, **kwargs)
    return update_wrapper(new_f, f)


def with_context(f):
    def new_f(request, *args, **kwargs):
        context = Context.for_request(request)
        return f(request, context, *args, **kwargs)
    return update_wrapper(new_f, f)


def cors(f):
    def new_f(request, *args, **kwargs):
        origin = request.META.get('HTTP_ORIGIN')
        resp = f(request, *args, **kwargs)
        resp['Access-Control-Allow-Origin'] = origin
        resp['Access-Control-Request-Method'] = 'GET, HEAD, OPTIONS'
        resp['Access-Control-Allow-Headers'] = 'X-Requested-With'
        resp['Access-Control-Allow-Credentials'] = 'true'
        resp['Access-Control-Max-Age'] = '1728000'
        return resp
    return update_wrapper(new_f, f)


@with_context
def configure(request, context):
    # XXX: this is a bit terrible because it means the login url is
    # already set at the time we visit this page.  This can have some
    # stupid consequences when opening up the login page seaprately in a
    # different tab later.  Ideally we could pass the login url through as
    # a URL parameter instead but this is currently not securely possible.
    request.session['_next'] = request.get_full_path()

    grant_form = None
    project_select_form = None

    if context.tenant.auth_user is None and \
       request.user.is_authenticated():
        grant_form = GrantAccessForm(context.tenant, request)
        if request.method == 'POST' and grant_form.is_valid():
            grant_form.save_changes()
            return HttpResponseRedirect(request.get_full_path())

    elif context.tenant.auth_user is not None:
        project_select_form = ProjectSelectForm(context.tenant, request)
        if request.method == 'POST' and project_select_form.is_valid():
            project_select_form.save_changes()
            return HttpResponseRedirect(request.get_full_path())

    return render(request, 'hipchat_sentry_configure.html', {
        'context': context,
        'tenant': context.tenant,
        'current_user': request.user,
        'grant_form': grant_form,
        'project_select_form': project_select_form,
        'available_orgs': list(context.tenant.organizations.all()),
        'hipchat_debug': IS_DEBUG,
    })


@with_context
def sign_out(request, context):
    tenant = context.tenant
    cfg_url = '%s?signed_request=%s' % (
        reverse('sentry-hipchat-config'),
        context.signed_request
    )

    if tenant.auth_user is None or 'no' in request.POST:
        return HttpResponseRedirect(cfg_url)
    elif request.method == 'POST':
        tenant.auth_user = None
        tenant.organizations.clear()
        for project in tenant.projects.all():
            disable_plugin_for_tenant(project, tenant)
        tenant.save()
        notify_tenant_removal(tenant)
        return HttpResponseRedirect(cfg_url)

    return render(request, 'hipchat_sentry_sign_out.html', {
        'context': context,
        'tenant': tenant,
    })


@cors
@with_context
def main_glance(request, context):
    return JsonResponse({
        'label': {
            'type': 'html',
            'value': '<b>10</b> Recent Sentry Events',
        },
        'status': {
            'type': 'lozenge',
            'value': {
                'label': 'COOL',
                'type': 'current',
            }
        },
    })


@with_context
def event_details(request, context):
    event = None
    group = None
    interface_data = {}
    tags = []
    event_id = request.GET.get('event')

    if event_id is not None:
        event = context.get_event(event_id)
        if event is None:
            return HttpResponse('Bad Request', status=400)
        group = event.group

        tags = event.get_tags()

        interface_data.update(
            http=event.interfaces.get('sentry.interfaces.Http'),
            user=event.interfaces.get('sentry.interfaces.User'),
        )
        exc = event.interfaces.get('sentry.interfaces.Exception')
        if exc is not None:
            interface_data['exc'] = exc
            interface_data['exc_as_string'] = exc.to_string(event)

    return render(request, 'hipchat_sentry_event_details.html', {
        'context': context,
        'event': event,
        'group': group,
        'interfaces': interface_data,
        'tags': tags,
    })


@with_context
def recent_events(request, context):
    return HttpResponse('TODO: implement me')


@webhook
def on_link_message(request, context, data):
    match = _link_re.search(data['item']['message']['message'])
    if match is not None:
        params = match.groupdict()
        event = context.get_event_from_url_params(
            group_id=params['group'],
            event_id=params['event'],
            slug_vars={'org_slug': params['org'],
                       'proj_slug': params['proj']}
        )
        if event is not None:
            context.send_notification(**make_event_notification(
                event.group, event, context.tenant, new=False,
                event_target=params['event'] is not None))

    return HttpResponse('', status=204)


def notify_tenant_added(tenant):
    ctx = Context.for_tenant(tenant)
    ctx.send_notification(**make_generic_notification(
        'The Sentry Hipchat integration was associated with this room.',
        color='green'))


def notify_tenant_removal(tenant):
    ctx = Context.for_tenant(tenant)
    ctx.send_notification(**make_generic_notification(
        'The Sentry Hipchat integration was disassociated with this room.',
        color='red'))
