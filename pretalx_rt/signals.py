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


# RT Integration Functions
# These functions handle the core RT operations


def get_rt_client(event):
    """Create an RT client instance for the given event.

    Args:
        event: The pretalx event with RT settings.

    Returns:
        rt.rest2.Rt: Configured RT client instance.
    """
    return Rt(
        url=event.settings.rt_url + "REST/2.0/",
        token=event.settings.rt_rest_api_key,
    )


def create_rt_submission_ticket(event, submission):
    """Create a new RT ticket for a submission.

    Args:
        event: The pretalx event
        submission: The submission to create a ticket for

    Returns:
        Ticket: The created ticket instance
    """
    logger.info(f"Creating RT ticket for submission {submission.code}")
    rt = get_rt_client(event)

    id = rt.create_ticket(
        queue=event.settings.rt_queue,
        subject=submission.title,
        Requestor=requestors(submission.speakers.all()),
        Status=event.settings.rt_initial_status,
        Owner=DEFAULT_OWNER,
        CustomFields={
            event.settings.rt_custom_field_id: submission.code,
            event.settings.rt_custom_field_state: submission.state,
        },
    )

    ticket = Ticket(id, submission=submission)
    pretalx_rt_pull(event, ticket)
    return ticket


def create_rt_mail_ticket(event, mail):
    """Create a new RT ticket for a standalone mail.

    Args:
        event: The pretalx event
        mail: The mail to create a ticket for

    Returns:
        Ticket: The created ticket instance
    """
    logger.info("Creating RT ticket for standalone mail")
    rt = get_rt_client(event)

    id = rt.create_ticket(
        queue=event.settings.rt_queue,
        subject=mail.subject,
        Requestor=requestors(mail.to_users.all()),
        Status=event.settings.rt_initial_status,
        Owner="Nobody",
    )

    ticket = Ticket(id)
    pretalx_rt_pull(event, ticket)
    return ticket


def create_rt_mail(event, ticket, mail):
    """Add a mail as a reply to an RT ticket.

    Args:
        event: The pretalx event
        ticket: The ticket to add the mail to
        mail: The mail to add
    """
    logger.info(f"Adding mail to RT ticket {ticket.id}")
    rt = get_rt_client(event)
    old_ticket = rt.get_ticket(ticket.id)

    try:
        # Update ticket metadata for the mail
        rt.edit_ticket(
            ticket.id,
            Requestor=requestors(mail.to_users.all()),
            Subject=mail.subject,
        )

        # Process attachments
        attachments = [
            Attachment(
                file_name=att["name"],
                file_content=att["content"],
                file_type=att["content_type"],
            )
            for att in mail.attachments or []
        ]

        # Send the reply
        html = event.settings.rt_mail_html
        rt.reply(
            ticket.id,
            content=mail.make_html() if html else mail.make_text(),
            content_type="text/html" if html else "text/plain",
            attachments=attachments,
        )

        # Update mail and ticket status
        mail.sent = now()
        mail.save()
        ticket.mails.add(mail.id)
        ticket.save()

    finally:
        # Restore original ticket metadata
        rt.edit_ticket(
            ticket.id,
            Requestor=old_ticket["Requestor"],
            Subject=old_ticket["Subject"],
            Status=old_ticket["Status"],
        )


def pretalx_rt_push(event, ticket):
    """Push updates from pretalx to RT ticket.

    Args:
        event: The pretalx event
        ticket: The ticket to update
    """
    if not ticket.submission:
        return

    logger.info(f"Pushing updates to RT ticket {ticket.id}")
    rt = get_rt_client(event)

    rt.edit_ticket(
        ticket.id,
        Subject=ticket.submission.title,
        Requestor=requestors(ticket.submission.speakers.all()),
        CustomFields={
            event.settings.rt_custom_field_id: ticket.submission.code,
            event.settings.rt_custom_field_state: ticket.submission.state,
        },
    )


def pretalx_rt_pull(event, ticket):
    """Pull updates from RT ticket to pretalx.

    Args:
        event: The pretalx event
        ticket: The ticket to update
    """
    logger.info(f"Pulling updates from RT ticket {ticket.id}")
    rt = get_rt_client(event)
    rt_ticket = rt.get_ticket(ticket.id)

    # Update ticket metadata
    ticket.subject = rt_ticket["Subject"]
    ticket.status = rt_ticket["Status"]
    ticket.queue = rt_ticket["Queue"]["Name"]

    # Update related users
    for requestor in rt_ticket["Requestor"]:
        for user in User.objects.filter(email=requestor["id"]):
            ticket.users.add(user.id)

    ticket.sync_timestamp = now()
    ticket.save()


# Helper Functions


def is_rt_enabled(event) -> bool:
    """Check if RT integration is enabled for the event."""
    return "pretalx_rt" in event.plugin_list


def needs_sync(ticket, event) -> bool:
    """Check if a ticket needs to be synced based on the sync interval."""
    if ticket.sync_timestamp is None:
        return True

    interval = timedelta(minutes=int(event.settings.rt_sync_interval))
    return (now() - ticket.sync_timestamp) > interval


def requestors(users):
    """Format user information for RT requestors field."""
    return [f"{user.name.replace('@', '(at)')} <{user.email}>" for user in users]
