"""Domain-specific exceptions for the email-delivery module.

Grouped by concern:

* **Provider (outbound)** — :class:`EmailProviderError` and its subclasses
  :class:`ProviderConfigError` / :class:`EmailSendError`, raised by the
  ``providers/`` layer.
* **Webhook (inbound)** — :class:`WebhookParseError`, raised by the
  ``webhooks/`` layer.
* **Service/persistence** — :class:`ConversationNotFoundError`,
  :class:`DuplicateConversationTokenError`, :class:`DraftNotSendableError`.

Keeping them all here means a caller can ``except`` a single module's error
types without importing from three different sub-packages.
"""


class EmailProviderError(Exception):
    """Base error for every outbound email-provider failure.

    Catching :class:`EmailProviderError` catches both configuration problems
    (:class:`ProviderConfigError`) and transmission failures
    (:class:`EmailSendError`).
    """


class ProviderConfigError(EmailProviderError):
    """Raised when a provider is missing required configuration.

    For example, selecting EngageLab without ``ENGAGELAB_API_USER`` set raises
    this with a message naming the missing variable.
    """


class EmailSendError(EmailProviderError):
    """Raised when a provider fails to transmit an outbound email.

    Wraps the underlying HTTP/SDK exception in one predictable type with a
    human-readable message so callers need not know which provider was used.
    """


class WebhookParseError(Exception):
    """Raised when an inbound webhook payload cannot be parsed.

    Carries a human-readable message describing what was malformed so the
    webhook route can log it and return a clear response.
    """


class ConversationNotFoundError(Exception):
    """Raised when a requested conversation does not exist or isn't owned by the caller."""


class DuplicateConversationTokenError(Exception):
    """Raised when a conversation's generated token collides with an existing one.

    The database's ``UNIQUE`` constraint on ``conversations.token`` is the real
    backstop; the service retries a fresh token a bounded number of times
    before surfacing this.
    """


class DraftNotSendableError(Exception):
    """Raised when an outbound send is attempted from a draft that isn't ready.

    A draft is sendable only once a human has verified it and it carries a
    recipient address — sending is never a side effect of drafting or editing.
    """
