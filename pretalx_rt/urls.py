from django.http import HttpResponseRedirect
from django.urls import path, re_path
from django_scopes import scopes_disabled
from pretalx.event.models.event import SLUG_REGEX
from pretalx.submission.models import Submission

from .views import SettingsView


@scopes_disabled()
def session_redirect(request, code, *args, **kwargs):
    try:
        submission = Submission.objects.get(code__iexact=code)
    except Submission.DoesNotExist:
        return HttpResponseRedirect("/403")
    if request.user.has_perm("orga.view_orga_area", submission.event):
        return HttpResponseRedirect(submission.orga_urls.base.full())
    return HttpResponseRedirect(submission.urls.public.full())


urlpatterns = [
    re_path(
        rf"^orga/event/(?P<event>{SLUG_REGEX})/settings/p/pretalx_rt/$",
        SettingsView.as_view(),
        name="settings",
    ),
    path(
        "goto/<code>",
        session_redirect,
        name="test",
    ),
]
