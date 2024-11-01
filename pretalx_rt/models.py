from django.db import models


class RtSettings(models.Model):
    event = models.OneToOneField(
        to="event.Event",
        on_delete=models.CASCADE,
        related_name="pretalx_rt_settings",
    )
    some_setting = models.CharField(max_length=10, default="A")
