import logging
from types import SimpleNamespace
from unittest import mock

import pytest
from django_scopes import scope, scopes_disabled

from pretalx.common.templatetags.rich_text import rich_text
from pretalx.event.models import Event
from pretalx.mail.enums import QueuedMailStates
from pretalx.mail.models import QueuedMail

from pretalx_rt.models import EventSettings, Ticket, UserSettings
from pretalx_rt.rt_sync import RTSync

LOGGER = "pretalx_rt.rt_sync"


@pytest.fixture(autouse=True)
def event_scope(event):
    with scope(event=event):
        yield


@pytest.fixture(autouse=True)
def no_signal_handlers():
    """Creating objects must not trigger the plugin's own sync handlers."""
    with mock.patch("pretalx_rt.signals.is_enabled", return_value=False):
        yield


@pytest.fixture
def rt():
    with mock.patch("pretalx_rt.rt_sync.Rt") as rt_mock:
        yield rt_mock.return_value


@pytest.fixture
def sync(event, event_settings, rt):
    return RTSync(event)


@pytest.fixture
def rt_ticket():
    return {
        "Subject": "Remote subject",
        "Status": "open",
        "Queue": {"Name": "Remote queue"},
        "Requestor": ["old requestor"],
    }


def log_lines(caplog):
    """(level, formatted message) for all records of the sync module.

    Formatting happens here, so a mismatch between a message and its arguments
    fails the test instead of being swallowed by the logging machinery.
    """
    return [
        (record.levelname, record.getMessage())
        for record in caplog.records
        if record.name == LOGGER
    ]


@pytest.fixture
def log(caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    return caplog


# Token selection


@pytest.mark.django_db
def test_rtsync_uses_event_token_without_user(event, event_settings, event_token):
    with mock.patch("pretalx_rt.rt_sync.Rt") as rt_mock:
        RTSync(event)
    rt_mock.assert_called_once_with(
        url="https://rt.example.com/REST/2.0/", token=event_token
    )


@pytest.mark.django_db
def test_rtsync_uses_event_token_if_user_has_none(
    event, event_settings, event_token, orga_user
):
    with mock.patch("pretalx_rt.rt_sync.Rt") as rt_mock:
        RTSync(event, orga_user)
    assert rt_mock.call_args.kwargs["token"] == event_token


@pytest.mark.django_db
def test_rtsync_prefers_user_token(event, event_settings, orga_user, user_token):
    UserSettings.objects.create(event=event, user=orga_user, rest_auth_token=user_token)
    with mock.patch("pretalx_rt.rt_sync.Rt") as rt_mock:
        RTSync(event, orga_user)
    assert rt_mock.call_args.kwargs["token"] == user_token


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
    with mock.patch("pretalx_rt.rt_sync.Rt") as rt_mock:
        RTSync(event, orga_user)
    assert rt_mock.call_args.kwargs["token"] == event_token


# Queues and custom fields


@pytest.mark.django_db
def test_get_queues(sync, rt):
    rt.get_all_queues.return_value = [{"Name": "General"}, {"id": "3"}, {"Name": "B"}]
    assert sync.get_queues() == ["General", "B"]


@pytest.mark.django_db
def test_get_queues_failure_returns_empty_list_and_logs(sync, rt, log):
    rt.get_all_queues.side_effect = RuntimeError("boom")
    assert sync.get_queues() == []
    (level, message), *rest = log_lines(log)
    assert (level, rest) == ("ERROR", [])
    assert message.startswith("Failed to fetch RT queues")


@pytest.mark.django_db
def test_get_custom_fields(sync, rt):
    rt.get_queue.return_value = {"TicketCustomFields": [{"name": "A"}, {"id": 2}]}
    assert sync.get_custom_fields() == ["A"]
    rt.get_queue.assert_called_once_with("General")


@pytest.mark.django_db
def test_get_custom_fields_failure_returns_empty_list_and_logs(sync, rt, log):
    rt.get_queue.side_effect = RuntimeError("boom")
    assert sync.get_custom_fields() == []
    (level, message), *rest = log_lines(log)
    assert (level, rest) == ("ERROR", [])
    assert message.startswith("Failed to fetch custom fields")


# Pull


@pytest.mark.django_db
def test_pull_updates_ticket(sync, rt, rt_ticket, ticket, log):
    rt.get_ticket.return_value = rt_ticket
    sync.pull(ticket)
    ticket.refresh_from_db()
    assert (ticket.subject, ticket.status, ticket.queue) == (
        "Remote subject",
        "open",
        "Remote queue",
    )
    rt.get_ticket.assert_called_once_with(5)
    assert log_lines(log) == [("INFO", "Pulling updates from RT #5")]


@pytest.mark.django_db
def test_pull_failure_keeps_ticket_and_logs(sync, rt, ticket, log):
    rt.get_ticket.side_effect = RuntimeError("boom")
    sync.pull(ticket)
    ticket.refresh_from_db()
    assert ticket.subject == "My talk"
    levels = [level for level, _ in log_lines(log)]
    assert levels == ["INFO", "ERROR"]
    assert log_lines(log)[1][1].startswith("Failed to pull RT ticket #5")


@pytest.mark.django_db
def test_failures_are_logged_with_traceback(sync, rt, ticket, log):
    rt.get_ticket.side_effect = RuntimeError("boom")
    sync.pull(ticket)
    error = next(r for r in log.records if r.levelname == "ERROR")
    assert error.exc_info is not None
    assert error.exc_info[0] is RuntimeError


# Ticket creation


@pytest.mark.django_db
def test_requestors(sync, speaker):
    assert sync.requestors([speaker.user]) == ["Jane <jane@example.org>"]


@pytest.mark.django_db
def test_requestors_replace_at_sign_in_names(sync):
    user = SimpleNamespace(name="Jane@Home", email="jane@example.org")
    assert sync.requestors([user]) == ["Jane(at)Home <jane@example.org>"]


@pytest.mark.django_db
def test_create_submission_ticket(sync, rt, rt_ticket, submission, log):
    rt.create_ticket.return_value = 42
    rt.get_ticket.return_value = rt_ticket

    ticket = sync.create_submission_ticket(submission)

    rt.create_ticket.assert_called_once_with(
        queue="General",
        subject="My talk",
        Requestor=["Jane <jane@example.org>"],
        Status="resolved",
        Owner="Nobody",
        CustomFields={"Pretalx ID": submission.code, "Pretalx State": submission.state},
    )
    saved = Ticket.objects.get(rt_id=42)
    assert ticket == saved
    assert saved.submission == submission
    assert (saved.subject, saved.status, saved.queue) == (
        "Remote subject",
        "open",
        "Remote queue",
    )
    assert log_lines(log) == [
        ("INFO", f"Creating RT ticket for submission {submission.code}"),
        ("INFO", "Pulling updates from RT #42"),
    ]


@pytest.mark.django_db
def test_create_submission_ticket_failure(sync, rt, submission, log):
    rt.create_ticket.side_effect = RuntimeError("boom")
    assert sync.create_submission_ticket(submission) is None
    assert not Ticket.objects.exists()
    level, message = log_lines(log)[-1]
    assert level == "ERROR"
    assert message.startswith("Failed to create RT ticket")


@pytest.mark.django_db
def test_create_mail_ticket(sync, rt, rt_ticket, mail, log):
    rt.create_ticket.return_value = 43
    rt.get_ticket.return_value = rt_ticket

    ticket = sync.create_mail_ticket(mail)

    rt.create_ticket.assert_called_once_with(
        queue="General",
        subject="Hello",
        Requestor=["Jane <jane@example.org>"],
        Status="resolved",
        Owner="Nobody",
    )
    assert ticket == Ticket.objects.get(rt_id=43)
    assert ticket.submission is None
    assert log_lines(log)[0] == ("INFO", "Creating RT ticket for standalone mail")


@pytest.mark.django_db
def test_create_mail_ticket_failure(sync, rt, mail, log):
    rt.create_ticket.side_effect = RuntimeError("boom")
    assert sync.create_mail_ticket(mail) is None
    assert not Ticket.objects.exists()
    level, message = log_lines(log)[-1]
    assert level == "ERROR"
    assert message.startswith("Failed to create RT ticket")


# Mails and comments


def reload(mail):
    with scopes_disabled():
        return QueuedMail.objects.get(pk=mail.pk)


@pytest.fixture
def push():
    with mock.patch.object(RTSync, "push") as push_mock:
        yield push_mock


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("html", "content", "content_type"),
    ((True, "<p>Body text</p>", "text/html"), (False, "Body text", "text/plain")),
)
def test_add_mail_to_ticket(
    sync, rt, ticket, mail, push, event_settings, log, html, content, content_type
):
    event_settings.is_mail_html = html
    event_settings.save()
    sync.settings = event_settings

    sync.add_mail_to_ticket(ticket, mail)

    rt.reply.assert_called_once_with(
        5, content=content, content_type=content_type, attachments=[]
    )
    rt.edit_ticket.assert_called_once_with(
        5, Requestor=["Jane <jane@example.org>"], Subject="Hello"
    )
    assert reload(mail).state == QueuedMailStates.SENT
    assert list(ticket.mails.values_list("pk", flat=True)) == [mail.pk]
    assert log_lines(log) == [("INFO", "Adding mail to RT #5")]


@pytest.mark.django_db
def test_add_mail_to_ticket_syncs_the_ticket_after_sending(
    sync, rt, ticket, mail, push
):
    calls = mock.Mock()
    calls.attach_mock(rt.reply, "reply")
    calls.attach_mock(push, "push")

    sync.add_mail_to_ticket(ticket, mail)

    assert [name for name, _, _ in calls.mock_calls] == ["reply", "push"]
    push.assert_called_once_with(ticket)


@pytest.mark.django_db
def test_add_mail_to_ticket_ends_with_the_pretalx_data_in_rt(
    sync, rt, ticket, mail, submission
):
    with mock.patch("pretalx_rt.rt_sync.ticket_pull_task") as pull_task:
        sync.add_mail_to_ticket(ticket, mail)

    assert rt.edit_ticket.call_args_list == [
        mock.call(5, Requestor=["Jane <jane@example.org>"], Subject="Hello"),
        mock.call(
            5,
            Subject="My talk",
            Requestor=["Jane <jane@example.org>"],
            CustomFields={
                "Pretalx ID": submission.code,
                "Pretalx State": submission.state,
            },
        ),
    ]
    pull_task.apply_async.assert_called_once()


@pytest.mark.django_db
def test_add_mail_to_ticket_sends_attachments(sync, rt, ticket, mail, push):
    mail.attachments = [
        {"name": "a.txt", "content": "YQ==", "content_type": "text/plain"}
    ]
    mail.save()
    with mock.patch("pretalx_rt.rt_sync.Attachment") as attachment:
        sync.add_mail_to_ticket(ticket, mail)
    attachment.assert_called_once_with(
        file_name="a.txt", file_content="YQ==", file_type="text/plain"
    )
    assert rt.reply.call_args.kwargs["attachments"] == [attachment.return_value]


@pytest.mark.django_db
def test_add_mail_to_ticket_failure_records_error(sync, rt, ticket, mail, push, log):
    rt.reply.side_effect = RuntimeError("boom")

    sync.add_mail_to_ticket(ticket, mail)

    mail = reload(mail)
    assert mail.state == QueuedMailStates.SENDING
    assert mail.error_data == {"error": "boom", "type": "RuntimeError"}
    assert mail.error_timestamp is not None
    assert not ticket.mails.exists()
    push.assert_called_once_with(ticket)
    level, message = log_lines(log)[-1]
    assert level == "ERROR"
    assert message.startswith("Failed to add mail to RT ticket #5")


@pytest.mark.django_db
def test_add_comment_to_ticket(sync, rt, ticket, push, log):
    comment = SimpleNamespace(text="Some *comment*")

    sync.add_comment_to_ticket(ticket, comment)

    rt.comment.assert_called_once_with(
        5, content=rich_text("Some *comment*"), content_type="text/html"
    )
    assert log_lines(log) == [("INFO", "Adding comment to RT #5")]


@pytest.mark.django_db
def test_add_comment_to_ticket_syncs_the_ticket_after_commenting(
    sync, rt, ticket, push
):
    calls = mock.Mock()
    calls.attach_mock(rt.comment, "comment")
    calls.attach_mock(push, "push")

    sync.add_comment_to_ticket(ticket, SimpleNamespace(text="x"))

    assert [name for name, _, _ in calls.mock_calls] == ["comment", "push"]
    push.assert_called_once_with(ticket)


@pytest.mark.django_db
def test_add_comment_to_ticket_syncs_the_ticket_on_failure(sync, rt, ticket, push):
    rt.comment.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError):
        sync.add_comment_to_ticket(ticket, SimpleNamespace(text="x"))

    push.assert_called_once_with(ticket)


@pytest.mark.django_db
def test_add_comment_to_ticket_ends_with_the_pretalx_data_in_rt(
    sync, rt, ticket, submission
):
    with mock.patch("pretalx_rt.rt_sync.ticket_pull_task") as pull_task:
        sync.add_comment_to_ticket(ticket, SimpleNamespace(text="x"))

    rt.edit_ticket.assert_called_once_with(
        5,
        Subject="My talk",
        Requestor=["Jane <jane@example.org>"],
        CustomFields={"Pretalx ID": submission.code, "Pretalx State": submission.state},
    )
    pull_task.apply_async.assert_called_once()


# Push


@pytest.mark.django_db
def test_push(sync, rt, ticket, submission, event, log):
    with mock.patch("pretalx_rt.rt_sync.ticket_pull_task") as pull_task:
        sync.push(ticket)

    rt.edit_ticket.assert_called_once_with(
        5,
        Subject="My talk",
        Requestor=["Jane <jane@example.org>"],
        CustomFields={"Pretalx ID": submission.code, "Pretalx State": submission.state},
    )
    pull_task.apply_async.assert_called_once_with(
        kwargs={"event_id": event.pk, "ticket_id": ticket.pk}
    )
    assert log_lines(log) == [("INFO", "Pushing updates to RT #5")]


@pytest.mark.django_db
def test_push_without_submission_does_nothing(sync, rt, event):
    ticket = Ticket.objects.create(event=event, rt_id=6)
    with mock.patch("pretalx_rt.rt_sync.ticket_pull_task") as pull_task:
        sync.push(ticket)
    rt.edit_ticket.assert_not_called()
    pull_task.apply_async.assert_not_called()


@pytest.mark.django_db
def test_push_failure_logs_and_skips_pull(sync, rt, ticket, log):
    rt.edit_ticket.side_effect = RuntimeError("boom")
    with mock.patch("pretalx_rt.rt_sync.ticket_pull_task") as pull_task:
        sync.push(ticket)
    pull_task.apply_async.assert_not_called()
    level, message = log_lines(log)[-1]
    assert level == "ERROR"
    assert message.startswith("Failed to push RT ticket #5")


# Queue sync


def rt_search_result(rt_id, pretalx_id=None):
    fields = [{"name": "Pretalx ID", "values": [pretalx_id]}] if pretalx_id else []
    return {"id": str(rt_id), "CustomFields": fields}


@pytest.mark.django_db
def test_get_custom_field():
    ticket = rt_search_result(1, "ABC")
    assert RTSync.get_custom_field(ticket, "Pretalx ID") == "ABC"
    assert RTSync.get_custom_field(ticket, "Other") is None
    assert RTSync.get_custom_field(rt_search_result(1), "Pretalx ID") is None


@pytest.mark.django_db
def test_sync_queue(sync, rt, make_submission, event, log):
    new = make_submission("New")
    linked = make_submission("Linked")
    Ticket.objects.create(event=event, rt_id=99, submission=linked)
    rt.search.return_value = [
        rt_search_result(10, new.code),
        rt_search_result(11, "NOPE"),
        rt_search_result(12),
        rt_search_result(13, linked.code),
        rt_search_result(99, linked.code),
    ]

    with mock.patch.object(RTSync, "push") as push:
        sync.sync_queue()

    rt.search.assert_called_once_with("General")
    created = Ticket.objects.get(rt_id=10)
    assert created.submission == new
    assert created.event == event
    assert set(Ticket.objects.values_list("rt_id", flat=True)) == {10, 99}
    push.assert_called_once_with(created)
    assert log_lines(log) == [
        ("INFO", "Starting sync of RT queue 'General'"),
        ("INFO", f"Created RT #10 for Submission '{new.code}'"),
        ("WARNING", "Skipping RT #11: Submission 'NOPE' not found"),
        ("DEBUG", "Skipping RT #12 (no Submission)"),
        (
            "WARNING",
            f"Skipping RT #13: Submission '{linked.code}' already linked to RT #99.",
        ),
        ("DEBUG", f"Skipping RT #99: Submission '{linked.code}' already linked."),
        ("INFO", "Synced 5 tickets of queue 'General': 0 updated, 1 new."),
    ]


@pytest.mark.django_db
def test_sync_queue_reports_updated_ticket(sync, rt, make_submission, event, log):
    submission = make_submission("Existing")
    Ticket.objects.create(event=event, rt_id=10)
    rt.search.return_value = [rt_search_result(10, submission.code)]

    with mock.patch.object(RTSync, "push"):
        sync.sync_queue()

    assert Ticket.objects.get(rt_id=10).submission == submission
    assert log_lines(log)[1:] == [
        ("INFO", f"Updated RT #10 with Submission '{submission.code}'"),
        ("INFO", "Synced 1 tickets of queue 'General': 1 updated, 0 new."),
    ]


@pytest.mark.django_db
def test_event_settings_row_is_required(event, rt):
    assert not EventSettings.objects.filter(event=event).exists()
    with pytest.raises(EventSettings.DoesNotExist):
        RTSync(event)
