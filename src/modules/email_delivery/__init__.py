"""Email-delivery module — outbound sending + inbound reply tracking.

Adapts the reference EmailPOC's multi-provider email system to this project's
modular, sync-SQLAlchemy architecture. Outbound sending is a Strategy+Factory
over providers; inbound parsing mirrors it. A tracked *conversation* ties an
outbound message to the supplier replies that thread back to it, and every
matched inbound reply is persisted against its owning user for future use.

    enums.py       -- ConversationStatus, EmailDirection, ReplyAction, ...
    exceptions.py  -- provider / webhook / service error types
    models.py      -- Conversation, Email, Attachment, UnmatchedEmail ORM models
    schemas.py     -- Pydantic request/response contracts
    providers/     -- outbound EmailMaster + EngageLab/SendGrid + factory (Strategy+Factory)
    webhooks/      -- inbound WebhookParserMaster + EngageLab/SendGrid + factory
    repository.py  -- data access (conversations/emails/attachments/unmatched)
    service.py     -- EmailDeliveryService (create / send_draft / send_rfq / handle_inbound)
    deps.py        -- FastAPI dependency wiring
    router.py      -- JSON API (/api/v1/email-delivery/...) + inbound webhook

``api_router`` (authenticated) and ``webhook_router`` (anonymous inbound) are
the two pieces the app factory mounts.
"""

from src.modules.email_delivery.router import router as api_router
from src.modules.email_delivery.router import webhook_router

__all__ = ["api_router", "webhook_router"]
