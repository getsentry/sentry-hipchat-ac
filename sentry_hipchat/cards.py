# -*- coding: utf-8 -*-
from django.utils.html import escape


COLORS = {
    'ALERT': 'red',
    'ERROR': 'red',
    'WARNING': 'yellow',
    'INFO': 'green',
    'DEBUG': 'purple',
}


def make_event_notification(group, event, tenant):
    project = event.project
    level = group.get_level_display().upper()
    link = group.get_absolute_url()
    color = COLORS.get(level, 'purple')

    # Legacy message
    message = (
        '[%(level)s]%(project_name)s %(message)s '
        '[<a href="%(link)s">view</a>]'
    ) % {
        'level': escape(level),
        'project_name': '<strong>%s</strong>' % escape(project.name),
        'message': escape(event.error()),
        'link': escape(link),
    }

    attributes = []
    for key, value in event.tags:
        attr = {
            'label': key,
            'value': {'label': value}
        }
        if key == 'level':
            attr_color = {
                'critical': 'lozenge-error',
                'fatal': 'lozenge-error',
                'error': 'lozenge-error',
                'warning': 'lozenge-current',
                'debug': 'lozenge-moved',
            }.get(value.lower())
            if attr_color is not None:
                attr['value']['style'] = attr_color
        elif key == 'release':
            attr['value']['style'] = 'lozenge-new'

    card = {
        'style': 'application',
        'url': link,
        'id': 'sentry/%s' % event.id,
        'title': event.error(),
        'description': 'An error ocurred.',
        'images': {},
        'icon': {
            'url': 'https://beta.getsentry.com/_static/sentry/images/favicon.ico'
        },
        'metadata': {
            'event': str(event.id),
        },
        'attributes': attributes,
        'activity': {
            'html': '''
            <p>
            <a href="%(link)s">
                <img src="https://beta.getsentry.com/_static/sentry/images/favicon.ico" style="width: 16px; height: 16px">
                <strong>New Sentry Event</strong></a>
            <p><a href="%(link)s"><code>%(err)s</code></a>
            <p><strong>Project:</strong>
                <span class="aui-icon aui-icon-small aui-iconfont-devtools-submodule"></span>
                <a href="%(project_link)s">%(project)s</a>
            <p><strong>Culprit:</strong>
            <em>%(culprit)s</em>
            ''' % {
                'link': escape(link),
                'err': escape(event.error()),
                'project': escape(project.name),
                'project_link': escape(project.get_absolute_url()),
                'culprit': escape(event.culprit),
            }
        },
    }

    return {
        'color': color,
        'message': message,
        'format': 'html',
        'card': card,
        'notify': True,
    }
