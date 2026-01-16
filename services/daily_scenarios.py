"""Сервис ежедневных сценариев"""
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.sql import func
from datetime import datetime, date, timedelta
from database.models import User, DailyRecord, Questionnaire
from utils.templates import (
    MORNING_GREETINGS, WATER_TIPS, WATER_TIPS_EXTENDED,
    get_morning_sleep_question, get_food_reminder,
    MORNING_SLEEP_OPTIONS, EVENING_MOOD_OPTIONS, EVENING_STOOL_OPTIONS,
    MORNING_WISHES, EVENING_WISHES
)
import random


async def get_or_create_daily_record(session: AsyncSession, user_id: int, target_date: Optional[date] = None) -> DailyRecord:
    """Получить или создать ежедневную запись"""
    if target_date is None:
        target_date = date.today()
    
    target_datetime = datetime.combine(target_date, datetime.min.time())
    
    result = await session.execute(
        select(DailyRecord).where(
            DailyRecord.user_id == user_id,
            func.date(DailyRecord.date) == target_date
        )
    )
    daily_record = result.scalar_one_or_none()
    
    if not daily_record:
        daily_record = DailyRecord(
            user_id=user_id,
            date=target_datetime
        )
        session.add(daily_record)
        await session.commit()
        await session.refresh(daily_record)
    
    return daily_record


async def save_morning_sleep_quality(session: AsyncSession, user_id: int, sleep_quality: str) -> None:
    """Сохранить качество сна утром (новый формат)"""
    daily_record = await get_or_create_daily_record(session, user_id)
    daily_record.morning_sleep_quality = sleep_quality
    await session.commit()


async def save_morning_sleep_hours(session: AsyncSession, user_id: int, sleep_hours: int) -> None:
    """Сохранить количество часов сна утром"""
    daily_record = await get_or_create_daily_record(session, user_id)
    daily_record.morning_sleep_hours = sleep_hours
    await session.commit()


async def save_morning_energy(session: AsyncSession, user_id: int, energy: int) -> None:
    """Сохранить уровень энергии утром (1-5)"""
    daily_record = await get_or_create_daily_record(session, user_id)
    daily_record.morning_energy = energy
    await session.commit()


async def save_evening_report(
    session: AsyncSession,
    user_id: int,
    mood: Optional[str] = None,
    steps: Optional[int] = None,
    physical_activity: Optional[bool] = None,
    stool: Optional[str] = None,
    wellbeing: Optional[int] = None,
    energy: Optional[int] = None
) -> Dict[str, Any]:
    """Сохранить вечерний отчёт (новый формат или старый для совместимости)"""
    daily_record = await get_or_create_daily_record(session, user_id)
    
    # Новый формат
    if mood:
        daily_record.evening_mood = mood
    
    # Старый формат (для совместимости)
    if wellbeing is not None:
        # Конвертируем старый формат в новый (приблизительно)
        if wellbeing >= 8:
            daily_record.evening_mood = "Очень довольна собой, отличное настроение"
        elif wellbeing >= 6:
            daily_record.evening_mood = "Хорошее настроение, удовлетворение"
        elif wellbeing >= 4:
            daily_record.evening_mood = "Спокойно, без сильных эмоций"
        elif wellbeing >= 2:
            daily_record.evening_mood = "Усталость, апатия"
        else:
            daily_record.evening_mood = "Раздражение, напряжение"
    
    if steps is not None:
        daily_record.daily_steps = steps
    if physical_activity is not None:
        daily_record.physical_activity = physical_activity
    if stool:
        daily_record.evening_stool = stool
    
    await session.commit()
    
    return {
        "message": f"{random.choice(EVENING_WISHES)}",
        "mood": daily_record.evening_mood or mood
    }


def get_morning_greeting() -> str:
    """Получить утреннее приветствие (с ротацией)"""
    return random.choice(MORNING_GREETINGS)


def get_water_tip() -> str:
    """Получить совет о воде (с ротацией) - расширенный список"""
    return random.choice(WATER_TIPS_EXTENDED)


def get_morning_wish() -> str:
    """Получить пожелание дня"""
    return random.choice(MORNING_WISHES)


async def check_daily_reminders_needed(session: AsyncSession, user_id: int) -> Dict[str, bool]:
    """Проверить, какие напоминания нужно отправить"""
    daily_record = await get_or_create_daily_record(session, user_id)
    
    return {
        "morning_sleep": daily_record.morning_sleep_quality is None,
        "morning_energy": daily_record.morning_energy is None,
        "food_photo": daily_record.total_calories == 0,  # Если нет записей о еде
        "evening_report": daily_record.evening_mood is None
    }
