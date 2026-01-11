"""Сервис статистики и отчётов"""
from typing import Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, Integer
from sqlalchemy.sql import func as sql_func
from datetime import datetime, date, timedelta
from database.models import DailyRecord, User


async def get_weekly_statistics(session: AsyncSession, user_id: int) -> Dict[str, Any]:
    """Получить статистику за неделю"""
    from sqlalchemy import case
    
    today = date.today()
    week_ago = today - timedelta(days=7)
    
    result = await session.execute(
        select(
            func.avg(DailyRecord.morning_energy).label("avg_morning_energy"),
            func.avg(DailyRecord.total_calories).label("avg_calories"),
            func.avg(DailyRecord.total_protein).label("avg_protein"),
            func.avg(DailyRecord.daily_steps).label("avg_steps"),
            func.count(DailyRecord.id).label("total_days"),
            func.sum(case((DailyRecord.physical_activity == True, 1), else_=0)).label("activity_days")
        ).where(
            DailyRecord.user_id == user_id,
            func.date(DailyRecord.date) >= week_ago,
            func.date(DailyRecord.date) <= today
        )
    )
    
    stats = result.first()
    
    return {
        "avg_morning_energy": float(stats.avg_morning_energy or 0),
        "avg_calories": float(stats.avg_calories or 0),
        "avg_protein": float(stats.avg_protein or 0),
        "avg_steps": float(stats.avg_steps or 0),
        "total_days": int(stats.total_days or 0),
        "activity_days": int(stats.activity_days or 0)
    }


async def get_monthly_statistics(session: AsyncSession, user_id: int) -> Dict[str, Any]:
    """Получить статистику за месяц"""
    from sqlalchemy import case
    
    today = date.today()
    month_ago = today - timedelta(days=30)
    
    result = await session.execute(
        select(
            func.avg(DailyRecord.morning_energy).label("avg_morning_energy"),
            func.avg(DailyRecord.total_calories).label("avg_calories"),
            func.avg(DailyRecord.total_protein).label("avg_protein"),
            func.avg(DailyRecord.daily_steps).label("avg_steps"),
            func.count(DailyRecord.id).label("total_days"),
            func.sum(case((DailyRecord.physical_activity == True, 1), else_=0)).label("activity_days")
        ).where(
            DailyRecord.user_id == user_id,
            func.date(DailyRecord.date) >= month_ago,
            func.date(DailyRecord.date) <= today
        )
    )
    
    stats = result.first()
    
    return {
        "avg_morning_energy": float(stats.avg_morning_energy or 0),
        "avg_calories": float(stats.avg_calories or 0),
        "avg_protein": float(stats.avg_protein or 0),
        "avg_steps": float(stats.avg_steps or 0),
        "total_days": int(stats.total_days or 0),
        "activity_days": int(stats.activity_days or 0)
    }


async def get_admin_statistics(session: AsyncSession) -> Dict[str, Any]:
    """Получить обезличенную статистику для администратора"""
    
    result = await session.execute(
        select(
            func.avg(DailyRecord.morning_energy).label("avg_morning_energy"),
            func.avg(DailyRecord.total_calories).label("avg_calories"),
            func.avg(DailyRecord.total_protein).label("avg_protein"),
            func.avg(DailyRecord.daily_steps).label("avg_steps"),
            func.count(func.distinct(DailyRecord.user_id)).label("total_users"),
            func.count(DailyRecord.id).label("total_records")
        ).where(
            func.date(DailyRecord.date) >= date.today() - timedelta(days=7)
        )
    )
    
    stats = result.first()
    
    return {
        "avg_morning_energy": float(stats.avg_morning_energy or 0),
        "avg_calories": float(stats.avg_calories or 0),
        "avg_protein": float(stats.avg_protein or 0),
        "avg_steps": float(stats.avg_steps or 0),
        "total_users": int(stats.total_users or 0),
        "total_records": int(stats.total_records or 0)
    }
