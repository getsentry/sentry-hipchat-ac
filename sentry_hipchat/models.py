"""
sentry_hipchat.models
~~~~~~~~~~~~~~~~~~~~~

:copyright: (c) 2015 by Functional Software Inc., see AUTHORS for more details.
:license: BSD, see LICENSE for more details.
"""

import jwt
import time
import json
import requests

import sentry_hipchat

from django import forms
from django.conf import settings
from django.db import models
from django.core.cache import cache
from urlparse import urlparse, urljoin

from sentry.plugins.bases.notify import NotifyPlugin
from requests.auth import HTTPBasicAuth
from datetime import timedelta


def base_url(url):
    result = urlparse(url)
    return '%s://%s' % (result.scheme, result.netloc)


class OauthClientInvalidError(Exception):

    def __init__(self, client, *args, **kwargs):
        super(OauthClientInvalidError, self).__init__(*args, **kwargs)
        self.client = client


class BadTenantError(Exception):
    pass


class HipchatOptionsForm(forms.Form):
    token = forms.CharField(help_text="Your hipchat API v1 token.")
    room = forms.CharField(help_text="Room name or ID.")
    notify = forms.BooleanField(help_text='Notify message in chat window.',
                                required=False)
    include_project_name = forms.BooleanField(
        help_text='Include project name in message.', required=False)


class HipchatMessage(NotifyPlugin):
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
    project_conf_form = HipchatOptionsForm
    timeout = getattr(settings, 'SENTRY_HIPCHAT_TIMEOUT', 3)

    def is_configured(self, project):
        return all((self.get_option(k, project) for k in ('room', 'token')))

    def on_alert(self, alert, **kwargs):
        pass

    def notify_users(self, group, event, fail_silently=False):
        pass


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


class Tenant(models.Model):
    objects = TenantManager()
    id = models.CharField(max_length=40, primary_key=True)
    room_id = models.CharField(max_length=40)
    secret = models.CharField(max_length=120)
    homepage = models.CharField(max_length=250)
    token_url = models.CharField(max_length=250)
    capabilities_url = models.CharField(max_length=250)
    api_base_url = models.CharField(max_length=250)
    installed_from = models.CharField(max_length=250)

    def get_token(self, token_only=True, scopes=None):
        if scopes is None:
            scopes = ['send_notification']

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

    def __init__(self, tenant, sender, context):
        self.tenant = tenant
        self.sender = sender
        self.context = context

    @property
    def tenant_token(self):
        rv = getattr(self, '_tenant_token', None)
        if rv is None:
            rv = self._tenant_token = self.tenant.get_token()
        return rv

    @classmethod
    def for_request(self, request, body=None):
        tenant, jwt_data = Tenant.objects.for_request(request, body)
        webhook_sender_id = jwt_data.get('sub')

        if body and 'item' in body:
            if 'sender' in body['item']:
                sender_data = body['item']['sender']
            elif 'message' in body['item'] and 'from' in body['item']['message']:
                sender_data = body['item']['message']['from']
            else:
                sender_data = None

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
            context=jwt_data.get('context'),
        )

    def post(self, url, data):
        return requests.post(urljoin(self.tenant.api_base_url, url), headers={
            'Authorization': 'Bearer %s' % self.tenant_token,
            'Content-Type': 'application/json'
        }, data=json.dumps(data), timeout=10)

    def send_notification(self, message):
        self.post('room/%s/notification' % self.tenant.room_id,
                  {'message': message})
