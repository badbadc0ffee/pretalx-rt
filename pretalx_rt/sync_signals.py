import logging
from datetime import timedelta

from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.utils.timezone import now
from pretalx.common.signals import minimum_interval, periodic_task
from pretalx.mail.signals import queuedmail_pre_send
from pretalx.person.models import User
from pretalx.submission.models import Submission
from pretalx.submission.signals import submission_state_change
from rt.rest2 import Attachment, Rt

from .models import Ticket

logger = logging.getLogger(__name__)


@receiver(periodic_task)
@minimum_interval(minutes_after_success=5)
def pretalx_rt_periodic_pull(sender, **kwargs):
    logger.info("periodic pull")
    start = now()
    for ticket in Ticket.objects.exclude(submission__isnull=True).order_by(
        "sync_timestamp"
    ):
        if now() - start > timedelta(minutes=1):
            return
        event = ticket.submission.event
        if "pretalx_rt" in event.plugin_list and (
            ticket.sync_timestamp is None
            or (
                now() - ticket.sync_timestamp
                > timedelta(minutes=int(event.settings.rt_sync_interval))
            )
        ):
            pretalx_rt_pull(event, ticket)


@receiver(submission_state_change)
def pretalx_rt_submission_state_change(sender, submission, old_state, user, **kwargs):
    logger.info(f"submission state change hook: {submission.code} > {submission.state}")
    ticket = getattr(submission, "rt_ticket", None)
    if ticket is None:
        ticket = create_rt_submission_ticket(sender, submission)
    pretalx_rt_push(sender, ticket)


@receiver(queuedmail_pre_send)
def pretalx_rt_queuedmail_pre_send(sender, mail, **kwargs):
    logger.info("queued mail pre send hook")
    ticket = None
    if mail.submissions.count() == 1:
        submission = mail.submissions.first()
        ticket = getattr(submission, "rt_ticket", None)
        if ticket is None:
            ticket = create_rt_submission_ticket(sender, submission)
    if ticket is None:
        ticket = create_rt_mail_ticket(sender, mail)
    create_rt_mail(sender, ticket, mail)


@receiver(pre_save, sender=Submission)
def pretalx_rt_submission_pre_save(sender, instance, **kwargs):
    if instance.pk:
        if "pretalx_rt" in instance.event.plugin_list and (
            ticket := getattr(instance, "rt_ticket", None)
        ):
            pretalx_rt_push(instance.event, ticket)


# ------------------------------


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
        Requestor=requestors(submission.speakers.all()),
        Status=status,
        Owner="Nobody",
        CustomFields={
            event.settings.rt_custom_field_id: submission.code,
            event.settings.rt_custom_field_state: submission.state,
        },
    )
    ticket = Ticket(id, submission=submission)
    pretalx_rt_pull(event, ticket)
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
        Requestor=requestors(mail.to_users.all()),
        Subject=mail.subject,
        Status=status,
        Owner="Nobody",
    )
    ticket = Ticket(id)
    pretalx_rt_pull(event, ticket)
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
            Requestor=requestors(mail.to_users.all()),
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


def pretalx_rt_push(event, ticket):
    logger.info(f"push RT ticket {ticket.id}")
    rt = Rt(
        url=event.settings.rt_url + "REST/2.0/",
        token=event.settings.rt_rest_api_key,
    )
    if ticket.submission is not None:
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
    logger.info(f"pull RT ticket {ticket.id}")
    rt = Rt(
        url=event.settings.rt_url + "REST/2.0/",
        token=event.settings.rt_rest_api_key,
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


def requestors(users):
    return [f"{user.name.replace('@', '(at)')} <{user.email}>" for user in users]
    # return ",".join(
    #     f"{user.name.replace('@', '(at)')} <{user.email}>" for user in users
    # )
