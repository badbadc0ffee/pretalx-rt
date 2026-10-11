from django.db import models
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

STATUS_TEXT = {
    "new": "<i class='fa fa-inbox'></i>&nbsp;&nbsp;new",
    "open": "<i class='fa fa-question-circle'></i>&nbsp;&nbsp;open",
    "stalled": "<i class='fa fa-warning'></i>&nbsp;&nbsp;stalled",
    "resolved": "<i class='fa fa-check-circle'></i>&nbsp;&nbsp;resolved",
    "rejected": "<i class='fa fa-ban'></i>&nbsp;&nbsp;rejected",
}


class EventSettings(models.Model):
    event = models.OneToOneField(
        to="event.Event", on_delete=models.CASCADE, related_name="rt_settings"
    )
    base_url = models.URLField(
        verbose_name=_("Base URL"), help_text=_("Base URL for Request Tracker.")
    )
    rest_auth_token = models.CharField(
        verbose_name=_("Auth Token"),
        help_text=_("Authorization token for Request Tracker REST 2.0 API."),
    )
    queue = models.CharField(
        verbose_name=_("Queue"), help_text=_("RT Queue for this event.")
    )
    initial_status = models.CharField(
        verbose_name=_("Initial state"),
        help_text=_("Initial RT status for newly created tickets."),
        default="resolved",
    )
    custom_field_id = models.CharField(
        verbose_name=_("ID Field"),
        help_text=_("Custom field in RT to store reference to pretalx ID."),
        default="Pretalx ID",
    )
    custom_field_state = models.CharField(
        verbose_name=_("State Field"),
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
        help_text=_("Minimum interval to sync RT tickets."),
        default=30,
    )

    def __str__(self):
        return f"EventSettings(event_id={self.event_id})"

    @classmethod
    def for_event(cls, event):
        """Return the settings of an event (or of an event id), or None."""
        return cls.objects.filter(event=event).first()

    @property
    def rest_api_url(self):
        return self.base_url + "REST/2.0/"


class UserSettings(models.Model):
    event = models.ForeignKey(to="event.Event", on_delete=models.CASCADE)
    user = models.ForeignKey(
        to="person.User", on_delete=models.CASCADE, related_name="rt_settings"
    )
    rest_auth_token = models.CharField(
        verbose_name=_("Auth Token"),
        help_text=_("Authorization token for Request Tracker REST 2.0 API."),
    )

    def __str__(self):
        return f"UserSettings(event_id={self.event_id}, user_id={self.user_id})"


class Ticket(models.Model):
    event = models.ForeignKey(
        to="event.Event", on_delete=models.CASCADE, related_name="rt_tickets"
    )
    rt_id = models.PositiveIntegerField(
        verbose_name=_("Ticket ID"), help_text=_("The numeric ID of the ticket in RT.")
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
    mails = models.ManyToManyField(to="mail.QueuedMail", related_name="rt_tickets")
    submission = models.OneToOneField(
        to="submission.Submission",
        related_name="rt_ticket",
        on_delete=models.SET_NULL,
        null=True,
    )
    sync_timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Ticket(rt_id={self.rt_id})"

    @classmethod
    def for_submission(cls, submission):
        return cls.objects.filter(submission=submission).first()

    @property
    def url(self):
        settings = EventSettings.for_event(self.event_id)
        if settings is None:
            return ""
        return f"{settings.base_url}Ticket/Display.html?id={self.rt_id}"

    @property
    def status_class(self):
        if self.status == "new" or self.status == "open":
            return "text-info"
        if self.status == "resolved":
            return "text-success"
        if self.status == "rejected" or self.status == "stalled":
            return "text-danger"
        return ""

    @property
    def status_text(self):
        if self.status in STATUS_TEXT:
            return mark_safe(STATUS_TEXT[self.status])  # noqa: S308 -- static markup
        return escape(self.status)
