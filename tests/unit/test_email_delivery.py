"""Unit tests for the email-delivery module.

Covers the provider's address scheme (pure, no network), and the service's
outbound send + inbound matching/classification/persistence paths with the
EngageLab HTTP call mocked out.
"""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session
from src.config.settings import Settings
from src.modules.auth.models import User
from src.modules.auth.repository import UserRepository
from src.modules.email_delivery.enums import ConversationStatus, EmailDirection, ReplyAction
from src.modules.email_delivery.providers.engagelab import EngageLabEmailProvider
from src.modules.email_delivery.repository import EmailDeliveryRepository
from src.modules.email_delivery.service import EmailDeliveryService
from src.modules.email_delivery.webhooks.base import InboundEmail, RawAttachment

_DOMAIN = "mail.example.com"


@pytest.fixture
def email_settings() -> Settings:
    """Settings with EngageLab fully configured for the test."""
    return Settings(
        database_url="sqlite:///:memory:",
        engagelab_api_user="api-user",
        engagelab_api_key="api-key",
        engagelab_outbound_domain=_DOMAIN,
        engagelab_company_name="Acme",
    )


@pytest.fixture
def user(db_session: Session) -> User:
    """A registered user with a permanent sending_email."""
    created = UserRepository(db_session).create(
        email="jane@buyer.com",
        full_name="Jane Doe",
        hashed_password="x",
        sending_email=f"JaneDoe@{_DOMAIN}",
    )
    db_session.flush()
    return created


@pytest.fixture
def service(db_session: Session, email_settings: Settings) -> EmailDeliveryService:
    """A service wired to the in-memory DB and configured settings."""
    return EmailDeliveryService(EmailDeliveryRepository(db_session), email_settings)


def _mock_send() -> MagicMock:
    """Return a MagicMock standing in for a successful ``httpx.post``."""
    response = MagicMock()
    response.status_code = 202
    response.json.return_value = {"email_ids": ["provider-msg-1"]}
    return response


# ── Provider address scheme (pure) ───────────────────────────────────────────


def test_dynamic_address_roundtrip(email_settings: Settings) -> None:
    provider = EngageLabEmailProvider(email_settings)
    conv_id = provider.generate_conversation_id()
    address = provider.build_dynamic_email("James Whitfield", conv_id)
    assert address == f"JamesWhitfield.{conv_id}@{_DOMAIN}"
    assert provider.parse_dynamic_email(address) == {"conv_id": conv_id}


def test_parse_dynamic_email_rejects_foreign_domain(email_settings: Settings) -> None:
    provider = EngageLabEmailProvider(email_settings)
    assert provider.parse_dynamic_email("someone.deadbeef@other.com") is None


def test_parse_conv_id_from_body_footer(email_settings: Settings) -> None:
    provider = EngageLabEmailProvider(email_settings)
    quoted = "On Mon, ... wrote:\nReference: CONV-3FA9C1B2 | USR-42 | THREAD-3FA9C1B2"
    assert provider.parse_conv_id_from_body(quoted) == {"conv_id": "3fa9c1b2"}


# ── Deliverability hardening (the "200 but no email" fix) ─────────────────────


def test_send_email_sanitizes_subject_and_adds_text_and_to_name(
    email_settings: Settings,
) -> None:
    """A newline in the subject is collapsed, a text part is added, and the
    recipient name is used in the ``to`` header — the fixes for a draft that
    returns 200 yet never arrives."""
    provider = EngageLabEmailProvider(email_settings)
    with patch("httpx.post", return_value=_mock_send()) as mock_post:
        provider.send_email(
            from_email=f"JaneDoe@{_DOMAIN}",
            from_name="Jane Doe",
            to_email="supplier@acme.com",
            to_name="Acme Buyer",
            subject="Quote please\nInjected: header",
            html_body="<div><p>Hello there</p></div>",
            reply_to=f"JaneDoe.deadbeef@{_DOMAIN}",
            text_body="Hello there",
        )
    payload = mock_post.call_args.kwargs["json"]
    assert "\n" not in payload["body"]["subject"]
    assert payload["body"]["subject"] == "Quote please Injected: header"
    assert payload["body"]["content"]["text"] == "Hello there"
    assert payload["to"] == ["Acme Buyer <supplier@acme.com>"]


def test_send_email_derives_text_from_html_when_absent(email_settings: Settings) -> None:
    provider = EngageLabEmailProvider(email_settings)
    with patch("httpx.post", return_value=_mock_send()) as mock_post:
        provider.send_email(
            from_email=f"JaneDoe@{_DOMAIN}",
            from_name="Jane Doe",
            to_email="supplier@acme.com",
            to_name="",
            subject="Hi",
            html_body="<p>Line one</p><p>Line two</p>",
            reply_to=f"JaneDoe.deadbeef@{_DOMAIN}",
        )
    payload = mock_post.call_args.kwargs["json"]
    assert "Line one" in payload["body"]["content"]["text"]
    assert "Line two" in payload["body"]["content"]["text"]
    assert "<p>" not in payload["body"]["content"]["text"]
    assert payload["to"] == ["supplier@acme.com"]  # no display name → bare address


def test_extract_recipient_name_from_greeting() -> None:
    from src.modules.email_delivery.router import extract_recipient_name

    assert extract_recipient_name("Dear Jane Smith,\n\nPlease quote.") == "Jane Smith"
    assert extract_recipient_name("Hi John,\nThanks") == "John"
    assert extract_recipient_name("Dear [recipient name],\nHi") == ""  # placeholder skipped
    assert extract_recipient_name("No greeting here.") == ""


# ── Outbound ──────────────────────────────────────────────────────────────────


def test_send_draft_records_sent_email(
    service: EmailDeliveryService, user: User, db_session: Session
) -> None:
    with patch("httpx.post", return_value=_mock_send()) as mock_post:
        conversation = service.send_draft(
            user_id=user.id,
            user_name=user.full_name,
            sender_email=user.sending_email,
            recipient="supplier@acme.com",
            recipient_name="Acme",
            subject="Quote please",
            body_text="Hello,\nplease quote 500 units.",
        )
    mock_post.assert_called_once()
    assert conversation.reply_to_address == f"JaneDoe.{conversation.token}@{_DOMAIN}"
    detail = service.get_conversation_detail(user_id=user.id, conversation_id=conversation.id)
    assert detail is not None
    assert [e.direction for e in detail.emails] == [EmailDirection.SENT.value]
    assert detail.emails[0].status_code == 202


def test_send_rfq_uses_template_subject(
    service: EmailDeliveryService, user: User
) -> None:
    with patch("httpx.post", return_value=_mock_send()):
        conversation = service.send_rfq(
            user_id=user.id,
            user_name=user.full_name,
            sender_email=user.sending_email,
            supplier_email="supplier@acme.com",
            supplier_name="Acme",
            product_name="Speaker X200",
            quantity=500,
            target_price="$12.00",
        )
    tag = conversation.token[:4].upper()
    assert conversation.subject == f"[RFQ-{tag}] Request for Quotation — Speaker X200"


# ── Inbound ─────────────────────────────────────────────────────────────────


def _open_conversation(service: EmailDeliveryService, user: User):
    with patch("httpx.post", return_value=_mock_send()):
        return service.send_draft(
            user_id=user.id,
            user_name=user.full_name,
            sender_email=user.sending_email,
            recipient="supplier@acme.com",
            recipient_name="Acme",
            subject="Quote please",
            body_text="Please quote.",
        )


def test_inbound_reply_matches_and_persists_against_user(
    service: EmailDeliveryService, user: User
) -> None:
    conversation = _open_conversation(service, user)
    inbound = InboundEmail(
        from_email="supplier@acme.com",
        to_email=conversation.reply_to_address,
        subject="Re: Quote please",
        body_text="Our price is $11.50 per unit.",
        provider="engagelab",
    )
    result = service._record_inbound(inbound, service._webhook_parser())
    assert result["status"] == "matched"
    assert result["action"] is ReplyAction.QUOTE_RECEIVED

    detail = service.get_conversation_detail(user_id=user.id, conversation_id=conversation.id)
    assert detail is not None
    directions = [e.direction for e in detail.emails]
    assert EmailDirection.RECEIVED.value in directions
    assert detail.status == ConversationStatus.REPLIED.value
    assert detail.reply_count == 1


def test_inbound_decline_sets_conversation_declined(
    service: EmailDeliveryService, user: User
) -> None:
    conversation = _open_conversation(service, user)
    inbound = InboundEmail(
        from_email="supplier@acme.com",
        to_email=conversation.reply_to_address,
        subject="Re: Quote please",
        body_text="Sorry, we cannot supply this item.",
        provider="engagelab",
    )
    result = service._record_inbound(inbound, service._webhook_parser())
    assert result["action"] is ReplyAction.DECLINED
    detail = service.get_conversation_detail(user_id=user.id, conversation_id=conversation.id)
    assert detail is not None
    assert detail.status == ConversationStatus.DECLINED.value


def test_inbound_attachment_is_persisted(
    service: EmailDeliveryService, user: User
) -> None:
    conversation = _open_conversation(service, user)
    inbound = InboundEmail(
        from_email="supplier@acme.com",
        to_email=conversation.reply_to_address,
        subject="Re: Quote please",
        body_text="See attached quote.",
        attachments=[RawAttachment("quote.pdf", "application/pdf", b"%PDF-1.4 data")],
        provider="engagelab",
    )
    service._record_inbound(inbound, service._webhook_parser())
    detail = service.get_conversation_detail(user_id=user.id, conversation_id=conversation.id)
    assert detail is not None
    received = [e for e in detail.emails if e.direction == EmailDirection.RECEIVED.value][0]
    assert len(received.attachments) == 1
    assert received.attachments[0].filename == "quote.pdf"
    assert received.attachments[0].url.startswith("/attachments/")


def test_inbound_new_thread_matched_via_sending_email(
    service: EmailDeliveryService, user: User
) -> None:
    inbound = InboundEmail(
        from_email="New Supplier <newsup@x.com>",
        to_email=user.sending_email or "",
        subject="Introducing our catalog",
        body_text="Hello, we make widgets.",
        provider="engagelab",
    )
    result = service._record_inbound(inbound, service._webhook_parser())
    assert result["status"] == "matched"
    conversations = service.list_conversations(user_id=user.id)
    assert any(c.supplier_email == "newsup@x.com" for c in conversations)


def test_inbound_unknown_address_is_unmatched(
    service: EmailDeliveryService, user: User
) -> None:
    inbound = InboundEmail(
        from_email="stranger@nowhere.com",
        to_email="nobody.deadbeef@mail.example.com",
        subject="Hello",
        body_text="Random message.",
        provider="engagelab",
    )
    result = service._record_inbound(inbound, service._webhook_parser())
    assert result["status"] == "unmatched"
    assert service.list_conversations(user_id=user.id) == []
