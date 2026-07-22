"""Unit tests for SendGrid provider selection, outbound send and inbound parse.

These verify the ``.env``-driven provider switch actually works: setting
``EMAIL_PROVIDER=sendgrid`` (or the legacy ``INBOUND_EMAIL_PROVIDER`` alias)
routes both outbound sends and inbound webhook parsing through SendGrid, with
the network call mocked out.
"""

import asyncio
import io
from unittest.mock import MagicMock, patch

import pytest
from src.config.settings import Settings
from src.modules.email_delivery.providers import EmailProviderFactory
from src.modules.email_delivery.providers.sendgrid import SendGridEmailProvider
from src.modules.email_delivery.repository import EmailDeliveryRepository
from src.modules.email_delivery.service import EmailDeliveryService
from src.modules.email_delivery.webhooks import WebhookParserFactory
from src.modules.email_delivery.webhooks.sendgrid import SendGridWebhookParser
from starlette.datastructures import FormData, Headers, UploadFile

_DOMAIN = "mail.example.com"


@pytest.fixture
def sendgrid_settings() -> Settings:
    """Settings with SendGrid selected and fully configured."""
    return Settings(
        database_url="sqlite:///:memory:",
        email_provider="sendgrid",
        sendgrid_api_key="SG.test-key",
        sendgrid_outbound_domain=_DOMAIN,
        sendgrid_company_name="Acme",
    )


def _mock_send() -> MagicMock:
    """Return a MagicMock standing in for a successful SendGrid ``httpx.post``."""
    response = MagicMock()
    response.status_code = 202
    response.headers = {"X-Message-Id": "sg-msg-1"}
    return response


# ── Provider selection is driven by EMAIL_PROVIDER ───────────────────────────


def test_factory_registers_sendgrid() -> None:
    assert "sendgrid" in EmailProviderFactory.supported()
    assert "sendgrid" in WebhookParserFactory.supported()


def test_service_selects_sendgrid_from_settings(sendgrid_settings: Settings) -> None:
    """With EMAIL_PROVIDER=sendgrid the service resolves the SendGrid provider."""
    service = EmailDeliveryService(MagicMock(spec=EmailDeliveryRepository), sendgrid_settings)
    provider = service.get_provider()
    assert isinstance(provider, SendGridEmailProvider)
    assert provider.provider_name == "sendgrid"
    assert isinstance(service._webhook_parser(), SendGridWebhookParser)


def test_inbound_email_provider_alias_still_works() -> None:
    """The legacy INBOUND_EMAIL_PROVIDER env name maps to email_provider."""
    settings = Settings(
        database_url="sqlite:///:memory:",
        inbound_email_provider="sendgrid",
        sendgrid_api_key="SG.test-key",
        sendgrid_outbound_domain=_DOMAIN,
    )
    assert settings.email_provider == "sendgrid"
    assert settings.default_outbound_domain == _DOMAIN


# ── Outbound send builds the v3 Mail Send payload ────────────────────────────


def test_sendgrid_send_builds_v3_payload(sendgrid_settings: Settings) -> None:
    provider = SendGridEmailProvider(sendgrid_settings)
    with patch("httpx.post", return_value=_mock_send()) as mock_post:
        result = provider.send_email(
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
    headers = mock_post.call_args.kwargs["headers"]
    # Bearer auth, not basic.
    assert headers["Authorization"] == "Bearer SG.test-key"
    # Subject sanitised (newline collapsed).
    assert "\n" not in payload["subject"]
    assert payload["subject"] == "Quote please Injected: header"
    # v3 shape.
    assert payload["personalizations"][0]["to"] == [
        {"email": "supplier@acme.com", "name": "Acme Buyer"}
    ]
    assert payload["from"] == {"email": f"JaneDoe@{_DOMAIN}", "name": "Jane Doe"}
    assert payload["reply_to"] == {"email": f"JaneDoe.deadbeef@{_DOMAIN}"}
    # text/plain must precede text/html.
    assert [c["type"] for c in payload["content"]] == ["text/plain", "text/html"]
    assert payload["content"][0]["value"] == "Hello there"
    # Normalised return.
    assert result == {
        "status_code": 202,
        "provider": "sendgrid",
        "provider_message_id": "sg-msg-1",
    }


def test_sendgrid_derives_text_and_omits_empty_to_name(sendgrid_settings: Settings) -> None:
    provider = SendGridEmailProvider(sendgrid_settings)
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
    text_part = payload["content"][0]["value"]
    assert "Line one" in text_part and "Line two" in text_part
    assert "<p>" not in text_part
    # No display name → bare recipient object.
    assert payload["personalizations"][0]["to"] == [{"email": "supplier@acme.com"}]


def test_sendgrid_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.modules.email_delivery.exceptions import ProviderConfigError

    settings = Settings(
        database_url="sqlite:///:memory:",
        email_provider="sendgrid",
        sendgrid_outbound_domain=_DOMAIN,
        sendgrid_api_key="",
    )
    with pytest.raises(ProviderConfigError, match="SENDGRID_API_KEY"):
        SendGridEmailProvider(settings)


# ── Inbound Parse (multipart form) ───────────────────────────────────────────


class _FakeRequest:
    """Minimal stand-in exposing the two attributes the parser touches."""

    def __init__(self, form: FormData) -> None:
        self.headers = {"content-type": "multipart/form-data; boundary=x"}
        self._form = form

    async def form(self) -> FormData:
        return self._form


def test_sendgrid_inbound_parse_extracts_fields_and_attachment(
    sendgrid_settings: Settings,
) -> None:
    upload = UploadFile(
        file=io.BytesIO(b"%PDF-1.4 data"),
        filename="quote.pdf",
        headers=Headers({"content-type": "application/pdf"}),
    )
    form = FormData(
        [
            ("from", "Supplier <supplier@acme.com>"),
            ("to", f"JaneDoe.deadbeef <JaneDoe.deadbeef@{_DOMAIN}>"),
            ("subject", "Re: Quote please"),
            ("text", "Our price is $11.50 per unit."),
            ("html", "<p>Our price is $11.50 per unit.</p>"),
            ("SPF", "pass"),
            ("dkim", "{@acme.com : pass}"),
            ("spam_score", "0.1"),
            ("attachments", "1"),
            (
                "attachment-info",
                '{"attachment1": {"filename": "quote.pdf", "type": "application/pdf"}}',
            ),
            ("attachment1", upload),
        ]
    )
    parser = SendGridWebhookParser(sendgrid_settings)
    inbound = asyncio.run(parser.parse(_FakeRequest(form)))

    assert inbound.provider == "sendgrid"
    assert inbound.from_email == "supplier@acme.com"
    assert inbound.to_email == f"JaneDoe.deadbeef@{_DOMAIN}"
    assert inbound.spf == "pass"
    assert inbound.spam_score == pytest.approx(0.1)
    assert len(inbound.attachments) == 1
    assert inbound.attachments[0].filename == "quote.pdf"
    assert inbound.attachments[0].content_type == "application/pdf"
    assert inbound.attachments[0].content == b"%PDF-1.4 data"


def test_sendgrid_inbound_falls_back_to_envelope_recipient(
    sendgrid_settings: Settings,
) -> None:
    """When the display ``to`` is blank, the envelope's first recipient is used."""
    form = FormData(
        [
            ("from", "supplier@acme.com"),
            ("to", ""),
            ("subject", "Re: Quote"),
            ("text", "Hello"),
            ("envelope", f'{{"to":["JaneDoe.deadbeef@{_DOMAIN}"],"from":"supplier@acme.com"}}'),
        ]
    )
    parser = SendGridWebhookParser(sendgrid_settings)
    inbound = asyncio.run(parser.parse(_FakeRequest(form)))
    assert inbound.to_email == f"JaneDoe.deadbeef@{_DOMAIN}"
