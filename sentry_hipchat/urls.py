from django.conf.urls import patterns, url
from . import views


urlpatterns = patterns('',
    url('^$', views.DescriptorView.as_view()),
    url('^addon/descriptor$', views.DescriptorView.as_view(),
        name='sentry-hipchat-descriptor'),
    url('^addon/installable$', views.InstallableView.as_view(),
        name='sentry-hipchat-installable'),
    url('^addon/installable/(?P<oauth_id>[^/]+)$',
        views.InstallableView.as_view()),
    url('^configuration/$', views.ConfigView.as_view(),
        name='sentry-hipchat-config'),

    url('^event/room-message$', views.on_room_message,
        name='sentry-hipchat-room-message')
)
