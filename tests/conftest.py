import datetime as dt
from unittest import mock

import pytest
from django.core import management
from django_scopes import scopes_disabled

from pretalx.event.domain.event import initialise_event
from pretalx.event.domain.plugins import enable_plugin
from pretalx.event.models import Event, Organiser, Team
from pretalx.mail.enums import QueuedMailStates
from pretalx.mail.models import QueuedMail
from pretalx.person.enums import EmailVerificationState
from pretalx.person.models import SpeakerProfile, User
from pretalx.submission.models import Submission

from pretalx_rt.models import EventSettings, Ticket


@pytest.fixture(scope="session", autouse=True)
def collect_static(request):
    management.call_command("collectstatic", "--noinput", "--clear")


@pytest.fixture
def organiser():
    with scopes_disabled():
        o = Organiser.objects.create(name="Super Organiser", slug="superorganiser")
        Team.objects.create(
            name="Organisers",
            organiser=o,
            can_create_events=True,
            can_change_teams=True,
            can_change_organiser_settings=True,
            can_change_event_settings=True,
            can_change_submissions=True,
        )
        Team.objects.create(name="Reviewers", organiser=o, is_reviewer=True)
    return o


@pytest.fixture
def event(organiser):
    today = dt.date.today()
    with scopes_disabled():
        event = Event.objects.create(
            name="Testevent",
            is_public=True,
            slug="test",
            email="event@example.org",
            date_from=today,
            date_to=today + dt.timedelta(days=3),
            organiser=organiser,
        )
        initialise_event(event)
        enable_plugin(event, "pretalx_rt")
        event.save()
        for team in organiser.teams.all():
            team.limit_events.add(event)
    return event


@pytest.fixture
def orga_user(event):
    with scopes_disabled():
        user = User.objects.create_user(
            password="orgapassw0rd",
            email="orgauser@example.org",
            name="Orga User",
            email_verification_state=EmailVerificationState.VERIFIED,
        )
        team = event.organiser.teams.filter(
            can_change_organiser_settings=True, is_reviewer=False
        ).first()
        team.members.add(user)
        team.save()
    return user


@pytest.fixture
def review_user(event):
    with scopes_disabled():
        user = User.objects.create_user(
            password="reviewpassw0rd",
            email="reviewuser@example.org",
            name="Review User",
            email_verification_state=EmailVerificationState.VERIFIED,
        )
        team = event.organiser.teams.filter(
            can_change_organiser_settings=False, is_reviewer=True
        ).first()
        team.members.add(user)
        team.save()
    return user


@pytest.fixture
def orga_client(orga_user, client):
    client.force_login(orga_user)
    return client


@pytest.fixture
def review_client(review_user, client):
    client.force_login(review_user)
    return client


# Example RT REST2 tokens: <user id>-<n>-<32 hex characters>
@pytest.fixture
def event_token():
    return "1-23-0f1e2d3c4b5a69788796a5b4c3d2e1f0"


@pytest.fixture
def user_token():
    return "4-56-a1b2c3d4e5f60718293a4b5c6d7e8f90"


@pytest.fixture
def other_token():
    return "7-89-9f8e7d6c5b4a39281706f5e4d3c2b1a0"


@pytest.fixture
def event_settings(event, event_token):
    return EventSettings.objects.create(
        event=event,
        base_url="https://rt.example.com/",
        rest_auth_token=event_token,
        queue="General",
    )


@pytest.fixture
def speaker(event):
    with scopes_disabled():
        user = User.objects.create_user(
            password="speakerpassw0rd",
            email="jane@example.org",
            name="Jane",
            email_verification_state=EmailVerificationState.VERIFIED,
        )
        return SpeakerProfile.objects.create(user=user, event=event)


@pytest.fixture
def make_submission(event):
    def make(title="My talk", speakers=()):
        with scopes_disabled():
            submission = Submission.objects.create(
                event=event, title=title, submission_type=event.cfp.default_type
            )
            submission.speakers.add(*speakers)
        return submission

    return make


@pytest.fixture
def submission(make_submission, speaker):
    return make_submission(speakers=[speaker])


@pytest.fixture
def ticket(event, submission):
    return Ticket.objects.create(
        event=event,
        rt_id=5,
        subject="My talk",
        status="new",
        queue="General",
        submission=submission,
    )


@pytest.fixture
def mail(event, speaker):
    with scopes_disabled():
        mail = QueuedMail.objects.create(
            event=event,
            subject="Hello",
            text="Body text",
            text_html="<p>Body text</p>",
            state=QueuedMailStates.DRAFT,
            locale="en",
        )
    recipients = [speaker.user]
    if hasattr(QueuedMail, "to_users"):
        mail.to_users.add(*recipients)
    else:  # newer pretalx versions removed the field
        mail.to_users = mock.Mock(all=lambda: recipients)
    return mail
