from unittest import mock

import pytest
from django_scopes import scopes_disabled
from pretalx.event.models import Event

from pretalx_rt.models import EventSettings, UserSettings
from pretalx_rt.rt_sync import RTSync


@pytest.fixture
def event_settings(event, event_token):
    return EventSettings.objects.create(
        event=event,
        base_url="https://rt.example.com/",
        rest_auth_token=event_token,
        queue="General",
    )


@pytest.mark.django_db
def test_rtsync_uses_event_token_without_user(event, event_settings, event_token):
    with mock.patch("pretalx_rt.rt_sync.Rt") as rt:
        RTSync(event)
    rt.assert_called_once_with(
        url="https://rt.example.com/REST/2.0/", token=event_token
    )


@pytest.mark.django_db
def test_rtsync_uses_event_token_if_user_has_none(
    event, event_settings, event_token, orga_user
):
    with mock.patch("pretalx_rt.rt_sync.Rt") as rt:
        RTSync(event, orga_user)
    assert rt.call_args.kwargs["token"] == event_token


@pytest.mark.django_db
def test_rtsync_prefers_user_token(event, event_settings, orga_user, user_token):
    UserSettings.objects.create(event=event, user=orga_user, rest_auth_token=user_token)
    with mock.patch("pretalx_rt.rt_sync.Rt") as rt:
        RTSync(event, orga_user)
    assert rt.call_args.kwargs["token"] == user_token


@pytest.mark.django_db
def test_rtsync_ignores_user_token_of_other_event(
    event, event_settings, event_token, orga_user, organiser, other_token
):
    with scopes_disabled():
        other = Event.objects.create(
            name="Other Event",
            slug="other",
            email="event@example.org",
            date_from=event.date_from,
            date_to=event.date_to,
            organiser=organiser,
        )
    UserSettings.objects.create(
        event=other, user=orga_user, rest_auth_token=other_token
    )
    with mock.patch("pretalx_rt.rt_sync.Rt") as rt:
        RTSync(event, orga_user)
    assert rt.call_args.kwargs["token"] == event_token
