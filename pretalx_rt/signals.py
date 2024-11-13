from django.dispatch import receiver
from django.urls import reverse
from django.utils.timezone import now
from rt.rest2 import Attachment, Rt

from pretalx.mail.models import QueuedMail
from pretalx.mail.signals import mail_badge, mail_details, queuedmail_pre_send
from pretalx.orga.signals import nav_event_settings
from pretalx.submission.signals import (
    submission_details,
    submission_link,
    submission_state_change,
)

from .models import Ticket


@receiver(nav_event_settings)
def pretalx_rt_settings(sender, request, **kwargs):
    if not request.user.has_perm("orga.change_settings", request.event):
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


@receiver(mail_badge)
def pretalx_rt_mail_badge(sender, request, mail: QueuedMail, **kwargs):
    result = ""
    for ticket in mail.rt_tickets.all():
        result += '<i class="fa fa-check-square-o" title="Request Tracker"></i> '
        result += f'<a href="{sender.settings.rt_url}Ticket/Display.html?id={ticket.id}">{ticket.id}</a> '
    return result


@receiver(mail_details)
def pretalx_rt_mail_details(sender, request, mail, **kwargs):
    result = ""
    for ticket in mail.rt_tickets.all():
        result += '<i class="fa fa-check-square-o" title="Request Tracker"></i> '
        result += f'<a href="{sender.settings.rt_url}Ticket/Display.html?id={ticket.id}">{ticket.id}</a>: '
        result += f"<small>{ticket.subject} ({ticket.status} in queue {ticket.queue})</small> "
    return result


@receiver(submission_details)
def pretalx_rt_submission_details(sender, request, submission, **kwargs):
    result = ""
    if hasattr(submission, "rt_ticket"):
        result += '<div class="form-group row">'
        result += '<label class="col-md-3 col-form-label">'
        result += "Request Tracker"
        result += "</label>"
        result += '<div class="col-md-9">'
        result += '<div class="pt-2">'
        result += '<i class="fa fa-check-square-o"></i> '
        result += f'<a href="{sender.settings.rt_url}Ticket/Display.html?id={submission.rt_ticket.id}">{submission.rt_ticket.id}</a> : '
        result += f"{submission.rt_ticket.subject}"
        result += f'<small class="form-text text-muted">{submission.rt_ticket.status} in queue {submission.rt_ticket.queue}</small>'
        result += "</div>"
        result += "</div>"
        result += "</div>"
    return result


@receiver(submission_link)
def pretalx_rt_submission_link(sender, request, submission, **kwargs):
    result = ""
    if hasattr(submission, "rt_ticket"):
        result += f'<a href="{sender.settings.rt_url}Ticket/Display.html?id={submission.rt_ticket.id}" class="dropdown-item" role="menuitem" tabindex="-1">'
        result += f'<i class="fa fa-check-square-o"></i> Request Tracker ({submission.rt_ticket.id})'
        result += "</a>"
    return result


@receiver(submission_state_change)
def pretalx_rt_submission_state_change(sender, submission, old_state, user, **kwargs):
    ticket = None
    if hasattr(submission, "rt_ticket"):
        ticket = submission.rt_ticket
    if ticket is None:
        ticket = create_rt_submission_ticket(sender, submission)
    update_rt_pretalx_state(sender, submission, ticket)


@receiver(queuedmail_pre_send)
def pretalx_rt_queuedmail_pre_send(sender, mail, **kwargs):
    ticket = None
    if mail.submissions.count() == 1:
        submission = mail.submissions.first()
        ticket = None
        if hasattr(submission, "rt_ticket"):
            ticket = submission.rt_ticket
        if ticket is None:
            ticket = create_rt_submission_ticket(sender, submission)
    if ticket is None:
        ticket = create_rt_mail_ticket(sender, mail)
    create_rt_mail(sender, ticket, mail)


def create_rt_submission_ticket(event, submission):
    rt = Rt(
        url=event.settings.rt_url + "REST/2.0/",
        token=event.settings.rt_rest_api_key,
    )
    queue = event.settings.rt_queue
    subject = submission.title
    status = event.settings.rt_initial_status
    id = rt.create_ticket(
        queue=queue,
        subject=subject,
        content="New pretalx submission.",
        Requestor=",".join(
            f"{user.name} <{user.email}>" for user in submission.speakers.all()
        ),
        Status=status,
        Owner="Nobody",
        CustomFields={
            event.settings.rt_custom_field_id: submission.code,
            event.settings.rt_custom_field_state: submission.state,
        },
    )
    ticket = Ticket(id)
    ticket.queue = queue
    ticket.subject = subject
    ticket.status = status
    ticket.submission = submission
    ticket.save()
    return ticket


def create_rt_mail_ticket(event, mail):
    rt = Rt(
        url=event.settings.rt_url + "REST/2.0/",
        token=event.settings.rt_rest_api_key,
    )
    queue = event.settings.rt_queue
    subject = mail.subject
    status = event.settings.rt_initial_status
    id = rt.create_ticket(
        queue=queue,
        subject=subject,
        Requestor=",".join(user.email for user in mail.to_users.all()),
        Subject=mail.subject,
        Status=status,
        Owner="Nobody",
    )
    ticket = Ticket(id)
    ticket.queue = queue
    ticket.subject = subject
    ticket.status = status
    ticket.save()
    return ticket


def create_rt_mail(event, ticket, mail):
    rt = Rt(
        url=event.settings.rt_url + "REST/2.0/",
        token=event.settings.rt_rest_api_key,
    )
    old_ticket = rt.get_ticket(ticket.id)
    try:
        ##
        rt.edit_ticket(
            ticket.id,
            Requestor=",".join(user.email for user in mail.to_users.all()),
            Subject=mail.subject,
        )
        attachments = []
        for mail_attachment in mail.attachments or []:
            rt_attachmant = Attachment(
                file_name=mail_attachment["name"],
                file_content=mail_attachment["content"],
                file_type=mail_attachment["content_type"],
            )
            attachments.append(rt_attachmant)
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


def update_rt_pretalx_state(event, submission, ticket):
    rt = Rt(
        url=event.settings.rt_url + "REST/2.0/",
        token=event.settings.rt_rest_api_key,
    )
    rt.edit_ticket(
        ticket.id,
        CustomFields={
            event.settings.rt_custom_field_id: submission.code,
            event.settings.rt_custom_field_state: submission.state,
        },
    )
