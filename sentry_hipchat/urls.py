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
    url('^configuration/$', views.configure,
        name='sentry-hipchat-config'),

    url('^sidebar/event-details$', views.event_details,
        name='sentry-hipchat-event-details'),

    url('^event/room-message$', views.on_room_message,
        name='sentry-hipchat-room-message')
)
