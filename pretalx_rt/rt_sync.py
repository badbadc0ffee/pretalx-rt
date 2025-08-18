import logging

from django.utils.timezone import now
from pretalx.celery_app import app
from pretalx.event.models import Event
from pretalx.person.models import User
from rt.rest2 import Attachment, Rt

from .models import Ticket


class RTSync:
    def __init__(self, event):
        self.event = event
        self.logger = logging.getLogger(__name__)
        self.rt = Rt(
            url=event.settings.rt_url + "REST/2.0/",
            token=event.settings.rt_rest_api_key,
        )

    def create_submission_ticket(self, submission):
        """Create a new RT ticket for a submission."""
        self.logger.info(f"Creating RT ticket for submission {submission.code}")

        id = self.rt.create_ticket(
            queue=self.event.settings.rt_queue,
            subject=submission.title,
            Requestor=self.requestors(submission.speakers.all()),
            Status=self.event.settings.rt_initial_status,
            Owner="Nobody",
            CustomFields={
                self.event.settings.rt_custom_field_id: submission.code,
                self.event.settings.rt_custom_field_state: submission.state,
            },
        )

        ticket = Ticket(id=id, submission=submission)
        self.pull(ticket)
        return ticket

    def create_mail_ticket(self, mail):
        """Create a new RT ticket for a standalone mail."""
        self.logger.info("Creating RT ticket for standalone mail")

        id = self.rt.create_ticket(
            queue=self.event.settings.rt_queue,
            subject=mail.subject,
            Requestor=self.requestors(mail.to_users.all()),
            Status=self.event.settings.rt_initial_status,
            Owner="Nobody",
        )

        ticket = Ticket(id=id)
        self.pull(ticket)
        return ticket

    def add_mail_to_ticket(self, ticket, mail):
        """Add a mail as a reply to an RT ticket."""
        self.logger.info(f"Adding mail to RT ticket {ticket.id}")
        old_ticket = self.rt.get_ticket(ticket.id)

        try:
            self.rt.edit_ticket(
                ticket.id,
                Requestor=self.requestors(mail.to_users.all()),
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

            html = self.event.settings.rt_mail_html
            self.rt.reply(
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
            self.rt.edit_ticket(
                ticket.id,
                Requestor=old_ticket["Requestor"],
                Subject=old_ticket["Subject"],
                Status=old_ticket["Status"],
            )

    def push(self, ticket):
        """Push updates from pretalx to RT ticket."""
        if not ticket.submission:
            return

        self.logger.info(f"Pushing updates to RT ticket {ticket.id}")

        self.rt.edit_ticket(
            ticket.id,
            Subject=ticket.submission.title,
            Requestor=self.requestors(ticket.submission.speakers.all()),
            CustomFields={
                self.event.settings.rt_custom_field_id: ticket.submission.code,
                self.event.settings.rt_custom_field_state: ticket.submission.state,
            },
        )
        ticket_pull_task.apply_async(
            kwargs={"event_id": self.event.pk, "ticket_id": ticket.pk}
        )

    def pull(self, ticket):
        """Pull updates from RT ticket to pretalx."""
        self.logger.info(f"Pulling updates from RT ticket {ticket.id}")
        rt_ticket = self.rt.get_ticket(ticket.id)

        ticket.subject = rt_ticket["Subject"]
        ticket.status = rt_ticket["Status"]
        ticket.queue = rt_ticket["Queue"]["Name"]

        for requestor in rt_ticket["Requestor"]:
            for user in User.objects.filter(email=requestor["id"]):
                ticket.users.add(user.id)

        ticket.sync_timestamp = now()
        ticket.save()

    def requestors(self, users):
        """Format user information for RT requestors field."""
        return [f"{user.name.replace('@', '(at)')} <{user.email}>" for user in users]


@app.task(bind=True, name="pretalx_rt.ticket_pull_task")
def ticket_pull_task(self, event_id: int, ticket_id: int):
    RTSync(Event.objects.get(id=event_id)).pull(Ticket.objects.get(id=ticket_id))


@app.task(bind=True, name="pretalx_rt.ticket_push_task")
def ticket_push_task(self, event_id: int, ticket_id: int):
    RTSync(Event.objects.get(id=event_id)).push(Ticket.objects.get(id=ticket_id))
