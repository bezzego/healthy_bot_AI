"""Калькулятор калорий для активностей"""
from typing import Optional, Tuple
from utils.templates import ACTIVITY_TYPES


def calculate_activity_calories(activity_name: str, duration_minutes: int, weight_kg: Optional[float] = None) -> float:
    """
    Рассчитать калории, потраченные на активность
    
    Args:
        activity_name: Название активности
        duration_minutes: Продолжительность в минутах
        weight_kg: Вес пользователя в кг (если None, используется средний вес 70кг)
    
    Returns:
        Количество потраченных калорий
    """
    if duration_minutes <= 0:
        return 0.0
    
    # Находим активность в справочнике
    activity = None
    for name, calories_per_hour, _ in ACTIVITY_TYPES:
        if name == activity_name:
            activity = (name, calories_per_hour, _)
            break
    
    if not activity:
        # Если активность не найдена, используем среднее значение
        calories_per_hour = 300
    else:
        calories_per_hour = activity[1]
    
    # Если вес не указан, используем средний вес 70кг
    if weight_kg is None:
        weight_kg = 70.0
    
    # Корректируем калории в зависимости от веса (линейная зависимость)
    # Для веса 70кг коэффициент = 1.0
    weight_coefficient = weight_kg / 70.0
    
    # Рассчитываем калории: (ккал/час) * (часы) * коэффициент_веса
    hours = duration_minutes / 60.0
    calories = calories_per_hour * hours * weight_coefficient
    
    return round(calories, 1)


def get_activity_info(activity_name: str) -> Optional[Tuple[str, int, str]]:
    """Получить информацию об активности"""
    for name, calories_per_hour, description in ACTIVITY_TYPES:
        if name == activity_name:
            return (name, calories_per_hour, description)
    return None
