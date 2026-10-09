from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from app.models import EmailActionDraft, EmailSyncState, EmailTaskLink, InboxEmail, Task
from app.routers import pages


def _message(reference, category="other_review", confidence="low", **kwargs):
    return InboxEmail(
        provider="synthetic", mailbox_key="workbench", reference=reference,
        category=category, confidence_band=confidence, seen=False,
        received_at=datetime(2026, 10, 8, tzinfo=UTC),
        last_seen_at=datetime(2026, 10, 8, tzinfo=UTC),
        **kwargs,
    )


def _context(db, monkeypatch):
    monkeypatch.setattr(pages, "settings", SimpleNamespace(
        email_provider="synthetic", email_sync_mailbox_key="workbench",
        email_sync_enabled=False, email_sync_interval_seconds=60,
    ))
    monkeypatch.setattr(pages, "render_template", lambda request, name, context: context)
    statements = []

    def record(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.lstrip().split()[0].upper())

    event.listen(db.get_bind(), "before_cursor_execute", record)
    try:
        context = pages.messages_page(None, db)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", record)
    assert set(statements) == {"SELECT"}
    assert not db.new and not db.dirty and not db.deleted
    return context


def test_groups_limits_full_counts_order_and_origin_isolation(db, monkeypatch):
    expected = {}
    for group, category, confidence in (
        ("operational", "customer_quote_request", "high"),
        ("informational", "informational", "low"),
        ("review", "customer_quote_request", "low"),
    ):
        rows = [_message(f"{group}-{i}", category, confidence, priority="high") for i in range(101)]
        db.add_all(rows)
        db.flush()
        expected[group] = [row.id for row in reversed(rows)][0:100]
    other_provider = _message("foreign-provider")
    other_provider.provider = "disabled"
    other_mailbox = _message("foreign-mailbox")
    other_mailbox.mailbox_key = "elsewhere"
    db.add_all([other_provider, other_mailbox])
    state = EmailSyncState(provider="synthetic", mailbox_key="workbench", paused=True)
    db.add_all([
        state,
        EmailSyncState(provider="synthetic", mailbox_key="elsewhere"),
        EmailSyncState(provider="disabled", mailbox_key="workbench", paused=False),
    ])
    db.commit()
    context = _context(db, monkeypatch)
    assert context["sync_state"].id == state.id
    assert context["message_summary"] == {
        "new": 303, "priority": 303, "operational": 101, "informational": 101, "review": 101,
    }
    assert context["message_count_total"] == 303
    for group in context["message_groups"]:
        assert [row.id for row in group["messages"]] == expected[group["key"]]
        assert group["count"] == 101


def test_category_confidence_and_presentation_links(db, monkeypatch):
    rows = [
        _message("vendor", "vendor_quotation", "high"),
        _message("medium", "service_request", "medium"),
        _message("low", "service_request", "low"),
        _message("unknown", "other_review", "high"),
        _message("info", "informational", "high"),
    ]
    task = Task(titulo="Synthetic task")
    db.add_all([*rows, task])
    db.flush()
    for provider, mailbox, reference, action, task_id in (
        ("synthetic", "workbench", "medium", "task_service_request", task.id),
        ("synthetic", "workbench", "medium", "task_pending_reply", None),
        ("disabled", "workbench", "low", "task_service_request", task.id),
        ("synthetic", "elsewhere", "unknown", "task_service_request", task.id),
    ):
        db.add(EmailTaskLink(provider=provider, mailbox_key=mailbox, reference=reference,
                             action_type=action, task_id=task_id, task_title_snapshot="Synthetic"))
    db.commit()
    context = _context(db, monkeypatch)
    groups = {group["key"]: {row.reference: row for row in group["messages"]}
              for group in context["message_groups"]}
    assert set(groups["operational"]) == {"medium", "vendor"}
    assert set(groups["review"]) == {"low", "unknown"}
    assert set(groups["informational"]) == {"info"}
    assert groups["operational"]["medium"].task_id == task.id
    assert all(row.task_id is None for row in groups["review"].values())
    assert "task_id" not in InboxEmail.__table__.columns


@pytest.mark.parametrize("latest_status", ["pending", "confirmed", "cancelled", "linked", "linked_deleted"])
def test_latest_draft_all_legal_statuses_and_empty_queue(db, monkeypatch, latest_status):
    assert _context(db, monkeypatch)["action_drafts_by_email"] == {}
    email = _message("draft")
    foreign = _message("foreign")
    foreign.mailbox_key = "elsewhere"
    db.add_all([email, foreign])
    db.flush()
    first = EmailActionDraft(inbox_email_id=email.id, action_type="task_customer_quote", status="pending")
    latest = EmailActionDraft(inbox_email_id=email.id, action_type="task_service_request", status=latest_status)
    db.add(first)
    db.flush()
    db.add(latest)
    db.add(EmailActionDraft(inbox_email_id=foreign.id, action_type="task_customer_quote"))
    db.commit()
    context = _context(db, monkeypatch)
    assert set(context["action_drafts_by_email"]) == {email.id}
    assert context["action_drafts_by_email"][email.id].id == latest.id
