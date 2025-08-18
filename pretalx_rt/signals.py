import logging
from datetime import timedelta

from django.db.models.signals import m2m_changed, post_save
from django.dispatch import receiver
from django.template import loader
from django.urls import reverse
from django.utils.timezone import now
from pretalx.common.signals import (
    minimum_interval,
    periodic_task,
    register_data_exporters,
)
from pretalx.mail.signals import queuedmail_pre_send
from pretalx.orga.signals import mail_form, nav_event_settings, submission_form
from pretalx.person.models import User
from pretalx.submission.models import Submission
from pretalx.submission.signals import submission_state_change
from rt.rest2 import Attachment, Rt

from .forms import RTForm
from .models import Ticket
from .rt_sync import RTSync

logger = logging.getLogger(__name__)

# UI Signal Handlers
# These handlers manage the user interface integration of RT with pretalx


@receiver(nav_event_settings)
def pretalx_rt_settings(sender, request, **kwargs):
    """Add RT settings to the event settings navigation.

    Only shows the RT settings link if the user has permission to update the event.
    """
    if not request.user.has_perm("event.update_event", request.event):
        return []

    return [
        {
            "label": "RT",
            "url": reverse(
                "plugins:pretalx_rt:settings",
                kwargs={"event": request.event.slug},
            ),
            "active": request.resolver_match.url_name == "plugins:pretalx_rt:settings",
        }
    ]


@receiver(register_data_exporters, dispatch_uid="exporter_rt")
def pretalx_rt_data_exporter(sender, **kwargs):
    """Register the RT data exporter for pretalx."""
    logger.debug("Registering RT data exporter")
    from .exporter import Exporter

    return Exporter


@receiver(mail_form)
def pretalx_rt_mail_form(sender, request, instance, **kwargs):
    """Add RT ticket forms to mail forms.

    Returns a list of RT ticket forms for all tickets associated with the instance.
    """
    return [
        RTForm(instance=ticket, event=sender) for ticket in instance.rt_tickets.all()
    ]


@receiver(submission_form)
def pretalx_rt_submission_form(sender, request, instance, **kwargs):
    """Add RT ticket form to submission forms.

    Returns a form for the RT ticket if the submission has one.
    """
    if hasattr(instance, "rt_ticket"):
        return [RTForm(instance=instance.rt_ticket, event=sender)]
    return []


# Optional SamAware Integration
try:
    from samaware.signals import submission_html

    @receiver(submission_html)
    def samaware_submission_html(sender, request, submission, **kwargs):
        """Add RT ticket information to SamAware submission view.

        Renders the RT ticket information in the SamAware template if available.
        """
        if not hasattr(submission, "rt_ticket"):
            return None

        template = loader.get_template("pretalx_rt/samaware.html")
        return template.render(
            {
                "event": sender,
                "tickets": [submission.rt_ticket],
            },
            None,
        )

except ImportError:
    pass


# Sync Signal Handlers
# These handlers manage the synchronization between pretalx and RT


@receiver(periodic_task)
@minimum_interval(minutes_after_success=5)
def pretalx_rt_periodic_pull(sender, **kwargs):
    """Periodically pull updates from RT for existing tickets."""
    logger.debug("Starting periodic RT ticket sync")

    if not is_enabled(sender):
        return

    start = now()

    for ticket in Ticket.objects.exclude(submission__isnull=True).order_by(
        "sync_timestamp"
    ):
        if now() - start > timedelta(minutes=1):
            logger.debug("Periodic sync time limit reached")
            return

        event = ticket.submission.event

        rt_sync = RTSync(event)

        if rt_sync.needs_sync(ticket):
            rt_sync.pull(ticket)


@receiver(submission_state_change)
def pretalx_rt_submission_state_change(sender, submission, old_state, user, **kwargs):
    """Handle submission state changes by creating or updating RT tickets."""
    logger.info(f"Submission state change: {submission.code} > {submission.state}")

    if not is_enabled(sender):
        return

    rt_sync = RTSync(sender)

    ticket = getattr(submission, "rt_ticket", None)
    if ticket is None:
        ticket = rt_sync.create_submission_ticket(submission)
    rt_sync.push(ticket)


@receiver(queuedmail_pre_send)
def pretalx_rt_queuedmail_pre_send(sender, mail, **kwargs):
    """Handle outgoing mail by creating RT tickets and replies."""
    logger.debug("Processing outgoing mail")

    if not is_enabled(sender):
        return

    rt_sync = RTSync(sender)
    ticket = None

    # Try to get or create submission-related ticket
    if mail.submissions.count() == 1:
        submission = mail.submissions.first()
        ticket = getattr(submission, "rt_ticket", None)
        if ticket is None:
            ticket = rt_sync.create_submission_ticket(submission)

    # Create standalone mail ticket if no submission ticket exists
    if ticket is None:
        ticket = rt_sync.create_mail_ticket(mail)

    rt_sync.add_mail_to_ticket(ticket, mail)


@receiver(post_save, sender=Submission)
def pretalx_rt_submission_changed(sender, instance, **kwargs):
    """Update RT ticket when submission is saved."""
    if not is_enabled(instance.event):
        return

    if not instance.pk:
        return

    rt_sync = RTSync(instance.event)
    if ticket := getattr(instance, "rt_ticket", None):
        rt_sync.push(ticket)


@receiver(m2m_changed, sender=Submission.speakers.through)
def pretalx_rt_submission_speaker_changed(sender, instance, action, **kwargs):
    """Handle changes to speakers of a submission by updating the RT ticket."""
    if not is_enabled(instance.event):
        return

    if action != "post_save":
        return

    rt_sync = RTSync(instance.event)

    if ticket := getattr(instance, "rt_ticket", None):
        rt_sync.push(ticket)


def is_enabled(event):
    """Check if RT integration is enabled for the event."""
    return "pretalx_rt" in event.plugin_list


def needs_sync(ticket, event):
    """Check if a ticket needs to be synced based on the sync interval."""
    if ticket.sync_timestamp is None:
        return True

    interval = timedelta(minutes=int(event.settings.rt_sync_interval))
    return (now() - ticket.sync_timestamp) > interval
