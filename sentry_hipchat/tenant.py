import time
import jwt

import requests
from datetime import timedelta
from requests.auth import HTTPBasicAuth
from urlparse import urlparse
from django.core.cache import cache


ACCESS_TOKEN_CACHE = 'hipchat-tokens:'


def base_url(url):
    result = urlparse(url)
    return '%s://%s' % (result.scheme, result.netloc)


class OauthClientInvalidError(Exception):

    def __init__(self, client, *args, **kwargs):
        super(OauthClientInvalidError, self).__init__(*args, **kwargs)
        self.client = client


class Tenant(object):

    def __init__(self, id, secret=None, homepage=None,
                 capabilities_url=None, room_id=None, token_url=None,
                 group_id=None, group_name=None, capdoc=None):
        self.id = id
        self.room_id = room_id
        self.secret = secret
        self.group_id = group_id
        self.group_name = group_name
        if homepage is None and capdoc is not None:
            homepage = capdoc['links']['homepage']
        self.homepage = homepage
        if token_url is None and capdoc is not None:
            token_url = capdoc['capabilities']['oauth2Provider']['tokenUrl']
        self.token_url = token_url
        if capabilities_url is None and capdoc is not None:
            capabilities_url = capdoc['links']['self']
        self.capabilities_url = capabilities_url
        if capdoc is not None:
            api_base_url = capdoc['capabilities']['hipchatApiProvider']['url']
        else:
            api_base_url = capabilities_url.rsplit('/', 1)[0]
        self.api_base_url = api_base_url
        self.installed_from = self.token_url \
            and base_url(self.token_url) or None

    def to_dict(self):
        return {
            'id': self.id,
            'secret': self.secret,
            'room_id': self.room_id,
            'group_id': self.group_id,
            'group_name': self.group_name,
            'homepage': self.homepage,
            'token_url': self.token_url,
            'capabilities_url': self.capabilities_url,
        }

    @staticmethod
    def from_dict(data):
        return Tenant(**data)

    @property
    def id_query(self):
        return {'id': self.id}

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
