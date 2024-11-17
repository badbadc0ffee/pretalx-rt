from django import forms
from django.utils.translation import gettext_lazy as _
from hierarkey.forms import HierarkeyForm


class SettingsForm(HierarkeyForm):
    rt_url = forms.URLField(
        label=_("Base URL"),
        widget=forms.URLInput(attrs={"placeholder": "https://tracker.example.com/"}),
        help_text=_("Base URL for Request Tracker."),
    )

    rt_rest_api_key = forms.CharField(
        label=_("API Token"),
        widget=forms.PasswordInput(
            attrs={"placeholder": "1-23-45678901234567890123456789012345"},
            render_value=True,
        ),
        help_text=_("Autohorization token for Request Tracker REST 2.0 API."),
    )

    rt_queue = forms.CharField(
        label=_("Queue"),
        help_text=_("RT Queue for this event."),
    )

    rt_initial_status = forms.CharField(
        label=_("Initial state"),
        help_text=_("Initial RT status for newly created tickets."),
        initial="resolved",
    )

    rt_custom_field_id = forms.CharField(
        label=_("Custom field for pretalx ID"),
        help_text=_("Custom field in RT to store reference to pretalx ID."),
        initial="Pretalx ID",
    )

    rt_custom_field_state = forms.CharField(
        label=_("Custom field for pretalx state"),
        help_text=_("Custom field in RT to store pretalx state."),
        initial="Pretalx State",
    )

    rt_mail_html = forms.BooleanField(
        label=_("Send HTML mails"),
        help_text=_("Let RT send out mails in HTML markup."),
        initial=True,
        required=False,
    )

    rt_sync_interval = forms.IntegerField(
        label=_("Sync interval"),
        help_text=_("Minimum interval in minutes to sync RT tickets."),
        initial=30,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        event = kwargs.get("obj")
        if not event.settings.rt_queue:
            self.fields["rt_queue"].initial = event.slug
