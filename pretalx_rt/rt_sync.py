import logging
from datetime import timedelta
from django.utils.timezone import now
from pretalx.person.models import User
from rt.rest2 import Attachment, Rt
from .models import Ticket

def get_rt_client(event):
    """Create an RT client instance for the given event."""
    return Rt(
        url=event.settings.rt_url + "REST/2.0/",
        token=event.settings.rt_rest_api_key,
    )

def create_rt_submission_ticket(event, submission):
    """Create a new RT ticket for a submission."""
    logger = logging.getLogger(__name__)
    logger.info(f"Creating RT ticket for submission {submission.code}")
    rt = get_rt_client(event)

    id = rt.create_ticket(
        queue=event.settings.rt_queue,
        subject=submission.title,
        Requestor=requestors(submission.speakers.all()),
        Status=event.settings.rt_initial_status,
        Owner="Nobody",
        CustomFields={
            event.settings.rt_custom_field_id: submission.code,
            event.settings.rt_custom_field_state: submission.state,
        },
    )

    ticket = Ticket(id=id, submission=submission)
    pretalx_rt_pull(event, ticket)
    return ticket

def create_rt_mail_ticket(event, mail):
    """Create a new RT ticket for a standalone mail."""
    logger = logging.getLogger(__name__)
    logger.info("Creating RT ticket for standalone mail")
    rt = get_rt_client(event)

    id = rt.create_ticket(
        queue=event.settings.rt_queue,
        subject=mail.subject,
        Requestor=requestors(mail.to_users.all()),
        Status=event.settings.rt_initial_status,
        Owner="Nobody",
    )

    ticket = Ticket(id=id)
    pretalx_rt_pull(event, ticket)
    return ticket

def create_rt_mail(event, ticket, mail):
    """Add a mail as a reply to an RT ticket."""
    logger = logging.getLogger(__name__)
    logger.info(f"Adding mail to RT ticket {ticket.id}")
    rt = get_rt_client(event)
    old_ticket = rt.get_ticket(ticket.id)

    try:
        rt.edit_ticket(
            ticket.id,
            Requestor=requestors(mail.to_users.all()),
            Subject=mail.subject,
        )

        attachments = [
            Attachment(
                file_name=att["name"],
                file_content=att["content"],
                file_type=att["content_type"],
            )
            for att in mail.attachments or []
        ]

        html = event.settings.rt_mail_html
        rt.reply(
            ticket.id,
            content=mail.make_html() if html else mail.make_text(),
            content_type="text/html" if html else "text/plain",
            attachments=attachments,
        )

        mail.sent = now()
        mail.save()
        ticket.mails.add(mail.id)
        ticket.save()

    finally:
        rt.edit_ticket(
            ticket.id,
            Requestor=old_ticket["Requestor"],
            Subject=old_ticket["Subject"],
            Status=old_ticket["Status"],
        )

def pretalx_rt_push(event, ticket):
    """Push updates from pretalx to RT ticket."""
    if not ticket.submission:
        return

    logger = logging.getLogger(__name__)
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
    """Pull updates from RT ticket to pretalx."""
    logger = logging.getLogger(__name__)
    logger.info(f"Pulling updates from RT ticket {ticket.id}")
    rt = get_rt_client(event)
    rt_ticket = rt.get_ticket(ticket.id)

    ticket.subject = rt_ticket["Subject"]
    ticket.status = rt_ticket["Status"]
    ticket.queue = rt_ticket["Queue"]["Name"]

    for requestor in rt_ticket["Requestor"]:
        for user in User.objects.filter(email=requestor["id"]):
            ticket.users.add(user.id)

    ticket.sync_timestamp = now()
    ticket.save()

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