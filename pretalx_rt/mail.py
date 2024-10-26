import rt.rest2
from django.core.mail.backends.base import BaseEmailBackend
from pretalx.event.models import Event


class RTBackend(BaseEmailBackend):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def send_messages(self, email_messages):
        for message in email_messages:
            event = Event.objects.get(pk=message.extra_headers["X-Pretalx-Event"])
            ticket_id = None
            if "X-Pretalx-RT-Ticket" in message.extra_headers:
                ticket_id = message.extra_headers["X-Pretalx-RT-Ticket"]
            else:
                c = rt.rest2.Rt(
                    url=event.settings.rt_rest_api_url,
                    token=event.settings.rt_rest_api_key,
                )
                ticket_id = c.create_ticket(
                    event.settings.rt_queue,
                    subject=message.subject,
                    content="Ticket automatically created by pretalx",
                    Requestor=message.to,
                    Status="resolved",
                    Owner="Nobody",
                )

            ticket = c.get_ticket(ticket_id)
            try:
                c.edit_ticket(ticket_id, Requestor=message.to, Subject=message.subject)
                c.reply(ticket_id, content=message.body, content_type="text/plain")
            finally:
                c.edit_ticket(
                    ticket_id,
                    Requestor=ticket["Requestor"],
                    Subject=ticket["Subject"],
                    Status=ticket["Status"],
                )
