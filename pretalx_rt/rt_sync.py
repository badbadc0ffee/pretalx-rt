import logging

from django.utils.timezone import now
from django_scopes import scope
from pretalx.celery_app import app
from pretalx.event.models import Event
from pretalx.mail.enums import QueuedMailStates
from rt.rest2 import Attachment, Rt

from .models import EventSettings, Ticket


class RTSync:
    def __init__(self, event, user=None):
        self.event = event
        self.settings = EventSettings.objects.get(event=event)
        self.logger = logging.getLogger(__name__)
        user_settings = (
            user.rt_settings.filter(event=event).first() if user else None
        )
        token = (
            user_settings.rest_auth_token
            if user_settings and user_settings.rest_auth_token
            else self.settings.rest_auth_token
        )
        self.rt = Rt(
            url=self.settings.rest_api_url,
            token=token,
        )

    def get_queues(self):
        try:
            queues = self.rt.get_all_queues()
            return [q.get("Name") for q in queues or [] if "Name" in q]
        except Exception as e:
            self.logger.error(f"Failed to fetch RT queues: {e}")
            return []

    def get_custom_fields(self):
        try:
            queue_data = self.rt.get_queue(self.settings.queue)
            ticket_custom_fields = queue_data.get("TicketCustomFields", [])
            return [cf.get("name") for cf in ticket_custom_fields or [] if "name" in cf]
        except Exception as e:
            self.logger.error(f"Failed to fetch custom fields: {e}")
            return []

    def create_submission_ticket(self, submission):
        """Create a new RT ticket for a submission."""
        self.logger.info(f"Creating RT ticket for submission {submission.code}")

        try:
            rt_id = self.rt.create_ticket(
                queue=self.settings.queue,
                subject=submission.title,
                Requestor=self.requestors(
                    speaker.user for speaker in submission.speakers.select_related("user")
                ),
                Status=self.settings.initial_status,
                Owner="Nobody",
                CustomFields={
                    self.settings.custom_field_id: submission.code,
                    self.settings.custom_field_state: submission.state,
                },
            )

            ticket = Ticket(event=self.event, rt_id=rt_id, submission=submission)
            self.pull(ticket)
            return ticket
        except Exception as e:
            self.logger.error(f"Failed to create RT ticket: {e}")
            return None

    def create_mail_ticket(self, mail):
        """Create a new RT ticket for a standalone mail."""
        self.logger.info("Creating RT ticket for standalone mail")

        try:
            rt_id = self.rt.create_ticket(
                queue=self.settings.queue,
                subject=mail.subject,
                Requestor=self.requestors(mail.to_users.all()),
                Status=self.settings.initial_status,
                Owner="Nobody",
            )

            ticket = Ticket(event=self.event, rt_id=rt_id)
            self.pull(ticket)
            return ticket
        except Exception as e:
            self.logger.error(f"Failed to create RT ticket: {e}")
            return None

    def add_mail_to_ticket(self, ticket, mail):
        """Add a mail as a reply to an RT ticket."""
        self.logger.info(f"Adding mail to RT #{ticket.rt_id}")
        old_ticket = self.rt.get_ticket(ticket.rt_id)

        try:
            mail.state = QueuedMailStates.SENDING
            mail.save(update_fields=["state"])

            self.rt.edit_ticket(
                ticket.rt_id,
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

            html = self.settings.is_mail_html
            self.rt.reply(
                ticket.rt_id,
                content=mail.text_html if html else mail.text,
                content_type="text/html" if html else "text/plain",
                attachments=attachments,
            )

            mail.mark_sent()
            ticket.mails.add(mail.id)
            ticket.save()

        except Exception as e:
            mail.error_data = {"error": str(e), "type": type(e).__name__}
            mail.error_timestamp = now()
            mail.save(update_fields=["error_data", "error_timestamp"])
            self.logger.error(f"Failed to add mail to RT ticket #{ticket.rt_id}: {e}")

        finally:
            self.rt.edit_ticket(
                ticket.rt_id,
                Requestor=old_ticket["Requestor"],
                Subject=old_ticket["Subject"],
                Status=old_ticket["Status"],
            )

    def add_comment_to_ticket(self, ticket, comment):
        """Add a comment to an RT ticket."""
        self.logger.info(f"Adding comment to RT #{ticket.rt_id}")
        old_ticket = self.rt.get_ticket(ticket.rt_id)
        from pretalx.common.templatetags.rich_text import rich_text

        try:
            self.rt.comment(
                ticket.rt_id,
                content=rich_text(comment.text),
                content_type="text/html",
            )
        finally:
            self.rt.edit_ticket(
                ticket.rt_id,
                Requestor=old_ticket["Requestor"],
                Subject=old_ticket["Subject"],
                Status=old_ticket["Status"],
            )

    def push(self, ticket):
        """Push updates from pretalx to RT ticket."""
        if not ticket.submission:
            return

        self.logger.info(f"Pushing updates to RT #{ticket.rt_id}")

        try:
            self.rt.edit_ticket(
                ticket.rt_id,
                Subject=ticket.submission.title,
                Requestor=self.requestors(
                    speaker.user for speaker in ticket.submission.speakers.select_related("user")
                ),
                CustomFields={
                    self.settings.custom_field_id: ticket.submission.code,
                    self.settings.custom_field_state: ticket.submission.state,
                },
            )
        except Exception as e:
            # Unfortunately, even if the update fails because of missing permissions,
            # RT still returns a 200 OK response, so we have to check the result.
            self.logger.error(f"Failed to push RT ticket #{ticket.rt_id}: {e}")
            return
        ticket_pull_task.apply_async(
            kwargs={"event_id": self.event.pk, "ticket_id": ticket.pk}
        )

    def pull(self, ticket):
        """Pull updates from RT ticket to pretalx."""
        self.logger.info(f"Pulling updates from RT #{ticket.rt_id}")
        try:
            rt_ticket = self.rt.get_ticket(ticket.rt_id)
        except Exception as e:
            self.logger.error(f"Failed to pull RT ticket #{ticket.rt_id}: {e}")
            return

        ticket.subject = rt_ticket["Subject"]
        ticket.status = rt_ticket["Status"]
        ticket.queue = rt_ticket["Queue"]["Name"]

        ticket.sync_timestamp = now()
        ticket.save()

    def requestors(self, users):
        """Format user information for RT requestors field."""
        return [f"{user.name.replace('@', '(at)')} <{user.email}>" for user in users]

    @staticmethod
    def get_custom_field(rt_ticket, field_name):
        """Extract a custom field value from an RT ticket dict."""
        for field in rt_ticket.get("CustomFields", []):
            if field.get("name") == field_name:
                values = field.get("values")
                if values:
                    return values[0]
        return None

    def sync_queue(self):
        """Sync RT queue to Pretalx tickets, creating submission links if valid."""
        queue_name = self.settings.queue
        self.logger.info(f"Starting sync of RT queue '{queue_name}'")

        submissions_by_code = {
            s.code: s for s in self.event.submissions.prefetch_related("speakers").all()
        }

        existing_tickets_by_rt = {
            t.rt_id: t
            for t in Ticket.objects.filter(event=self.event).select_related(
                "submission"
            )
        }
        existing_tickets_by_submission = {
            t.submission_id: t
            for t in existing_tickets_by_rt.values()
            if t.submission_id
        }

        tickets = list(self.rt.search(queue_name))
        total = len(tickets)
        new_tickets = 0
        updated_tickets = 0

        for rt_ticket in tickets:
            pretalx_id = self.get_custom_field(rt_ticket, self.settings.custom_field_id)
            if not pretalx_id:
                self.logger.debug(f"Skipping RT #{rt_ticket['id']} (no Submission)")
                continue

            submission = submissions_by_code.get(pretalx_id)
            if not submission:
                self.logger.warning(
                    f"Skipping RT #{rt_ticket['id']}: Submission '{pretalx_id}' not found"
                )
                continue

            if submission.id in existing_tickets_by_submission:
                ticket = existing_tickets_by_submission[submission.id]
                if ticket.rt_id == int(rt_ticket["id"]):
                    self.logger.debug(
                        f"Skipping RT #{rt_ticket['id']}: Submission '{pretalx_id}' already linked."
                    )
                else:
                    self.logger.warning(
                        f"Skipping RT #{rt_ticket['id']}: Submission '{pretalx_id}' already linked to RT #{ticket.rt_id}."
                    )
                continue

            ticket, created = Ticket.objects.update_or_create(
                rt_id=rt_ticket["id"],
                defaults={"event": self.event, "submission": submission},
            )
            if created:
                new_tickets += 1
                self.logger.info(
                    f"Created RT #{rt_ticket['id']} for Submission '{submission.code}'"
                )
            else:
                updated_tickets += 1
                self.logger.info(
                    f"Updated RT #{rt_ticket['id']} with Submission '{submission.code}'"
                )

            self.push(ticket)

        self.logger.info(
            f"Synced {total} tickets of queue '{queue_name}': {updated_tickets} updated, {new_tickets} new."
        )


@app.task(bind=True, name="pretalx_rt.ticket_pull_task")
def ticket_pull_task(self, event_id: int, ticket_id: int):
    event = Event.objects.get(id=event_id)
    with scope(event=event):
        RTSync(event).pull(Ticket.objects.get(id=ticket_id))


@app.task(bind=True, name="pretalx_rt.ticket_push_task")
def ticket_push_task(self, event_id: int, ticket_id: int):
    event = Event.objects.get(id=event_id)
    with scope(event=event):
        RTSync(event).push(Ticket.objects.get(id=ticket_id))

