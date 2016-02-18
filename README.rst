sentry-hipchat-ac
=================

An extension for Sentry which integrates with Hipchat.
It will send issues notification to Hipchat.

Install
-------

Install the package via ``pip``::

    pip install https://github.com/getsentry/sentry-hipchat-ac/archive/master.zip
    
Run migrations after installation is complete

    sentry upgrade

Development
-----------

.. code::

  git clone git@github.com:getsentry/sentry-hipchat-ac.git
  workon sentry
  make


Create a tunnel to localhost using something like https://ngrok.com/download::

    ngrok http 8000

Start Sentry with the following parameters set::

    AC_BASE_URL=https://<xxx>.ngrok.io HTTPS=on sentry runserver


Configuration
-------------

Go to your project's configuration page (Projects -> [Project]) and select the
Hipchat tab. Enter the required credentials and click save changes.

