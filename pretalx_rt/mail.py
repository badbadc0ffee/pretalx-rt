import rt.rest2
from django.core.mail.backends.base import BaseEmailBackend
from pretalx.event.models import Event


class RTBackend(BaseEmailBackend):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def send_messages(self, email_messages):
        for message in email_messages:
            event = Event.objects.get(pk=message.extra_headers["X-Pretalx-Event"])
            if "X-Pretalx-RT-Ticket" not in message.extra_headers:
                """38C3 hack in lack of a plugin"""
                new_ticket = {
                    "Requestor": message.to,
                    "Status": "resolved",
                    "Owner": "Nobody",
                }
                c = rt.rest2.Rt(
                    url=event.settings.rt_rest_api_url,
                    token=event.settings.rt_rest_api_key,
                )
                self.ticket_id = c.create_ticket(
                    event.settings.rt_queue,
                    subject=message.subject,
                    content="Ticket automatically created by pretalx",
                    **new_ticket,
                )
