"""Сервис для работы с ежемесячными замерами (вес и обхваты)"""
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, date
from database.models import MonthlyMeasurement, User


async def save_monthly_measurement(
    session: AsyncSession,
    user_id: int,
    weight: Optional[float] = None,
    waist_circumference: Optional[float] = None,
    hips_circumference: Optional[float] = None,
    chest_circumference: Optional[float] = None
) -> MonthlyMeasurement:
    """
    Сохранить ежемесячные замеры
    
    Args:
        session: SQLAlchemy сессия
        user_id: ID пользователя
        weight: Вес (кг)
        waist_circumference: Обхват талии (см)
        hips_circumference: Обхват бедер (см)
        chest_circumference: Обхват груди (см)
    
    Returns:
        MonthlyMeasurement: Сохраненная запись замеров
    """
    today = date.today()
    # Используем первый день месяца как ключ
    measurement_date = date(today.year, today.month, 1)
    
    # Проверяем, есть ли уже замеры за этот месяц
    result = await session.execute(
        select(MonthlyMeasurement).where(
            MonthlyMeasurement.user_id == user_id,
            func.date(MonthlyMeasurement.measurement_date) == measurement_date
        )
    )
    existing = result.scalar_one_or_none()
    
    if existing:
        # Обновляем существующую запись
        if weight is not None:
            existing.weight = weight
        if waist_circumference is not None:
            existing.waist_circumference = waist_circumference
        if hips_circumference is not None:
            existing.hips_circumference = hips_circumference
        if chest_circumference is not None:
            existing.chest_circumference = chest_circumference
        existing.updated_at = datetime.now()
        await session.commit()
        await session.refresh(existing)
        return existing
    else:
        # Создаем новую запись
        measurement = MonthlyMeasurement(
            user_id=user_id,
            measurement_date=datetime.combine(measurement_date, datetime.min.time()),
            weight=weight,
            waist_circumference=waist_circumference,
            hips_circumference=hips_circumference,
            chest_circumference=chest_circumference
        )
        session.add(measurement)
        await session.commit()
        await session.refresh(measurement)
        return measurement


async def get_current_month_measurement(
    session: AsyncSession,
    user_id: int
) -> Optional[MonthlyMeasurement]:
    """Получить замеры за текущий месяц"""
    today = date.today()
    measurement_date = date(today.year, today.month, 1)
    
    result = await session.execute(
        select(MonthlyMeasurement).where(
            MonthlyMeasurement.user_id == user_id,
            func.date(MonthlyMeasurement.measurement_date) == measurement_date
        )
    )
    return result.scalar_one_or_none()


async def get_previous_month_measurement(
    session: AsyncSession,
    user_id: int
) -> Optional[MonthlyMeasurement]:
    """Получить замеры за предыдущий месяц"""
    today = date.today()
    # Получаем первый день предыдущего месяца
    if today.month == 1:
        prev_month = 12
        prev_year = today.year - 1
    else:
        prev_month = today.month - 1
        prev_year = today.year
    
    measurement_date = date(prev_year, prev_month, 1)
    
    result = await session.execute(
        select(MonthlyMeasurement).where(
            MonthlyMeasurement.user_id == user_id,
            func.date(MonthlyMeasurement.measurement_date) == measurement_date
        ).order_by(MonthlyMeasurement.created_at.desc())
    )
    return result.scalar_one_or_none()
