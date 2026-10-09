from __future__ import annotations

from sqlalchemy import and_, not_, or_
from sqlalchemy.orm import Session

from app.assistant.email.classification import OPERATIONAL_CATEGORIES
from app.models import EmailActionDraft, EmailSyncState, EmailTaskLink, InboxEmail


def get_message_workbench(db: Session, *, provider: str, mailbox_key: str) -> dict[str, object]:
    state = (
        db.query(EmailSyncState)
        .filter_by(
            provider=provider,
            mailbox_key=mailbox_key,
        )
        .one_or_none()
    )
    base_query = db.query(InboxEmail).filter_by(
        provider=provider,
        mailbox_key=mailbox_key,
    )
    operational_filter = and_(
        InboxEmail.category.in_(OPERATIONAL_CATEGORIES),
        InboxEmail.confidence_band.in_(("medium", "high")),
    )
    informational_filter = InboxEmail.category == "informational"
    review_filter = not_(or_(operational_filter, informational_filter))

    def latest_messages(query):
        return (
            query.order_by(InboxEmail.received_at.desc(), InboxEmail.id.desc())
            .limit(100)
            .all()
        )

    operational_messages = latest_messages(base_query.filter(operational_filter))
    informational_messages = latest_messages(base_query.filter(informational_filter))
    review_messages = latest_messages(base_query.filter(review_filter))
    messages = operational_messages + informational_messages + review_messages
    message_references = list({message.reference for message in messages})
    task_links = (
        db.query(EmailTaskLink)
        .filter(
            EmailTaskLink.provider == provider,
            EmailTaskLink.mailbox_key == mailbox_key,
            EmailTaskLink.reference.in_(message_references),
            EmailTaskLink.task_id.is_not(None),
        )
        .all()
        if message_references else []
    )
    task_ids_by_reference = {link.reference: link.task_id for link in task_links}
    for message in messages:
        message.task_id = task_ids_by_reference.get(message.reference)
    action_drafts = (
        db.query(EmailActionDraft)
        .filter(EmailActionDraft.inbox_email_id.in_([message.id for message in messages]))
        .order_by(EmailActionDraft.id.asc())
        .all()
        if messages
        else []
    )
    action_drafts_by_email = {
        draft.inbox_email_id: draft
        for draft in action_drafts
        if draft.status in {"pending", "confirmed", "cancelled", "linked", "linked_deleted"}
    }
    message_summary = {
        "new": base_query.filter(InboxEmail.seen.is_(False)).count(),
        "priority": base_query.filter(InboxEmail.priority.in_(("high", "critical"))).count(),
        "review": base_query.filter(review_filter).count(),
        "operational": base_query.filter(operational_filter).count(),
        "informational": base_query.filter(informational_filter).count(),
    }
    return {
        "sync_state": state,
        "operational_messages": operational_messages,
        "informational_messages": informational_messages,
        "review_messages": review_messages,
        "message_summary": message_summary,
        "action_drafts_by_email": action_drafts_by_email,
    }

