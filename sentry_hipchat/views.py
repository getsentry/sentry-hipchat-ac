import json
import requests
from functools import update_wrapper
from django.views.generic import View
from django.core.urlresolvers import reverse
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt


from .utils import JsonResponse, ac_absolute_uri
from .models import Tenant, Context


'''
https://c00cc4c7.ngrok.io/hipchat/
'''


class ConfigView(View):

    def get(self, request):
        return HttpResponse('''<!doctype html>
<html>
  <head>
    <script src="https://www.hipchat.com/atlassian-connect/all.js"></script>
    <link rel="stylesheet" href="https://www.hipchat.com/atlassian-connect/all.css">
  </head>
  <body>
    Hello World!
  </body>
</html>
        ''')


class DescriptorView(View):

    def get(self, request):
        return JsonResponse({
            'key': 'hipchat-sentry',
            'name': 'Sentry for Hipchat',
            'description': 'Sentry integration for Hipchat.',
            'links': {
                'self': ac_absolute_uri(reverse('sentry-hipchat-descriptor')),
            },
            'capabilities': {
                'installable': {
                    'allowRoom': True,
                    'allowGlobal': False,
                    'callbackUrl': ac_absolute_uri(reverse(
                        'sentry-hipchat-installable')),
                },
                'hipchatApiConsumer': {
                    'scopes': ['send_notification'],
                },
                'configurable': {
                    'url': ac_absolute_uri(reverse('sentry-hipchat-config')),
                },
                'webhook': [
                    {
                        'event': 'room_message',
                        'url': ac_absolute_uri(reverse('sentry-hipchat-room-message')),
                        'pattern': 'sentry[,:]',
                        'authentication': 'jwt',
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

        Tenant.objects.create(
            id=data['oauthId'],
            room_id=room_id,
            secret=data['oauthSecret'],
            capdoc=capdoc,
        )

        return HttpResponse('', status=201)

    def delete(self, request, oauth_id):
        tenant = Tenant.objects.get(pk=oauth_id)
        if tenant is not None:
            tenant.delete()
        return HttpResponse('', status=201)


def webhook(f):
    @csrf_exempt
    def new_f(request):
        data = json.loads(request.body) or {}
        context = Context.for_request(request, data)
        return f(request, context, data)
    return update_wrapper(new_f, f)


@webhook
def on_room_message(request, context, data):
    context.send_notification('Hello World!')
    return HttpResponse('', status=204)
