"""Сервис администратора"""
from typing import Dict, Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
from database.models import AdminRequest, User
from config import settings


async def create_admin_request(
    session: AsyncSession,
    user_id: int,
    request_type: str,
    **kwargs
) -> AdminRequest:
    """Создать обращение к администратору"""
    request = AdminRequest(
        user_id=user_id,
        request_type=request_type,
        **{k: v for k, v in kwargs.items() if hasattr(AdminRequest, k)}
    )
    
    session.add(request)
    await session.commit()
    await session.refresh(request)
    
    return request


async def get_pending_requests(session: AsyncSession) -> List[AdminRequest]:
    """Получить все ожидающие обращения с загруженными пользователями"""
    from sqlalchemy.orm import joinedload
    
    result = await session.execute(
        select(AdminRequest)
        .where(AdminRequest.status == "pending")
        .options(joinedload(AdminRequest.user))
        .order_by(AdminRequest.created_at.desc())
    )
    return list(result.scalars().unique().all())


async def update_request_status(
    session: AsyncSession,
    request_id: int,
    status: str,
    admin_response: Optional[str] = None
) -> bool:
    """Обновить статус обращения"""
    request = await session.get(AdminRequest, request_id)
    if not request:
        return False
    
    request.status = status
    if admin_response:
        request.admin_response = admin_response
    request.updated_at = datetime.now()
    
    await session.commit()
    return True


def is_admin(user_id: int) -> bool:
    """Проверить, является ли пользователь администратором"""
    return user_id in settings.admin_ids


async def get_user_by_telegram_id(session: AsyncSession, telegram_id: int) -> Optional[User]:
    """Получить пользователя по telegram_id"""
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    return result.scalar_one_or_none()
