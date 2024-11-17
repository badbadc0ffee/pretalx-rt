from django.db import models
from django.utils.translation import gettext_lazy as _


class Ticket(models.Model):
    id = models.PositiveIntegerField(
        primary_key=True,
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
