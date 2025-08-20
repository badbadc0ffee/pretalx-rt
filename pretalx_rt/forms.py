from django import forms
from django.utils.translation import gettext_lazy as _
from pretalx.common.forms.renderers import TabularFormRenderer
from pretalx.common.forms.widgets import TextInputWithAddon
from pretalx.mail.models import QueuedMail
from pretalx.submission.models import Submission

from .models import EventSettings, Ticket


class SettingsForm(forms.ModelForm):
    new_auth_token = forms.CharField(
        label=_("Auth Token"),
        required=False,
        widget=forms.PasswordInput(attrs={"placeholder": "1-23-45678 ... 45"}),
        help_text=_(
            "Authorization token for Request Tracker REST 2.0 API. Leave empty to keep current token."
        ),
    )
    new_auth_token_repeat = forms.CharField(
        label=_("Auth Token (again)"),
        required=False,
        widget=forms.PasswordInput(),
    )

    def __init__(self, *args, event, **kwargs):
        self.instance, _ = EventSettings.objects.get_or_create(event=event)
        if key := self.instance.rest_auth_token:
            self.declared_fields["new_auth_token"].widget.attrs["placeholder"] = (
                key[:10] + " ... " + key[-2:]
            )
        super().__init__(*args, **kwargs, instance=self.instance)

    def clean(self):
        data = super().clean()
        new_auth_token = self.cleaned_data.get("new_auth_token")
        new_auth_token_repeat = self.cleaned_data.get("new_auth_token_repeat")
        if new_auth_token:
            if new_auth_token == new_auth_token_repeat:
                data["rest_auth_token"] = new_auth_token
                self.changed_data.append("rest_auth_token")
            else:
                self.add_error("new_auth_token_repeat", "Auth tokens do not match.")
        return data

    def save(self):
        if "rest_auth_token" in self.changed_data:
            self.instance.rest_auth_token = self.cleaned_data.get("rest_auth_token")
        return super().save()

    class Meta:
        model = EventSettings
        exclude = ["event", "rest_auth_token"]
        widgets = {
            "sync_interval": TextInputWithAddon(addon_after=_("minutes")),
        }


class RTRenderer(TabularFormRenderer):
    form_template_name = "pretalx_rt/form.html"


class RTForm(forms.ModelForm):
    default_renderer = RTRenderer

    mails = forms.ModelChoiceField(queryset=QueuedMail.objects.none())
    submission = forms.ModelChoiceField(queryset=Submission.all_objects.none())

    class Meta:
        model = Ticket
        exclude = ["id"]

    def __init__(self, *args, **kwargs):
        self.event = kwargs.pop("event")
        super().__init__(*args, **kwargs)
        self.fields["mails"].queryset = QueuedMail.objects.filter(event=self.event)
        self.fields["submission"].queryset = Submission.objects.filter(event=self.event)
        for fieldname in self.fields:
            self.fields[fieldname].disabled = True
