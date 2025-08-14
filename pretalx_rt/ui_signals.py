import logging

from django.dispatch import receiver
from django.template import loader
from django.urls import reverse
from pretalx.common.signals import register_data_exporters
from pretalx.orga.signals import mail_form, nav_event_settings, submission_form

from .forms import RTForm

logger = logging.getLogger(__name__)


@receiver(nav_event_settings)
def pretalx_rt_settings(sender, request, **kwargs):
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
    logger.info("exporter registration")
    from .exporter import Exporter

    return Exporter


@receiver(mail_form)
def pretalx_rt_mail_form(sender, request, instance, **kwargs):
    forms = []
    for ticket in instance.rt_tickets.all():
        forms.append(RTForm(instance=ticket, event=sender))
    return forms


@receiver(submission_form)
def pretalx_rt_submission_form(sender, request, instance, **kwargs):
    forms = []
    if hasattr(instance, "rt_ticket"):
        forms.append(RTForm(instance=instance.rt_ticket, event=sender))
    return forms


#@receiver(submission_form_link)
def pretalx_rt_submission_form_link(sender, request, submission, **kwargs):
    result = ""
    if hasattr(submission, "rt_ticket"):
        result += f'<a href="{sender.settings.rt_url}Ticket/Display.html?id={submission.rt_ticket.id}" class="dropdown-item" role="menuitem" tabindex="-1">'
        result += f'<i class="fa fa-check-square-o"></i> Request Tracker ({submission.rt_ticket.id})'
        result += "</a>"
    return result


try:
    from samaware.signals import submission_html

    @receiver(submission_html)
    def samaware_submission_html(sender, request, submission, **kwargs):
        if hasattr(submission, "rt_ticket"):
            tickets = [submission.rt_ticket]
            template = loader.get_template("pretalx_rt/samaware.html")
            context = {
                "event": sender,
                "tickets": tickets,
            }
            return template.render(context, None)
        return None

except ImportError:
    pass
