"""
sentry_hipchat
~~~~~~~~~~~~~~

:copyright: (c) 2011 by Linovia, see AUTHORS for more details.
:license: BSD, see LICENSE for more details.
"""

try:
    VERSION = __import__('pkg_resources') \
        .get_distribution('sentry_hipchat').version
except Exception, e:
    VERSION = 'unknown'


def _patch_urls():
    from django.conf.urls import include, patterns, url
    from sentry.conf import urls
    urls.urlpatterns = patterns('',
        url('^api/hipchat/', include('sentry_hipchat.urls')),
    ) + urls.urlpatterns


_patch_urls()
del _patch_urls
