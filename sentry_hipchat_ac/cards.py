# -*- coding: utf-8 -*-
from django.utils.html import escape


ICON = 'https://s3.amazonaws.com/f.cl.ly/items/0X2q0W011B1i1m2D140m/sentry-icon.png'
ICON2X = 'https://s3.amazonaws.com/f.cl.ly/items/0X2q0W011B1i1m2D140m/sentry-icon.png'
ICON_SM = 'https://beta.getsentry.com/_static/sentry/images/favicon.ico'

COLORS = {
    'ALERT': 'red',
    'ERROR': 'red',
    'WARNING': 'yellow',
    'INFO': 'green',
    'DEBUG': 'purple',
}


def make_event_notification(group, event, tenant, new=True, event_target=False):
    project = event.project
    level = group.get_level_display().upper()

    link = group.get_absolute_url()
    if event_target:
        link = '%s/events/%s/' % (
            link.rstrip('/'),
            event.id
        )

    color = COLORS.get(level, 'purple')

    title = '%sSentry %s Event' % (
        new and 'New ' or '',
        level.title(),
    )

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
        if key.startswith('sentry:'):
            key = key.split(':', 1)[1]
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
            attr['value']['style'] = 'lozenge-success'
        attributes.append(attr)

    description = '%s. Event has been seen %s time%s. First seen %s%s.' % (
        group.get_level_display().title() + ' in Sentry',
        group.times_seen,
        group.times_seen != 1 and 's' or '',
        group.first_seen.strftime('%Y-%m-%d'),
        group.first_release and ' (%s)' % group.first_release.short_version or '',
    )

    card = {
        'style': 'application',
        'url': link,
        'id': 'sentry/%s' % event.id,
        'title': event.error(),
        'description': ''.join(description),
        'images': {},
        'icon': {
            'url': ICON,
            'url@2x': ICON2X,
        },
        'metadata': {
            'event': str(event.id),
            'sentry_message_type': 'event',
        },
        'attributes': attributes,
        'activity': {
            'html': '''
            <p>
            <a href="%(link)s">
                <img src="%(icon_sm)s" style="width: 16px; height: 16px">
                <strong>%(title)s</strong></a>
            <p><a href="%(link)s"><em>%(err)s</em></a>
            <p>
                <strong>Project:</strong>
                <a href="%(project_link)s">%(project)s</a>&nbsp;
                <strong>Culprit:</strong>
                 %(culprit)s
            ''' % {
                'title': title,
                'icon': ICON,
                'icon_sm': ICON_SM,
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


def make_subscription_update_notification(new=None, removed=None):
    bits = ['The project subscriptions for this room were updated. ']

    def _proj(project):
        return '<strong>%s</strong>' % escape(project.name)

    if new:
        if len(new) == 1:
            bits.append('New project: %s. ' % _proj(new[0]))
        else:
            bits.append('New projects: %s. ' %
                        ', '.join(_proj(x) for x in new))
    if removed:
        if len(removed) == 1:
            bits.append('Removed project: %s' % _proj(removed[0]))
        else:
            bits.append('Removed projects: %s' %
                        ', '.join(_proj(x) for x in removed))
    return {
        'message': ' '.join(bits).strip(),
        'color': 'green',
        'notify': False,
    }


def make_generic_notification(text, color=None, notify=False):
    return {
        'message': escape(text),
        'color': color,
        'notify': notify,
    }
