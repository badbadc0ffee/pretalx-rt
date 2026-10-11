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
submission and mail forms in the pretalx orga interface. The plugin will
keep track of the RT ticket related to each submission and will reuse that
ticket for all notifications that are sent out to the speakers.

Features
--------

- **Mails via RT:** outgoing mails are sent as replies on RT tickets. A mail
  related to exactly one submission uses that submission's ticket; any other
  mail gets its own ticket. Requestors are set from the recipients.
- **One ticket per submission:** a ticket is created automatically when a
  non-draft submission is saved, its speakers change, or a comment is added.
- **Comments:** comments on a submission are added to its RT ticket as comments.
- **Two-way sync:**

  - Title, speakers (as requestors), submission code and state are pushed to
    RT whenever the submission changes.
  - Ticket subject, status and queue are pulled back from RT periodically and
    when a submission form is opened, at most once per sync interval.

- **Existing tickets:** tickets in the configured queue that carry a
  submission code in the ID custom field are linked to the matching
  submission.
- **Orga interface:** RT ticket information is shown in the submission and mail
  forms.
- **Export:** a CSV exporter (``rt.csv``) lists the tickets.

Configuration
-------------

Enable the plugin in the plugin settings of your event, then open the new
"RT" entry in the event settings.

Event settings (require permission to update the event):

- *Base URL*: base URL of your Request Tracker. The REST 2.0 API is expected
  at ``<base URL>REST/2.0/``, so include the trailing slash.
- *Auth Token*: RT REST 2.0 token used for all actions by default.
- *Queue*: the RT queue for this event.
- *Initial state*: status of newly created tickets (default ``resolved``).
- *ID Field* / *State Field*: names of the RT ticket custom fields that store
  the pretalx submission code and state (defaults ``Pretalx ID`` and
  ``Pretalx State``). They must exist on the queue.
- *Send HTML mails*: send mails to RT as HTML instead of plain text.
- *Sync interval*: minimum number of minutes between syncs of a ticket
  (default 30).

User settings: each user can store their own RT auth token for an event. If
set, it is used for that user's actions (e.g. comments), so they show up in RT
under their name. Otherwise the event token is used.

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
