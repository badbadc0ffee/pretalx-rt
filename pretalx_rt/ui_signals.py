import logging

from django.dispatch import receiver
from django.urls import reverse
from pretalx.common.signals import register_data_exporters
from pretalx.mail.signals import mail_form_html
from pretalx.orga.signals import nav_event_settings
from pretalx.submission.signals import submission_form_html, submission_form_link

logger = logging.getLogger(__name__)


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


@receiver(register_data_exporters, dispatch_uid="exporter_rt")
def pretalx_rt_data_exporter(sender, **kwargs):
    logger.info("exporter registration")
    from .exporter import Exporter

    return Exporter


# @receiver(html_after_mail_badge)
def pretalx_rt_html_after_mail_badge(sender, request, mail, **kwargs):
    result = ""
    for ticket in mail.rt_tickets.all():
        result += '<i class="fa fa-check-square-o" title="Request Tracker"></i> '
        result += f'<a href="{sender.settings.rt_url}Ticket/Display.html?id={ticket.id}">{ticket.id}</a> '
    return result


@receiver(mail_form_html)
def pretalx_rt_mail_form_html(sender, request, mail, **kwargs):
    if not request.user.has_perm("orga.view_mails", request.event):
        return None
    result = ""
    for ticket in mail.rt_tickets.all():
        result += '<div class="form-group row">'
        result += '<label class="col-md-3 col-form-label">'
        result += "Request Tracker"
        result += "</label>"
        result += '<div class="col-md-9">'
        result += '<div class="pt-2">'
        result += '<i class="fa fa-check-square-o"></i> '
        result += f'<a href="{sender.settings.rt_url}Ticket/Display.html?id={ticket.id}">{ticket.id}</a> : '
        result += f"{ticket.subject}"
        result += f'<small class="form-text text-muted">{ticket.status} in queue {ticket.queue}</small>'
        result += "</div>"
        result += "</div>"
        result += "</div>"
    return result


@receiver(submission_form_html)
def pretalx_rt_submission_form_html(sender, request, submission, **kwargs):
    result = ""
    if hasattr(submission, "rt_ticket"):
        ticket = submission.rt_ticket
        result += '<div class="form-group row">'
        result += '<label class="col-md-3 col-form-label">'
        result += "Request Tracker"
        result += "</label>"
        result += '<div class="col-md-9">'
        result += '<div class="pt-2">'
        result += '<i class="fa fa-check-square-o"></i> '
        result += f'<a href="{sender.settings.rt_url}Ticket/Display.html?id={ticket.id}">{ticket.id}</a> : '
        result += f"{ticket.subject}"
        result += f'<small class="form-text text-muted">{ticket.status} in queue {ticket.queue}</small>'
        result += "</div>"
        result += "</div>"
        result += "</div>"
    return result


@receiver(submission_form_link)
def pretalx_rt_submission_form_link(sender, request, submission, **kwargs):
    result = ""
    if hasattr(submission, "rt_ticket"):
        result += f'<a href="{sender.settings.rt_url}Ticket/Display.html?id={submission.rt_ticket.id}" class="dropdown-item" role="menuitem" tabindex="-1">'
        result += f'<i class="fa fa-check-square-o"></i> Request Tracker ({submission.rt_ticket.id})'
        result += "</a>"
    return result
