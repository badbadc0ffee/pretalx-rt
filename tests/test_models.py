from datetime import timedelta

import pytest
from django.utils import timezone
from django_scopes import scopes_disabled

from pretalx.event.models import Event

from pretalx_rt.models import EventSettings, Ticket, UserSettings
from pretalx_rt.signals import needs_sync


@pytest.fixture
def plain_ticket(event):
    return Ticket.objects.create(event=event, rt_id=7, status="new")


@pytest.mark.django_db
def test_ticket_url(plain_ticket, event_settings):
    assert plain_ticket.url == "https://rt.example.com/Ticket/Display.html?id=7"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("status", "css_class"),
    (
        ("new", "text-info"),
        ("open", "text-info"),
        ("resolved", "text-success"),
        ("rejected", "text-danger"),
        ("stalled", "text-danger"),
        ("something else", ""),
    ),
)
def test_ticket_status_class(plain_ticket, status, css_class):
    plain_ticket.status = status
    assert plain_ticket.status_class == css_class


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("status", "icon"),
    (
        ("new", "fa-inbox"),
        ("open", "fa-question-circle"),
        ("stalled", "fa-warning"),
        ("resolved", "fa-check-circle"),
        ("rejected", "fa-ban"),
    ),
)
def test_ticket_status_text_for_known_status(plain_ticket, status, icon):
    plain_ticket.status = status
    assert plain_ticket.status_text == (
        f"<i class='{'fa ' + icon}'></i>&nbsp;&nbsp;{status}"
    )


@pytest.mark.django_db
def test_ticket_status_text_escapes_unknown_status(plain_ticket):
    plain_ticket.status = "<b>custom</b>"
    assert plain_ticket.status_text == "&lt;b&gt;custom&lt;/b&gt;"


@pytest.mark.django_db
def test_model_string_representations(event, event_settings, plain_ticket, orga_user):
    user_settings = UserSettings.objects.create(
        event=event, user=orga_user, rest_auth_token="x"
    )
    assert str(event_settings) == f"EventSettings(event_id={event.pk})"
    assert str(plain_ticket) == "Ticket(rt_id=7)"
    assert str(user_settings) == (
        f"UserSettings(event_id={event.pk}, user_id={orga_user.pk})"
    )


@pytest.mark.django_db
def test_needs_sync_depends_on_interval(plain_ticket, event_settings):
    event_settings.sync_interval = 30
    event_settings.save()
    assert not needs_sync(plain_ticket)

    Ticket.objects.filter(pk=plain_ticket.pk).update(
        sync_timestamp=timezone.now() - timedelta(minutes=31)
    )
    plain_ticket.refresh_from_db()
    assert needs_sync(plain_ticket)


@pytest.mark.django_db
def test_needs_sync_without_timestamp(plain_ticket, event_settings):
    plain_ticket.sync_timestamp = None
    assert needs_sync(plain_ticket)


@pytest.mark.django_db
def test_event_settings_for_event(event, event_settings, organiser):
    with scopes_disabled():
        other = Event.objects.create(
            name="Other Event",
            slug="other",
            email="event@example.org",
            date_from=event.date_from,
            date_to=event.date_to,
            organiser=organiser,
        )
    assert EventSettings.for_event(event) == event_settings
    assert EventSettings.for_event(event.pk) == event_settings
    assert EventSettings.for_event(other) is None


@pytest.mark.django_db
def test_ticket_url_without_settings_is_empty(plain_ticket):
    assert plain_ticket.url == ""


@pytest.mark.django_db
def test_needs_sync_is_false_without_settings(plain_ticket):
    plain_ticket.sync_timestamp = None
    assert not needs_sync(plain_ticket)
