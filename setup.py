#!/usr/bin/env python
"""
sentry-hipchat-ac
=================

An extension for Sentry which integrates with HipChat. It will forwards
notifications to an hipchat room.

:copyright: (c) 2011 by the Linovia, see AUTHORS for more details.
:license: BSD, see LICENSE for more details.
"""
from setuptools import setup, find_packages


tests_require = [
    'pytest',
    'mock',
]

install_requires = [
    'sentry>=6.0.0',
    'requests',
    'PyJWT',
]

setup(
    name='sentry-hipchat-ac',
    version='1.0.0',
    author='Sentry',
    author_email='hello@getsentry.com',
    url='http://github.com/getsentry/sentry-hipchat-ac',
    description='A Sentry extension which integrates with HipChat.',
    long_description=__doc__,
    license='BSD',
    packages=find_packages(exclude=['tests']),
    zip_safe=False,
    install_requires=install_requires,
    tests_require=tests_require,
    extras_require={'test': tests_require},
    test_suite='runtests.runtests',
    include_package_data=True,
    entry_points={
        'sentry.apps': [
            'sentry_hipchat_ac = sentry_hipchat_ac',
        ],
        'sentry.plugins': [
            'hipchat_ac = sentry_hipchat_ac.plugin:HipchatNotifier',
         ],
    },
    classifiers=[
        'Framework :: Django',
        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
        'Operating System :: OS Independent',
        'Topic :: Software Development'
    ],
)
