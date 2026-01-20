"""FSM состояния для aiogram"""
from aiogram.fsm.state import State, StatesGroup


class OnboardingStates(StatesGroup):
    """Состояния онбординга"""
    in_progress = State()


class RetestStates(StatesGroup):
    """Состояния повторного тестирования"""
    in_progress = State()


class AddingFoodStates(StatesGroup):
    """Состояния добавления еды"""
    waiting_for_food = State()
    waiting_for_calories = State()
    waiting_for_food_confirmation = State()
    waiting_for_food_correction = State()


class WaterStates(StatesGroup):
    """Состояния для ввода воды"""
    waiting_for_water_manual = State()


class AdminRequestStates(StatesGroup):
    """Состояния обращения к администратору"""
    waiting_for_message = State()
    waiting_for_recipe_composition = State()
    waiting_for_recipe_description = State()
    waiting_for_recipe_photo = State()
    waiting_for_results_data = State()


class NotificationSettingsStates(StatesGroup):
    """Состояния настройки уведомлений"""
    waiting_for_timezone = State()
    waiting_for_morning_time = State()
    waiting_for_evening_time = State()


class MorningCheckinStates(StatesGroup):
    """Состояния утреннего чек-ина"""
    waiting_for_sleep_quality = State()
    waiting_for_sleep_hours = State()
    waiting_for_energy = State()


class EveningCheckinStates(StatesGroup):
    """Состояния вечернего чек-ина"""
    waiting_for_mood = State()
    waiting_for_steps = State()
    waiting_for_activity = State()
    waiting_for_activity_duration = State()  # Продолжительность активности в минутах
    waiting_for_stool = State()


class MonthlyMeasurementStates(StatesGroup):
    """Состояния ежемесячных замеров"""
    waiting_for_weight = State()
    waiting_for_waist = State()
    waiting_for_hips = State()
    waiting_for_chest = State()


# Импортируем в __init__ handlers для удобства
__all__ = [
    'OnboardingStates',
    'RetestStates',
    'AddingFoodStates',
    'AdminRequestStates',
    'NotificationSettingsStates',
    'MorningCheckinStates',
    'EveningCheckinStates',
    'MonthlyMeasurementStates',
    'WaterStates'
]
