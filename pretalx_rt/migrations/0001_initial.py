# Generated by Django 5.1.3 on 2024-11-13 08:34

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("mail", "0012_queuedmail_submissions"),
        ("submission", "0077_answeroption_position"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Ticket",
            fields=[
                ("id", models.PositiveIntegerField(primary_key=True, serialize=False)),
                ("subject", models.CharField(max_length=200)),
                ("status", models.CharField(max_length=64)),
                ("queue", models.CharField(max_length=200)),
                (
                    "mails",
                    models.ManyToManyField(
                        related_name="rt_tickets", to="mail.queuedmail"
                    ),
                ),
                (
                    "submission",
                    models.OneToOneField(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="rt_ticket",
                        to="submission.submission",
                    ),
                ),
                (
                    "users",
                    models.ManyToManyField(
                        related_name="rt_tickets", to=settings.AUTH_USER_MODEL
                    ),
                ),
            ],
        ),
    ]