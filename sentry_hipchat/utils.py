import os
import json
from urlparse import urljoin
from django.http import HttpResponse
from sentry.utils.http import absolute_uri


ac_base = os.environ.get('AC_BASE_URL')


class JsonResponse(HttpResponse):

    def __init__(self, value, status=200):
        HttpResponse.__init__(self, json.dumps(value), status=status,
                              content_type='application/json')


def ac_absolute_uri(path):
    if ac_base is not None:
        return urljoin(ac_base, path)
    return absolute_uri(path)
