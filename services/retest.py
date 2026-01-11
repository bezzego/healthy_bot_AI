"""Сервис повторного тестирования"""
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timedelta
from database.models import Questionnaire, User
from services.onboarding import (
    QUESTIONNAIRE_FLOW, get_current_question, get_question_type, QUESTION_OPTIONS
)
from utils.calculations import (
    calculate_bmi, get_bmi_category, calculate_health_score,
    calculate_recommended_calories, calculate_bju, calculate_water_norm
)
from utils.templates import get_question_text


async def can_start_retest(session: AsyncSession, user_id: int) -> tuple[bool, Optional[str]]:  # type: ignore
    """Проверить, можно ли начать повторное тестирование"""
    # Проверяем, прошёл ли первичное тестирование
    primary_result = await session.execute(
        select(Questionnaire).where(
            Questionnaire.user_id == user_id,
            Questionnaire.type == "primary"
        ).order_by(Questionnaire.created_at.desc()).limit(1)
    )
    primary = primary_result.scalar_one_or_none()
    
    if not primary:
        return False, "Сначала нужно пройти первичное тестирование"
    
    # Проверяем, прошёл ли месяц с последнего тестирования
    last_retest_result = await session.execute(
        select(Questionnaire).where(
            Questionnaire.user_id == user_id,
            Questionnaire.type == "retest"
        ).order_by(Questionnaire.created_at.desc()).limit(1)
    )
    last_retest = last_retest_result.scalar_one_or_none()
    
    if last_retest:
        time_since_retest = datetime.now() - last_retest.created_at
        if time_since_retest < timedelta(days=30):
            days_left = 30 - time_since_retest.days
            return False, f"Повторное тестирование можно пройти через {days_left} дней"
    
    # Проверяем, прошёл ли месяц с первичного тестирования
    time_since_primary = datetime.now() - primary.created_at
    if time_since_primary < timedelta(days=30):
        days_left = 30 - time_since_primary.days
        return False, f"Повторное тестирование можно пройти через {days_left} дней после первичного"
    
    return True, None


async def start_retest(session: AsyncSession, user_id: int) -> Dict[str, Any]:
    """Начать процесс повторного тестирования"""
    can_start, error = await can_start_retest(session, user_id)
    if not can_start:
        return {"error": error}
    
    user = await session.get(User, user_id)
    if not user:
        return {"error": "User not found"}
    
    # Обновляем статус (для совместимости)
    user.current_state = "retest_in_progress"
    
    await session.commit()
    
    from services.onboarding import get_current_question
    return {
        "message": "🔄 Начинаем повторное тестирование. Ответьте на те же вопросы, что и в первый раз.",
        "current_question": get_current_question(0, {})
    }


async def save_retest_answer(session: AsyncSession, user_id: int, answer: Any, state_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Сохранить ответ на вопрос повторного тестирования"""
    user = await session.get(User, user_id)
    if not user:
        return {"error": "User not found"}
    
    # Используем переданное состояние или создаём новое
    if state_data is None:
        state_data = user.state_data or {}
    
    current_index = state_data.get("current_question_index", 0)
    answers = state_data.get("answers", {})
    
    question_key = QUESTIONNAIRE_FLOW[current_index]
    answers[question_key] = answer
    
    # Если вопрос про головные боли = нет, пропускаем вопрос о частоте
    if question_key == "headaches" and not answer:
        current_index += 2
    else:
        current_index += 1
    
    state_data["current_question_index"] = current_index
    state_data["answers"] = answers
    
    # Сохраняем в БД для совместимости
    user.state_data = state_data
    await session.commit()
    
    # Проверяем, завершена ли анкета
    if current_index >= len(QUESTIONNAIRE_FLOW):
        return await complete_retest(session, user_id, answers)
    
    from services.onboarding import get_current_question
    next_question = get_current_question(current_index, answers)
    return {
        "completed": False,
        "next_question": next_question,
        "state_data": state_data
    }


async def complete_retest(session: AsyncSession, user_id: int, answers: Dict[str, Any]) -> Dict[str, Any]:
    """Завершить повторное тестирование и сравнить с первичным"""
    user = await session.get(User, user_id)
    if not user:
        return {"error": "User not found"}
    
    # Получаем первичную анкету
    primary_result = await session.execute(
        select(Questionnaire).where(
            Questionnaire.user_id == user_id,
            Questionnaire.type == "primary"
        ).order_by(Questionnaire.created_at.desc()).limit(1)
    )
    primary = primary_result.scalar_one_or_none()
    
    if not primary:
        return {"error": "Primary questionnaire not found"}
    
    # Создаём запись повторной анкеты
    retest = Questionnaire(
        user_id=user_id,
        type="retest",
        **{k: v for k, v in answers.items() if hasattr(Questionnaire, k)}
    )
    
    # Рассчитываем показатели
    height = answers.get("height") or primary.height
    weight = answers.get("weight") or primary.weight
    
    if height and weight:
        bmi = calculate_bmi(height, weight)
        retest.bmi = bmi
        retest.health_score = calculate_health_score(answers)
        
        # Профессиональный расчет калорий с использованием данных из первичной анкеты
        # Определяем пол из поля gender (предпочтительно) или из первичной анкеты
        gender = answers.get("gender") or (getattr(primary, 'gender', None) if primary else None)
        if gender is None:
            # Fallback: пытаемся определить из menstrual_cycle (для старых данных)
            menstrual_cycle = answers.get("menstrual_cycle") or (getattr(primary, 'menstrual_cycle', None) if primary else None)
            if isinstance(menstrual_cycle, str) and menstrual_cycle == "я мужчина":
                gender = "male"
            else:
                gender = "female"  # По умолчанию female для безопасности
        
        average_steps = answers.get("average_steps") or (getattr(primary, 'average_steps', None) if primary else None)
        additional_activity = answers.get("additional_activity_frequency") or (getattr(primary, 'additional_activity_frequency', None) if primary else None)
        
        recommended_calories = calculate_recommended_calories(
            bmi=bmi,
            weight=weight,
            height=height,
            gender=gender,
            age=None,  # Возраст не в анкете, используем среднее значение 30
            average_steps=average_steps,
            additional_activity=additional_activity
        )
        retest.recommended_calories = recommended_calories
        
        goal = "weight_loss" if bmi >= 25 else ("weight_gain" if bmi < 18.5 else "maintenance")
        bju = calculate_bju(recommended_calories, bmi=bmi, goal=goal)
        retest.recommended_protein = bju["protein"]
        retest.recommended_fats = bju["fats"]
        retest.recommended_carbs = bju["carbs"]
        retest.recommended_water = calculate_water_norm(weight)
    
    session.add(retest)
    
    # Формируем сравнительную таблицу
    comparison_message = format_retest_comparison(primary, retest)
    
    user.current_state = "main_menu"
    user.state_data = {}  # Очищаем состояние
    
    await session.commit()
    
    return {
        "completed": True,
        "message": comparison_message,
        "retest_id": retest.id
    }


def format_retest_comparison(primary: Questionnaire, retest: Questionnaire) -> str:
    """Форматировать сравнение результатов тестирования"""
    text = "📊 СРАВНЕНИЕ РЕЗУЛЬТАТОВ\n\n"
    text += "📋 БЫЛО → СТАЛО\n\n"
    
    if primary.weight and retest.weight:
        text += f"⚖️ Вес: {primary.weight} кг → {retest.weight} кг "
        weight_diff = retest.weight - primary.weight
        if weight_diff > 0:
            text += f"(+{weight_diff:.1f} кг)\n"
        elif weight_diff < 0:
            text += f"({weight_diff:.1f} кг)\n"
        else:
            text += "(без изменений)\n"
    
    if primary.bmi and retest.bmi:
        text += f"📈 ИМТ: {primary.bmi} → {retest.bmi} "
        bmi_diff = retest.bmi - primary.bmi
        if bmi_diff > 0:
            text += f"(+{bmi_diff:.1f})\n"
        elif bmi_diff < 0:
            text += f"({bmi_diff:.1f})\n"
        else:
            text += "(без изменений)\n"
    
    if primary.health_score and retest.health_score:
        text += f"⭐ Балл здоровья: {primary.health_score} → {retest.health_score} "
        score_diff = retest.health_score - primary.health_score
        if score_diff > 0:
            text += f"(+{score_diff:.1f}) 📈\n"
        elif score_diff < 0:
            text += f"({score_diff:.1f}) 📉\n"
        else:
            text += "(без изменений)\n"
    
    if primary.energy_level is not None and retest.energy_level is not None:
        text += f"⚡ Энергия: {primary.energy_level}/10 → {retest.energy_level}/10\n"
    
    if primary.sleep_quality is not None and retest.sleep_quality is not None:
        text += f"😴 Сон: {primary.sleep_quality}/10 → {retest.sleep_quality}/10\n"
    
    if primary.stress_level is not None and retest.stress_level is not None:
        text += f"😰 Стресс: {primary.stress_level}/10 → {retest.stress_level}/10\n"
    
    text += "\n✅ Повторное тестирование завершено!"
    
    return text
