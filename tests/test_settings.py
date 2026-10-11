from unittest import mock

import pytest
from django.urls import reverse

from pretalx_rt.models import UserSettings
from pretalx_rt.rt_sync import RTSync

SETTINGS_URL_NAME = "plugins:pretalx_rt:settings"


@pytest.fixture(autouse=True)
def no_rt_access():
    """The settings form queries RT for queues and custom fields."""
    with (
        mock.patch.object(RTSync, "get_queues", return_value=[]),
        mock.patch.object(RTSync, "get_custom_fields", return_value=[]),
    ):
        yield


@pytest.mark.django_db
def test_orga_can_access_settings(orga_client, event):
    response = orga_client.get(
        reverse(SETTINGS_URL_NAME, kwargs={"event": event.slug}), follow=True
    )
    assert response.status_code == 200


@pytest.mark.django_db
def test_reviewer_cannot_access_settings(review_client, event):
    response = review_client.get(
        reverse(SETTINGS_URL_NAME, kwargs={"event": event.slug})
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_orga_can_save_user_token(orga_client, orga_user, event, user_token):
    url = reverse(SETTINGS_URL_NAME, kwargs={"event": event.slug})
    response = orga_client.post(
        url,
        {
            "form": "user",
            "new_auth_token": user_token,
            "new_auth_token_repeat": user_token,
        },
        follow=True,
    )
    assert response.status_code == 200
    settings = UserSettings.objects.get(event=event, user=orga_user)
    assert settings.rest_auth_token == user_token


@pytest.mark.django_db
def test_user_token_mismatch_is_not_saved(
    orga_client, orga_user, event, user_token, other_token
):
    url = reverse(SETTINGS_URL_NAME, kwargs={"event": event.slug})
    orga_client.post(
        url,
        {
            "form": "user",
            "new_auth_token": user_token,
            "new_auth_token_repeat": other_token,
        },
        follow=True,
    )
    settings = UserSettings.objects.get(event=event, user=orga_user)
    assert settings.rest_auth_token == ""
