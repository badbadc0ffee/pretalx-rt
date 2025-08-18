import logging
from datetime import timedelta

from django.db.models.signals import pre_save
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
from .rt_sync import (
    create_rt_mail,
    create_rt_mail_ticket,
    create_rt_submission_ticket,
    is_rt_enabled,
    needs_sync,
    pretalx_rt_pull,
    pretalx_rt_push,
    requestors,
    get_rt_client,
)

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
    """Periodically pull updates from RT for existing tickets.

    Processes tickets in order of last sync time, stopping after 1 minute
    to avoid long-running tasks.
    """
    logger.debug("Starting periodic RT ticket sync")
    start = now()

    for ticket in Ticket.objects.exclude(submission__isnull=True).order_by(
        "sync_timestamp"
    ):
        if now() - start > timedelta(minutes=1):
            logger.debug("Periodic sync time limit reached")
            return

        event = ticket.submission.event
        if not is_rt_enabled(event):
            continue

        if needs_sync(ticket, event):
            pretalx_rt_pull(event, ticket)


@receiver(submission_state_change)
def pretalx_rt_submission_state_change(sender, submission, old_state, user, **kwargs):
    """Handle submission state changes by creating or updating RT tickets.

    Creates a new RT ticket if none exists, otherwise updates the existing one.
    """
    logger.info(f"Submission state change: {submission.code} > {submission.state}")

    if not is_rt_enabled(sender):
        return

    ticket = getattr(submission, "rt_ticket", None)
    if ticket is None:
        ticket = create_rt_submission_ticket(sender, submission)
    pretalx_rt_push(sender, ticket)


@receiver(queuedmail_pre_send)
def pretalx_rt_queuedmail_pre_send(sender, mail, **kwargs):
    """Handle outgoing mail by creating RT tickets and replies.

    If the mail is related to a submission, uses or creates that submission's ticket.
    Otherwise creates a new standalone mail ticket.
    """
    logger.debug("Processing outgoing mail")

    if not is_rt_enabled(sender):
        return

    ticket = None

    # Try to get or create submission-related ticket
    if mail.submissions.count() == 1:
        submission = mail.submissions.first()
        ticket = getattr(submission, "rt_ticket", None)
        if ticket is None:
            ticket = create_rt_submission_ticket(sender, submission)

    # Create standalone mail ticket if no submission ticket exists
    if ticket is None:
        ticket = create_rt_mail_ticket(sender, mail)

    create_rt_mail(sender, ticket, mail)


@receiver(pre_save, sender=Submission)
def pretalx_rt_submission_pre_save(sender, instance, **kwargs):
    """Update RT ticket when submission is saved.

    Only processes existing submissions that have RT tickets and RT enabled.
    """
    if not instance.pk:
        return

    if not is_rt_enabled(instance.event):
        return

    if ticket := getattr(instance, "rt_ticket", None):
        pretalx_rt_push(instance.event, ticket)
