"""FastAPI dependency wiring for the email-delivery module."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from src.config import Settings, get_settings
from src.integrations.database import get_db_session
from src.modules.email_delivery.repository import EmailDeliveryRepository
from src.modules.email_delivery.service import EmailDeliveryService


def get_email_delivery_repository(
    session: Annotated[Session, Depends(get_db_session)],
) -> EmailDeliveryRepository:
    """Return a request-scoped :class:`EmailDeliveryRepository`."""
    return EmailDeliveryRepository(session)


def get_email_delivery_service(
    repository: Annotated[EmailDeliveryRepository, Depends(get_email_delivery_repository)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> EmailDeliveryService:
    """Compose an :class:`EmailDeliveryService` for the current request.

    Args:
        repository: Request-scoped email-delivery data access.
        settings: Application settings (provider selection + credentials).

    Returns:
        A fully wired :class:`EmailDeliveryService`.
    """
    return EmailDeliveryService(repository, settings)


EmailDeliveryServiceDep = Annotated[EmailDeliveryService, Depends(get_email_delivery_service)]
