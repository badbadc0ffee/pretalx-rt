from django.contrib import messages
from django.shortcuts import redirect
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from django.views.generic import TemplateView
from django_context_decorator import context
from pretalx.common.views import is_form_bound
from pretalx.common.views.mixins import PermissionRequired

from .forms import EventSettingsForm, UserSettingsForm


class SettingsView(PermissionRequired, TemplateView):
    permission_required = "event.update_event"
    template_name = "pretalx_rt/settings.html"

    def get_success_url(self):
        return self.request.path

    def get_object(self):
        return self.request.event

    def post(self, request, *args, **kwargs):
        if self.event_settings.is_bound and self.event_settings.is_valid():
            self.event_settings.save()
            messages.success(
                self.request, _("The pretalx RT event settings were updated.")
            )
        elif self.user_settings.is_bound and self.user_settings.is_valid():
            self.user_settings.save()
            messages.success(
                self.request, _("The pretalx RT user settings were updated.")
            )
        return redirect(self.get_success_url())

    @context
    @cached_property
    def event_settings(self):
        return EventSettingsForm(
            event=self.request.event,
            data=self.request.POST if is_form_bound(self.request, "event") else None,
        )

    @context
    @cached_property
    def user_settings(self):
        return UserSettingsForm(
            event=self.request.event,
            user=self.request.user,
            data=self.request.POST if is_form_bound(self.request, "user") else None,
        )
