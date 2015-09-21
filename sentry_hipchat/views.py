import json
import requests
from functools import update_wrapper
from django import forms
from django.views.generic import View
from django.core.urlresolvers import reverse
from django.http import HttpResponse, HttpResponseRedirect
from django.utils.html import mark_safe
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from sentry.utils.http import absolute_uri
from sentry.models import Organization, Team

from .utils import JsonResponse, IS_DEBUG
from .models import Tenant, Context
from .plugin import enable_plugin_for_tenant, disable_plugin_for_tenant
from .cards import make_event_notification


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
                'url': 'https://beta.getsentry.com/_static/sentry/images/favicon.ico'
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
                        'url': absolute_uri(reverse('sentry-hipchat-room-message')),
                        'pattern': 'sentry[,:]',
                        'authentication': 'jwt',
                    }
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
                    }
                ],
                'action': [
                    {
                        'key': 'message.sentry.event-details',
                        'name': {
                            'value': 'Show details',
                        },
                        'target': 'sentry.sidebar.event-details',
                        'location': 'hipchat.message.action',
                    }
                ]
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
        except Tenant.DoesNoteExist:
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
        return [org for org in self.all_orgs if str(org.id) in
                self.cleaned_data['orgs']]

    def save_changes(self):
        self.tenant.auth_user = self.user
        self.tenant.organizations = self.cleaned_data['orgs']
        self.tenant.save()


class ProjectSelectForm(forms.Form):
    projects = forms.MultipleChoiceField(widget=forms.CheckboxSelectMultiple,
                                         label='Projects', required=False)

    def __init__(self, tenant, request):
        self.tenant = tenant
        all_orgs = Organization.objects.get_for_user(tenant.auth_user)
        project_choices = []
        self.projects_by_id = {}

        for org in all_orgs:
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
        for project_id, project in self.projects_by_id.iteritems():
            if project_id in self.cleaned_data['projects']:
                enable_plugin_for_tenant(project, self.tenant)
            else:
                disable_plugin_for_tenant(project, self.tenant)


def webhook(f):
    @csrf_exempt
    def new_f(request, **kwargs):
        data = json.loads(request.body) or {}
        context = Context.for_request(request, data)
        return f(request, context, data, **kwargs)
    return update_wrapper(new_f, f)


def with_context(f):
    def new_f(request, **kwargs):
        context = Context.for_request(request)
        return f(request, context, **kwargs)
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
def event_details(request, context):
    event = None
    group = None
    interface_list = []
    tags = []
    event_id = request.GET.get('event')

    if event_id is not None:
        event = context.get_event(event_id)
        if event is None:
            return HttpResponse('Bad Request', status=400)
        group = event.group

        tags = event.get_tags()
        for interface in event.interfaces.itervalues():
            body = interface.to_email_html(event)
            if not body:
                continue
            text_body = interface.to_string(event)
            interface_list.append(
                (interface.get_title(), mark_safe(body), text_body)
            )

    return render(request, 'hipchat_sentry_event_details.html', {
        'context': context,
        'event': event,
        'group': group,
        'interfaces': interface_list,
        'tags': tags,
    })


@webhook
def on_room_message(request, context, data):
    from sentry.models import Event
    event = Event.objects.get(pk=10)
    Event.objects.bind_nodes([event], 'data')
    group = event.group
    context.send_notification(**make_event_notification(
        group, event, context.tenant))
    return HttpResponse('', status=204)
