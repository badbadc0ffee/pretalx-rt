import logging
from datetime import timedelta

from django.dispatch import receiver
from django.urls import reverse
from django.utils.timezone import now
from pretalx.common.signals import (
    minimum_interval,
    periodic_task,
    register_data_exporters,
)
from pretalx.mail.signals import queuedmail_pre_send
from pretalx.orga.signals import nav_event_settings
from pretalx.person.models import User
from pretalx.submission.signals import submission_state_change
from rt.rest2 import Attachment, Rt

from .models import Ticket

logger = logging.getLogger(__name__)

try:
    from pretalx.mail.signals import html_after_mail_badge
except ImportError:
    from pretalx.common.signals import EventPluginSignal

    html_after_mail_badge = EventPluginSignal()
    logger.warn("'html_after_mail_badge' is not available in this pretalx version.")
try:
    from pretalx.mail.signals import html_below_mail_subject
except ImportError:
    from pretalx.common.signals import EventPluginSignal

    html_below_mail_subject = EventPluginSignal()
    logger.warn("'html_below_mail_subject' is not available in this pretalx version.")
try:
    from pretalx.submission.signals import html_below_submission_form
except ImportError:
    from pretalx.common.signals import EventPluginSignal

    html_below_submission_form = EventPluginSignal()
    logger.warn(
        "'html_below_submission_form' is not available in this pretalx version."
    )
try:
    from pretalx.submission.signals import html_below_submission_link
except ImportError:
    from pretalx.common.signals import EventPluginSignal

    html_below_submission_link = EventPluginSignal()
    logger.warn(
        "'html_below_submission_link' is not available in this pretalx version."
    )


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


@receiver(periodic_task)
@minimum_interval(minutes_after_success=5)
def pretalx_rt_periodic_sync(sender, **kwargs):
    logger.info("periodic sync")
    for ticket in Ticket.objects.all():
        if ticket.submission is not None:
            event = ticket.submission.event
            if "pretalx_rt" in event.plugin_list and (
                ticket.sync_timestamp is None
                or (
                    now() - ticket.sync_timestamp
                    > timedelta(minutes=int(event.settings.rt_sync_interval))
                )
            ):
                pretalx_rt_sync(event, ticket)


@receiver(register_data_exporters, dispatch_uid="exporter_rt")
def pretalx_rt_data_exporter(sender, **kwargs):
    logger.info("exporter registration")
    from .exporter import Exporter

    return Exporter


@receiver(html_after_mail_badge)
def pretalx_rt_html_after_mail_badge(sender, request, mail, **kwargs):
    result = ""
    for ticket in mail.rt_tickets.all():
        result += '<i class="fa fa-check-square-o" title="Request Tracker"></i> '
        result += f'<a href="{sender.settings.rt_url}Ticket/Display.html?id={ticket.id}">{ticket.id}</a> '
    return result


@receiver(html_below_mail_subject)
def pretalx_rt_html_below_mail_subject(sender, request, mail, **kwargs):
    result = ""
    for ticket in mail.rt_tickets.all():
        result += '<i class="fa fa-check-square-o" title="Request Tracker"></i> '
        result += f'<a href="{sender.settings.rt_url}Ticket/Display.html?id={ticket.id}">{ticket.id}</a>: '
        result += f"<small>{ticket.subject} ({ticket.status} in queue {ticket.queue})</small> "
    return result


@receiver(html_below_submission_form)
def pretalx_rt_html_below_submission_form(sender, request, submission, **kwargs):
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


@receiver(html_below_submission_link)
def pretalx_rt_html_below_submission_link(sender, request, submission, **kwargs):
    result = ""
    if hasattr(submission, "rt_ticket"):
        result += f'<a href="{sender.settings.rt_url}Ticket/Display.html?id={submission.rt_ticket.id}" class="dropdown-item" role="menuitem" tabindex="-1">'
        result += f'<i class="fa fa-check-square-o"></i> Request Tracker ({submission.rt_ticket.id})'
        result += "</a>"
    return result


@receiver(submission_state_change)
def pretalx_rt_submission_state_change(sender, submission, old_state, user, **kwargs):
    logger.info(f"submission state change hook: {submission.code} > {submission.state}")
    ticket = None
    if hasattr(submission, "rt_ticket"):
        ticket = submission.rt_ticket
    if ticket is None:
        ticket = create_rt_submission_ticket(sender, submission)
    pretalx_rt_sync(sender, ticket)


@receiver(queuedmail_pre_send)
def pretalx_rt_queuedmail_pre_send(sender, mail, **kwargs):
    logger.info("queued mail pre send hook")
    event = sender
    ticket = None
    if mail.submissions.count() == 1:
        submission = mail.submissions.first()
        ticket = None
        if hasattr(submission, "rt_ticket"):
            ticket = submission.rt_ticket
        if ticket is None:
            ticket = create_rt_submission_ticket(event, submission)
    if ticket is None:
        ticket = create_rt_mail_ticket(event, mail)
    create_rt_mail(event, ticket, mail)


def create_rt_submission_ticket(event, submission):
    logger.info(f"create RT ticket for submission {submission.code}")
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
        content=f"New pretalx submission {submission.code}.",
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
    ticket.submission = submission
    pretalx_rt_sync(event, ticket)
    return ticket


def create_rt_mail_ticket(event, mail):
    logger.info("create RT ticket not related to a specific submission")
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
    pretalx_rt_sync(event, ticket)
    return ticket


def create_rt_mail(event, ticket, mail):
    logger.info(f"send mail via RT ticket {ticket.id}")
    rt = Rt(
        url=event.settings.rt_url + "REST/2.0/",
        token=event.settings.rt_rest_api_key,
    )
    old_ticket = rt.get_ticket(ticket.id)
    try:
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


def pretalx_rt_sync(event, ticket):
    logger.info(f"update RT ticket {ticket.id}")
    rt = Rt(
        url=event.settings.rt_url + "REST/2.0/",
        token=event.settings.rt_rest_api_key,
    )
    if ticket.submission is not None:
        rt.edit_ticket(
            ticket.id,
            Subject=ticket.submission.title,
            Requestor=[
                f"{user.name} <{user.email}>"
                for user in ticket.submission.speakers.all()
            ],
            CustomFields={
                event.settings.rt_custom_field_id: ticket.submission.code,
                event.settings.rt_custom_field_state: ticket.submission.state,
            },
        )
    rt_ticket = rt.get_ticket(ticket.id)
    ticket.subject = rt_ticket["Subject"]
    ticket.status = rt_ticket["Status"]
    ticket.queue = rt_ticket["Queue"]["Name"]
    for requestor in rt_ticket["Requestor"]:
        for user in list(User.objects.filter(email=requestor["id"])):
            ticket.users.add(user.id)
    ticket.sync_timestamp = now()
    ticket.save()
