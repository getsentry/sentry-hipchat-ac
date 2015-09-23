import jwt
import time
import json
import logging
import requests

from django.db import models
from django.core.cache import cache
from django.utils import timezone
from urlparse import urlparse, urljoin

from requests.auth import HTTPBasicAuth
from datetime import timedelta

from sentry.models import Event, Group


logger = logging.getLogger(__name__)


MAX_RECENT = 15
RECENT_HOURS = 12


def base_url(url):
    result = urlparse(url)
    return '%s://%s' % (result.scheme, result.netloc)


class HipChatException(Exception):
    pass


class OauthClientInvalidError(HipChatException):

    def __init__(self, client, *args, **kwargs):
        super(OauthClientInvalidError, self).__init__(*args, **kwargs)
        self.client = client


class BadTenantError(HipChatException):
    pass


class MentionedEventManager(models.Manager):

    def recent(self, tenant):
        rv = list(MentionedEvent.objects.order_by('-last_mentioned')
            .filter(tenant=tenant, last_mentioned__gt=timezone.now() -
                    timedelta(hours=RECENT_HOURS))[:MAX_RECENT])
        for me in rv:
            if me.event is None:
                me.event = me.group.get_latest_event()
        Event.objects.bind_nodes([x.event for x in rv], 'data')
        return rv

    def count(self, tenant):
        return MentionedEvent.objects \
            .filter(tenant=tenant, last_mentioned__gt=timezone.now() -
                    timedelta(hours=RECENT_HOURS))[:MAX_RECENT].count()

    def mention(self, project, group, tenant, event=None):
        try:
            evt = MentionedEvent.objects.get(
                project=project,
                group=group,
                tenant=tenant
            )
        except MentionedEvent.DoesNotExist:
            evt = MentionedEvent.objects.create(
                project=project,
                group=group,
                event=event,
                tenant=tenant
            )
        else:
            evt.last_mentioned = timezone.now()
            if event is not None:
                evt.event = event
            evt.save()
            return evt

        old_events = MentionedEvent.objects.filter(
            tenant=tenant,
        ).order_by('-last_mentioned')[MAX_RECENT:]
        for old_event in old_events:
            old_event.delete()

        return evt


class TenantManager(models.Manager):

    def create(self, id, secret=None, homepage=None,
               capabilities_url=None, room_id=None, token_url=None,
               capdoc=None):
        if homepage is None and capdoc is not None:
            homepage = capdoc['links']['homepage']
        if token_url is None and capdoc is not None:
            token_url = capdoc['capabilities']['oauth2Provider']['tokenUrl']
        if capabilities_url is None and capdoc is not None:
            capabilities_url = capdoc['links']['self']
        if capdoc is not None:
            api_base_url = capdoc['capabilities']['hipchatApiProvider']['url']
        else:
            api_base_url = capabilities_url.rsplit('/', 1)[0]
        installed_from = token_url and base_url(token_url) or None

        return models.Manager.create(self,
            id=id,
            room_id=room_id,
            secret=secret,
            homepage=homepage,
            token_url=token_url,
            capabilities_url=capabilities_url,
            api_base_url=api_base_url,
            installed_from=installed_from,
        )

    def for_request(self, request, body=None):
        if body and 'oauth_client_id' in body:
            rv = Tenant.objects.get(pk=body['oauth_client_id'])
            if rv is not None:
                return rv, {}

        jwt_data = request.GET.get('signed_request')

        if not jwt_data:
            header = request.META.get('HTTP_AUTHORIZATION', '')
            jwt_data = header[4:] if header.startswith('JWT ') else None

        if not jwt_data:
            raise BadTenantError('Could not find JWT')

        try:
            oauth_id = jwt.decode(jwt_data, verify=False)['iss']
            client = Tenant.objects.get(pk=oauth_id)
            if client is not None:
                data = jwt.decode(jwt_data, client.secret)
                return client, data
        except jwt.exceptions.DecodeError:
            pass

        raise BadTenantError('Could not find tenant')


class MentionedEvent(models.Model):
    objects = MentionedEventManager()
    project = models.ForeignKey(
        'sentry.Project', related_name='hipchat_mentioned_events')
    group = models.ForeignKey(
        'sentry.Group', related_name='hipchat_mentioned_groups')
    event = models.ForeignKey(
        'sentry.Event', related_name='hipchat_mentioned_events',
        null=True)
    tenant = models.ForeignKey('sentry_hipchat_ac.Tenant')
    last_mentioned = models.DateTimeField(default=timezone.now)


class Tenant(models.Model):
    objects = TenantManager()
    id = models.CharField(max_length=40, primary_key=True)
    room_id = models.CharField(max_length=40)
    room_name = models.CharField(max_length=200, null=True)
    room_owner_id = models.CharField(max_length=40, null=True)
    room_owner_name = models.CharField(max_length=200, null=True)
    secret = models.CharField(max_length=120)
    homepage = models.CharField(max_length=250)
    token_url = models.CharField(max_length=250)
    capabilities_url = models.CharField(max_length=250)
    api_base_url = models.CharField(max_length=250)
    installed_from = models.CharField(max_length=250)

    auth_user = models.ForeignKey('sentry.User', null=True,
                                  related_name='hipchat_tenant_set')
    organizations = models.ManyToManyField(
        'sentry.Organization', related_name='hipchat_tenant_set')
    projects = models.ManyToManyField(
        'sentry.Project', related_name='hipchat_tenant_set')

    def get_token(self, token_only=True, scopes=None):
        if scopes is None:
            scopes = ['send_notification', 'view_room']

        cache_key = 'hipchat-tokens:%s:%s' % (self.id, ','.join(scopes))

        def gen_token():
            data = {
                'grant_type': 'client_credentials',
                'scope': ' '.join(scopes),
            }
            resp = requests.post(self.token_url, data=data,
                                 auth=HTTPBasicAuth(self.id, self.secret),
                                 timeout=10)
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 401:
                raise OauthClientInvalidError(self)
            else:
                raise Exception('Invalid token: %s' % resp.text)

        if token_only:
            token = cache.get(cache_key)
            if not token:
                data = gen_token()
                token = data['access_token']
                cache.set(cache_key, token, data['expires_in'] - 20)
            return token
        else:
            return gen_token()

    def sign_jwt(self, user_id, data=None):
        if data is None:
            data = {}

        now = int(time.time())
        exp = now + timedelta(hours=1).total_seconds()

        jwt_data = {'iss': self.id,
                    'iat': now,
                    'exp': exp}

        if user_id:
            jwt_data['sub'] = user_id

        data.update(jwt_data)
        return jwt.encode(data, self.secret)

    def delete(self, *args, **kwargs):
        for project in self.projects.all():
            disable_plugin_for_tenant(project, self)
        MentionedEvent.objects.filter(
            tenant=self
        ).delete()
        models.Model.delete(self, *args, **kwargs)

    def clear(self, commit=True):
        self.auth_user = None
        self.organizations.clear()
        MentionedEvent.objects.filter(
            tenant=self
        ).delete()
        for project in self.projects.all():
            disable_plugin_for_tenant(project, self)
        if commit:
            self.save()

    def update_room_info(self, commit=True):
        headers = {
            'Authorization': 'Bearer %s' % self.get_token(),
            'Content-Type': 'application/json'
        }
        room = requests.get(urljoin(self.api_base_url, 'room/%s') %
                            self.room_id, headers=headers, timeout=5).json()
        self.room_name = room['name']
        self.room_owner_id = str(room['owner']['id'])
        self.room_owner_name = str(room['owner']['name'])
        if commit:
            self.save()

    def __repr__(self):
        return '<Tenant id=%r from=%r>' % (
            self.id,
            self.installed_from,
        )

    def __unicode__(self):
        return 'Tenant %s' % self.id


def _extract_sender(item):
    if 'sender' in item:
        return item['sender']
    if 'message' in item and 'from' in item['message']:
        return item['message']['from']
    return None


class HipchatUser(object):

    def __init__(self, id, mention_name=None, name=None):
        self.id = id
        self.mention_name = mention_name
        self.name = name


class Context(object):

    def __init__(self, tenant, sender, context, signed_request=None):
        self.tenant = tenant
        self.sender = sender
        self.context = context
        self.signed_request = signed_request

    @staticmethod
    def for_request(request, body=None):
        """Creates the context for a specific request."""
        tenant, jwt_data = Tenant.objects.for_request(request, body)
        webhook_sender_id = jwt_data.get('sub')
        sender_data = None

        if body and 'item' in body:
            if 'sender' in body['item']:
                sender_data = body['item']['sender']
            elif 'message' in body['item'] and 'from' in body['item']['message']:
                sender_data = body['item']['message']['from']

        if sender_data is None:
            if webhook_sender_id is None:
                raise BadTenantError('Cannot identify sender in tenant')
            sender_data = {'id': webhook_sender_id}

        return Context(
            tenant=tenant,
            sender=HipchatUser(
                id=sender_data.get('id'),
                name=sender_data.get('name'),
                mention_name=sender_data.get('mention_name'),
            ),
            signed_request=request.GET.get('signed_request'),
            context=jwt_data.get('context') or {},
        )

    @staticmethod
    def for_tenant(tenant):
        """Creates a context just for a tenant."""
        return Context(
            tenant=tenant,
            sender=None,
            context={},
        )

    @property
    def tenant_token(self):
        """The cached token of the current tenant."""
        rv = getattr(self, '_tenant_token', None)
        if rv is None:
            rv = self._tenant_token = self.tenant.get_token()
        return rv

    @property
    def room_id(self):
        """The most appropriate room for this context."""
        return self.context.get('room_id', self.tenant.room_id)

    def post(self, url, data):
        resp = requests.post(urljoin(self.tenant.api_base_url, url), headers={
            'Authorization': 'Bearer %s' % self.tenant_token,
            'Content-Type': 'application/json'
        }, data=json.dumps(data), timeout=10)
        if not resp.ok:
            logger.warning('Request to "%s" failed:\n%s',
                           url, resp.text)
        return resp

    def send_notification(self, message, color='yellow', notify=False,
                          format='html', card=None):
        data = {'message': message, 'format': format, 'notify': notify}
        if color is not None:
            data['color'] = color
        if card is not None:
            data['card'] = card
        self.post('room/%s/notification' % self.room_id, data)

    def get_recent_events_glance(self):
        count = MentionedEvent.objects.count(self.tenant)
        return {
            'label': {
                'type': 'html',
                'value': '<b>%s</b> Recent Sentry Event%s' % (
                    count, count != 1 and 's' or '')
            },
        }

    def push_recent_events_glance(self):
        self.post('addon/ui/room/%s' % self.room_id, {
            'glance': [{
                'content': self.get_recent_events_glance(),
                'key': 'sentry-recent-events-glance',
            }]
        })

    def _ensure_and_bind_event(self, event):
        rv = self.tenant.projects.filter(pk=event.project.id).first()
        if rv is not None:
            Event.objects.bind_nodes([event], 'data')
            return event

    def get_event(self, event_id):
        try:
            event = Event.objects.get(pk=int(event_id))
        except (ValueError, Event.DoesNotExist):
            return None
        return self._ensure_and_bind_event(event)

    def get_event_from_url_params(self, group_id, event_id=None, slug_vars=None):
        if event_id is not None:
            try:
                event = Event.objects.get(pk=int(event_id))
            except (ValueError, Event.DoesNotExist):
                return None
            group = event.group
            if str(group.id) != group_id:
                return None
        else:
            try:
                group = Group.objects.get(pk=int(group_id))
            except (ValueError, Group.DoesNotExist):
                return None
            event = group.get_latest_event()
        event = self._ensure_and_bind_event(event)
        if event is None:
            return None

        if slug_vars is not None:
            if slug_vars['org_slug'] != group.organization.slug or \
               slug_vars['proj_slug'] != group.project.slug:
                return None

        return event


from .plugin import disable_plugin_for_tenant
