from django.db import models
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _


class Ticket(models.Model):
    id = models.PositiveIntegerField(
        primary_key=True,
        verbose_name=_("Ticket ID"),
        help_text=_("The numeric ID of the ticket in RT"),
    )
    subject = models.CharField(
        max_length=200,
        verbose_name=_("Subject"),
        help_text=_("The subject of the ticket in RT"),
    )
    status = models.CharField(
        max_length=64,
        verbose_name=_("Status"),
        help_text=_("The status of the ticket in RT"),
    )
    queue = models.CharField(
        max_length=200,
        verbose_name=_("Queue"),
        help_text=_("The queue of the ticket in RT"),
    )
    users = models.ManyToManyField(
        to="person.User",
        related_name="rt_tickets",
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
