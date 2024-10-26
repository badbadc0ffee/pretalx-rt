from django import forms
from django.utils.translation import gettext_lazy as _
from hierarkey.forms import HierarkeyForm


class RtSettingsForm(HierarkeyForm):
    rt_rest_api_url = forms.URLField(
        label=_("Base URL"),
        widget=forms.URLInput(
            attrs={"placeholder": "https://tracker.example.com/REST/2.0/"}
        ),
        help_text=_("Base URL for Request Tracker API."),
    )

    rt_rest_api_key = forms.CharField(
        label=_("API Token"),
        widget=forms.PasswordInput(
            attrs={"placeholder": "1-23-45678901234567890123456789012345"},
            render_value=True,
        ),
        help_text=_("Autohorization token for Request Tracker API."),
    )

    rt_queue = forms.CharField(
        label=_("Queue"),
        widget=forms.TextInput(),
        help_text=_("RT Queue for this event."),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        event = kwargs.get("obj")
        if not event.settings.rt_queue:
            self.fields["rt_queue"].initial = event.slug
