from django import forms
from django.utils.translation import gettext_lazy as _
from pretalx.common.forms.mixins import ReadOnlyFlag
from pretalx.common.forms.renderers import TabularFormRenderer
from pretalx.common.forms.widgets import TextInputWithAddon
from pretalx.mail.models import QueuedMail
from pretalx.submission.models import Submission

from .models import EventSettings, Ticket, UserSettings
from .rt_sync import RTSync


class SettingsForm(forms.ModelForm):
    new_auth_token = forms.CharField(
        label=_("Auth Token"),
        required=False,
        widget=forms.PasswordInput(attrs={"placeholder": "1-23-45678 ... 45"}),
        help_text=_("Authorization token for Request Tracker REST 2.0 API."),
    )
    new_auth_token_repeat = forms.CharField(
        label=_("Auth Token (again)"),
        required=False,
        widget=forms.PasswordInput(),
    )

    def clean(self):
        data = super().clean()
        new_auth_token = self.cleaned_data.get("new_auth_token")
        new_auth_token_repeat = self.cleaned_data.get("new_auth_token_repeat")
        if new_auth_token:
            if new_auth_token == new_auth_token_repeat:
                if new_auth_token == "-":
                    new_auth_token = ""
                data["rest_auth_token"] = new_auth_token
                self.changed_data.append("rest_auth_token")
            else:
                self.add_error("new_auth_token_repeat", "Auth tokens do not match.")
        return data

    def save(self):
        if "rest_auth_token" in self.changed_data:
            self.instance.rest_auth_token = self.cleaned_data.get("rest_auth_token")
        return super().save()


class EventSettingsForm(ReadOnlyFlag, SettingsForm):
    def __init__(self, *args, event, **kwargs):
        self.instance, created = EventSettings.objects.get_or_create(event=event)
        if key := self.instance.rest_auth_token:
            self.declared_fields["new_auth_token"].widget.attrs["placeholder"] = (
                key[:10] + " ... " + key[-2:]
            )
        super().__init__(*args, **kwargs, instance=self.instance)
        queues = RTSync(event=event).get_queues()
        if not queues:
            queues = [event.rt_settings.queue or "Default"]
            self.fields[
                "queue"
            ].help_text += " <i class='fa fa-warning text-warning' aria-hidden='true'></i> No RT queues accessible. Please check your RT permissions."
            self.fields["queue"].widget.attrs["readonly"] = True
            self.fields["initial_status"].widget.attrs["readonly"] = True
        self.fields["queue"].choices = [(q, q) for q in queues]
        custom_fields = RTSync(event=event).get_custom_fields()
        if not custom_fields:
            custom_fields = [
                event.rt_settings.custom_field_id,
                event.rt_settings.custom_field_state,
            ]
            self.fields[
                "custom_field_id"
            ].help_text += " <i class='fa fa-warning text-warning' aria-hidden='true'></i> No custom fields accessible. Please check your RT permissions."
            self.fields[
                "custom_field_state"
            ].help_text += " <i class='fa fa-warning text-warning' aria-hidden='true'></i> No custom fields accessible. Please check your RT permissions."
            self.fields["custom_field_id"].widget.attrs["readonly"] = True
            self.fields["custom_field_state"].widget.attrs["readonly"] = True
        self.fields["custom_field_id"].choices = [(q, q) for q in custom_fields]
        self.fields["custom_field_state"].choices = [(q, q) for q in custom_fields]

    queue = forms.ChoiceField(
        label=_("Queue"),
        choices=[],
        required=True,
    )
    custom_field_id = forms.ChoiceField(
        label=_("ID Field"),
        help_text=_("Custom field in RT to store reference to pretalx ID."),
    )
    custom_field_state = forms.ChoiceField(
        label=_("State Field"),
        help_text=_("Custom field in RT to store pretalx state."),
    )

    class Meta:
        model = EventSettings
        exclude = ["event", "rest_auth_token"]
        widgets = {
            "sync_interval": TextInputWithAddon(addon_after=_("minutes")),
        }


class UserSettingsForm(SettingsForm):
    def __init__(self, event, user, *args, **kwargs):
        self.instance, created = UserSettings.objects.get_or_create(
            event=event, user=user
        )
        super().__init__(*args, **kwargs, instance=self.instance)
        self.fields["new_auth_token"].help_text = _(
            "Personal authorization token for Request Tracker REST 2.0 API."
        )
        key = self.instance.rest_auth_token
        self.fields["new_auth_token"].widget.attrs["placeholder"] = (
            (key[:10] + " ... " + key[-2:])
            if key
            else _("Leave empty to use the event token.")
        )

    class Meta:
        model = UserSettings
        exclude = ["event", "user", "rest_auth_token"]


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
