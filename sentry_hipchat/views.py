import json
from django.views.generic import View
from django.core.urlresolvers import reverse
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt


from .utils import JsonResponse, ac_absolute_uri


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

        print 'INIT', data
        return HttpResponse('', status=201)

    def delete(self, request, oauth_id):
        print 'DELETE', oauth_id
        return HttpResponse('', status=201)
