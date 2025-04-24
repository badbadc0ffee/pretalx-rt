pretalx RT plugin
==========================

This is a plugin for `pretalx`_.

This plugin allows you to use the RT issue tracker for communication with
speakers.

The plugin will be used to send out all notifications that would normally be
sent out as mail via RT instead of SMTP - with the exception of mails that
will be sent out to reset passwords. Those will still be sent out via SMTP
directly.

Information regarding the corresponding RT ticket will be included in the
submission and speaker forms in the pretalx orga interface. The plugin will
keep track of the RT ticket related to each submission and will reuse that
ticket for all notifications that are sent out to the speakers.

Development setup
-----------------

1. Make sure that you have a working `pretalx development setup`_.

2. Clone this repository, eg to ``local/pretalx-rt``.

3. Activate the virtual environment you use for pretalx development.

4. Run ``pip install -e .`` within this directory to register this application with pretalx's plugin registry.

5. Run ``make`` within this directory to compile translations.

6. Restart your local pretalx server. This plugin should show up in the plugin list shown on startup in the console.
   You can now use the plugin from this repository for your events by enabling it in the 'plugins' tab in the settings.

This plugin has CI set up to enforce a few code style rules. To check locally, you need these packages installed::

    pip install flake8 flake8-bugbear isort black

To check your plugin for rule violations, run::

    black --check .
    isort -c .
    flake8 .

You can auto-fix some of these issues by running::

    isort .
    black .


License
-------

Copyright 2025 Florian Moesch

Released under the terms of the Apache License 2.0


.. _pretalx: https://github.com/pretalx/pretalx
.. _pretalx development setup: https://docs.pretalx.org/en/latest/developer/setup.html
