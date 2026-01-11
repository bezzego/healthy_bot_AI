"""Сервис работы с питанием"""
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, date
from database.models import NutritionRecord, DailyRecord, User
from utils.validators import validate_calories
from utils.calculations import calculate_bju


async def add_nutrition_record(
    session: AsyncSession,
    user_id: int,
    food_name: str,
    calories: float,
    protein: float = 0,
    fats: float = 0,
    carbs: float = 0,
    fiber: float = 0,
    photo_file_id: Optional[str] = None
) -> NutritionRecord:
    """Добавить запись о питании"""
    # Валидация
    is_valid, error = validate_calories(calories)
    if not is_valid:
        raise ValueError(error)
    
    # Получаем или создаём дневную запись
    from services.daily_scenarios import get_or_create_daily_record
    daily_record = await get_or_create_daily_record(session, user_id)
    
    # Создаём запись о питании
    nutrition_record = NutritionRecord(
        user_id=user_id,
        daily_record_id=daily_record.id,
        food_name=food_name,
        calories=calories,
        protein=protein,
        fats=fats,
        carbs=carbs,
        fiber=fiber,
        photo_file_id=photo_file_id,
        meal_time=datetime.now()
    )
    
    session.add(nutrition_record)
    
    # Обновляем дневную запись
    daily_record.total_calories += calories
    daily_record.total_protein += protein
    daily_record.total_fats += fats
    daily_record.total_carbs += carbs
    daily_record.total_fiber += fiber
    
    await session.commit()
    await session.refresh(nutrition_record)
    
    return nutrition_record


async def get_today_nutrition(session: AsyncSession, user_id: int) -> Dict[str, Any]:
    """Получить питание за сегодня"""
    today = date.today()
    
    daily_record_result = await session.execute(
        select(DailyRecord).where(
            DailyRecord.user_id == user_id,
            func.date(DailyRecord.date) == today
        )
    )
    daily_record = daily_record_result.scalar_one_or_none()
    
    if not daily_record:
        return {
            "total_calories": 0,
            "total_protein": 0,
            "total_fats": 0,
            "total_carbs": 0,
            "total_fiber": 0,
            "records": []
        }
    
    # Получаем все записи о питании за день
    records_result = await session.execute(
        select(NutritionRecord).where(
            NutritionRecord.daily_record_id == daily_record.id
        ).order_by(NutritionRecord.meal_time)
    )
    records = records_result.scalars().all()
    
    return {
        "total_calories": daily_record.total_calories,
        "total_protein": daily_record.total_protein,
        "total_fats": daily_record.total_fats,
        "total_carbs": daily_record.total_carbs,
        "total_fiber": daily_record.total_fiber,
        "records": [
            {
                "id": r.id,
                "food_name": r.food_name,
                "calories": r.calories,
                "protein": r.protein,
                "fats": r.fats,
                "carbs": r.carbs,
                "meal_time": r.meal_time
            }
            for r in records
        ]
    }


async def delete_nutrition_record(session: AsyncSession, record_id: int, user_id: int) -> bool:
    """Удалить запись о питании"""
    result = await session.execute(
        select(NutritionRecord).where(
            NutritionRecord.id == record_id,
            NutritionRecord.user_id == user_id
        )
    )
    record = result.scalar_one_or_none()
    
    if not record:
        return False
    
    # Обновляем дневную запись
    if record.daily_record_id:
        daily_record = await session.get(DailyRecord, record.daily_record_id)
        if daily_record:
            daily_record.total_calories -= record.calories
            daily_record.total_protein -= record.protein
            daily_record.total_fats -= record.fats
            daily_record.total_carbs -= record.carbs
            daily_record.total_fiber -= record.fiber
    
    await session.delete(record)
    await session.commit()
    
    return True


# Справочник продуктов (базовый)
FOOD_DATABASE = {
    "яблоко": {"calories": 52, "protein": 0.3, "fats": 0.2, "carbs": 14, "fiber": 2.4},
    "банан": {"calories": 89, "protein": 1.1, "fats": 0.3, "carbs": 23, "fiber": 2.6},
    "куриная грудка": {"calories": 165, "protein": 31, "fats": 3.6, "carbs": 0, "fiber": 0},
    "рис вареный": {"calories": 130, "protein": 2.7, "fats": 0.3, "carbs": 28, "fiber": 0.4},
    "гречка": {"calories": 110, "protein": 4.2, "fats": 1.1, "carbs": 21, "fiber": 2.7},
    "овсянка": {"calories": 68, "protein": 2.4, "fats": 1.4, "carbs": 12, "fiber": 1.7},
    "яйцо": {"calories": 155, "protein": 13, "fats": 11, "carbs": 1.1, "fiber": 0},
    "творог": {"calories": 98, "protein": 16, "fats": 0.6, "carbs": 1.8, "fiber": 0},
    "овощной салат": {"calories": 25, "protein": 1, "fats": 0.2, "carbs": 5, "fiber": 2},
    "суп": {"calories": 50, "protein": 2, "fats": 1, "carbs": 8, "fiber": 1.5},
}


def search_food_in_database(query: str) -> List[Dict[str, Any]]:
    """Поиск продукта в справочнике"""
    query_lower = query.lower().strip()
    results = []
    
    for food_name, nutrition in FOOD_DATABASE.items():
        if query_lower in food_name.lower():
            results.append({
                "name": food_name,
                **nutrition
            })
    
    return results[:10]  # Максимум 10 результатов
