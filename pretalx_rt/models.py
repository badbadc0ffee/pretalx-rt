from django.db import models
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _


class EventSettings(models.Model):
    event = models.OneToOneField(
        to="event.Event",
        on_delete=models.CASCADE,
        related_name="rt_settings",
    )
    base_url = models.URLField(
        verbose_name=_("Base URL"),
        help_text=_("Base URL for Request Tracker."),
    )
    rest_auth_token = models.CharField(
        verbose_name=_("API Token"),
        help_text=_("Authorization token for Request Tracker REST 2.0 API."),
    )
    queue = models.CharField(
        verbose_name=_("Queue"),
        help_text=_("RT Queue for this event"),
    )
    initial_status = models.CharField(
        verbose_name=_("Initial state"),
        help_text=_("Initial RT status for newly created tickets."),
        default="resolved",
    )
    custom_field_id = models.CharField(
        verbose_name=_("Custom field for pretalx ID"),
        help_text=_("Custom field in RT to store reference to pretalx ID."),
        default="Pretalx ID",
    )
    custom_field_state = models.CharField(
        verbose_name=_("Custom field for pretalx state"),
        help_text=_("Custom field in RT to store pretalx state."),
        default="Pretalx State",
    )
    is_mail_html = models.BooleanField(
        verbose_name=_("Send HTML mails"),
        help_text=_("Let RT send out mails in HTML markup."),
        default=True,
    )
    sync_interval = models.IntegerField(
        verbose_name=_("Sync interval"),
        help_text=_("Minimum interval in minutes to sync RT tickets."),
        default=30,
    )

    @property
    def rest_api_url(self):
        return self.base_url + "REST/2.0/"


class Ticket(models.Model):
    event = models.ForeignKey(
        to="event.Event",
        on_delete=models.CASCADE,
        related_name="rt_tickets",
    )
    rt_id = models.PositiveIntegerField(
        verbose_name=_("Ticket ID"),
        help_text=_("The numeric ID of the ticket in RT."),
    )
    subject = models.CharField(
        max_length=200,
        verbose_name=_("Subject"),
        help_text=_("The subject of the ticket in RT."),
    )
    status = models.CharField(
        max_length=64,
        verbose_name=_("Status"),
        help_text=_("The status of the ticket in RT."),
    )
    queue = models.CharField(
        max_length=200,
        verbose_name=_("Queue"),
        help_text=_("The queue of the ticket in RT."),
    )
    mails = models.ManyToManyField(
        to="mail.QueuedMail",
        related_name="rt_tickets",
    )
    submission = models.OneToOneField(
        to="submission.Submission",
        related_name="rt_ticket",
        on_delete=models.SET_NULL,
        null=True,
    )
    sync_timestamp = models.DateTimeField(
        auto_now_add=True,
    )

    @property
    def url(self):
        return f"{self.event.rt_settings.base_url}Ticket/Display.html?id={self.rt_id}"

    @property
    def status_class(self):
        if self.status == "new":
            return "text-info"
        elif self.status == "open":
            return "text-info"
        elif self.status == "resolved":
            return "text-success"
        elif self.status == "rejected":
            return "text-danger"
        elif self.status == "stalled":
            return "text-danger"
        else:
            return ""

    @property
    @mark_safe
    def status_text(self):
        if self.status == "new":
            return "<i class='fa fa-inbox'></i>&nbsp;&nbsp;new"
        elif self.status == "open":
            return "<i class='fa fa-question-circle'></i>&nbsp;&nbsp;open"
        elif self.status == "stalled":
            return "<i class='fa fa-warning'></i>&nbsp;&nbsp;stalled"
        elif self.status == "resolved":
            return "<i class='fa fa-check-circle'></i>&nbsp;&nbsp;resolved"
        elif self.status == "rejected":
            return "<i class='fa fa-ban'></i>&nbsp;&nbsp;rejected"
        else:
            return self.status
