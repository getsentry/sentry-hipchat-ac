"""
sentry_hipchat.models
~~~~~~~~~~~~~~~~~~~~~

:copyright: (c) 2015 by Functional Software Inc., see AUTHORS for more details.
:license: BSD, see LICENSE for more details.
"""

import requests
import time
import jwt

import sentry_hipchat

from django import forms
from django.conf import settings
from django.db import models
from django.core.cache import cache
from urlparse import urlparse

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
               group_id=None, group_name=None, capdoc=None):
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
        installed_from = self.token_url and base_url(self.token_url) or None

        return models.Manager.create(self,
            room_id=room_id,
            secret=secret,
            group_id=group_id,
            group_name=group_name,
            homepage=homepage,
            token_url=token_url,
            capabilities_url=capabilities_url,
            api_base_url=api_base_url,
            installed_from=installed_from,
        )


class Tenant(models.Model):
    objects = TenantManager()
    room_id = models.CharField(max_length=40)
    secret = models.CharField(max_length=120)
    group_id = models.CharField(max_length=40)
    group_name = models.CharField(max_length=50)
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
                cache.setex(cache_key, token, data['expires_in'] - 20)
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
