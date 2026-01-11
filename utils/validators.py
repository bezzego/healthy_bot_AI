"""Валидация данных"""
from typing import Optional, Tuple


def validate_height(height: float) -> Tuple[bool, Optional[str]]:
    """Валидация роста"""
    if height < 100 or height > 250:
        return False, "Рост должен быть от 100 до 250 см"
    return True, None


def validate_weight(weight: float) -> Tuple[bool, Optional[str]]:
    """Валидация веса"""
    if weight < 20 or weight > 300:
        return False, "Вес должен быть от 20 до 300 кг"
    return True, None


def validate_scale_value(value: int, min_val: int = 0, max_val: int = 10) -> Tuple[bool, Optional[str]]:
    """Валидация значения по шкале"""
    if value < min_val or value > max_val:
        return False, f"Значение должно быть от {min_val} до {max_val}"
    return True, None


def validate_scale_0_5(value: int) -> Tuple[bool, Optional[str]]:
    """Валидация значения по шкале 0-5 (устарело, используйте validate_scale_1_5)"""
    return validate_scale_value(value, 0, 5)


def validate_scale_1_5(value: int) -> Tuple[bool, Optional[str]]:
    """Валидация значения по шкале 1-5"""
    return validate_scale_value(value, 1, 5)


def validate_steps(steps: int) -> Tuple[bool, Optional[str]]:
    """Валидация количества шагов"""
    if steps < 0 or steps > 100000:
        return False, "Количество шагов должно быть от 0 до 100000"
    return True, None


def validate_calories(calories: float) -> Tuple[bool, Optional[str]]:
    """Валидация калорий"""
    if calories < 0 or calories > 10000:
        return False, "Калорийность должна быть от 0 до 10000 ккал"
    return True, None


def parse_number(text: str) -> Tuple[bool, Optional[float], Optional[str]]:
    """Попытаться распарсить число из текста"""
    try:
        # Убираем все пробелы и заменяем запятую на точку
        cleaned = text.strip().replace(",", ".").replace(" ", "")
        value = float(cleaned)
        return True, value, None
    except ValueError:
        return False, None, "Не удалось распознать число. Пожалуйста, введите числовое значение."
