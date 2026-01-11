"""Сервис онбординга и анкетирования"""
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
from database.models import User, Questionnaire
from utils.calculations import (
    calculate_bmi, get_bmi_category, calculate_health_score,
    calculate_recommended_calories, calculate_bju, calculate_water_norm,
    get_recommendations
)
from utils.templates import (
    get_onboarding_welcome, format_questionnaire_results, format_questionnaire_results_new, get_question_text
)


# Порядок вопросов анкеты согласно новому ТЗ
# ВАЖНО: gender должен быть первым, чтобы определять, какие вопросы показывать
QUESTIONNAIRE_FLOW = [
    # Пол (определяется первым для персонализации анкеты)
    "gender",
    
    # Антропометрия
    "height",
    "weight",
    "chest_circumference",
    "waist_circumference",
    "hips_circumference",
    
    # ЖКТ
    "stool_frequency",
    "stool_character",
    
    # Менструальный цикл (только для женщин)
    "menstrual_cycle",
    
    # Самочувствие (шкала 1-5)
    "energy_level",
    "stress_level",
    "sleep_quality",
    "concentration",
    "irritability",
    "sleepiness",
    
    # Аппетит и тяги
    "appetite",
    "sugar_craving",
    "fat_craving",
    
    # Дополнительные симптомы
    "shortness_of_breath",
    "cold_hands_feet",
    "skin_itch",
    "blue_sclera",
    "headaches",
    "oily_skin",
    "dry_skin",
    "low_libido",
    "vaginal_itch",  # Только для женщин
    "joint_pain",
    "abdominal_cramps",
    "gas",
    "hair_loss",
    "dry_mouth",
    
    # Физическая активность
    "average_steps",
    "additional_activity_frequency",
]


# Опции для вопросов с выбором
QUESTION_OPTIONS = {
    "gender": [
        "мужской",
        "женский"
    ],
    "stool_frequency": [
        "2–3 раза в сутки",
        "1 раз в сутки",
        "1 раз в 1–2 дня",
        "1 раз в 2–3 дня",
        "1 раз в 3–5 дней"
    ],
    "stool_character": [
        "оформленный, нормальный",
        "твёрдый",
        "жидкий",
        "иногда твёрдый, иногда жидкий",
        "чередуется"
    ],
    "menstrual_cycle": [
        "я женщина, цикла нет",
        "регулярный",
        "нерегулярный"
    ],
    "appetite": [
        "нормальный",
        "повышенный",
        "пониженный"
    ],
    "additional_activity_frequency": [
        "нет",
        "1-2 раза в неделю",
        "3 и более раз в неделю"
    ],
}


async def get_or_create_user(session: AsyncSession, telegram_id: int, username: Optional[str] = None,
                             first_name: Optional[str] = None, last_name: Optional[str] = None) -> User:
    """Получить или создать пользователя"""
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    
    if not user:
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            current_state="onboarding_start"
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return user


async def start_onboarding(session: AsyncSession, user_id: int) -> Dict[str, Any]:
    """Начать процесс онбординга"""
    user = await session.get(User, user_id)
    if not user:
        raise ValueError("User not found")
    
    # Обновляем статус пользователя (для совместимости со старой БД)
    user.current_state = "onboarding_in_progress"
    
    await session.commit()
    
    return {
        "message": get_onboarding_welcome(),
        "current_question": get_current_question(0, {})
    }


def get_current_question(index: int, answers: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Получить текущий вопрос по индексу с учетом пола пользователя"""
    if answers is None:
        answers = {}
    
    if index >= len(QUESTIONNAIRE_FLOW):
        return None
    
    # Определяем пол пользователя
    gender = answers.get("gender")
    
    # Находим следующий вопрос, который нужно задать (пропускаем вопросы для противоположного пола)
    while index < len(QUESTIONNAIRE_FLOW):
        question_key = QUESTIONNAIRE_FLOW[index]
        
        # Пропускаем вопросы, которые не относятся к полу пользователя
        if should_skip_question(question_key, gender):
            index += 1
            continue
        
        return {
            "key": question_key,
            "text": get_question_text(question_key),
            "type": get_question_type(question_key),
            "options": QUESTION_OPTIONS.get(question_key),
            "optional": question_key in ["chest_circumference", "waist_circumference", "hips_circumference"]
        }
    
    return None


def get_question_type(question_key: str) -> str:
    """Определить тип вопроса"""
    if question_key in ["height", "weight", "chest_circumference", "waist_circumference", 
                       "hips_circumference", "average_steps"]:
        return "number"
    elif question_key in ["energy_level", "stress_level", "sleep_quality"]:
        return "scale_1_5"  # Шкала 1-5
    elif question_key in QUESTION_OPTIONS:
        return "choice"
    elif question_key in ["concentration", "irritability", "sleepiness", "sugar_craving", 
                          "fat_craving", "shortness_of_breath", "cold_hands_feet", "skin_itch",
                          "blue_sclera", "headaches", "oily_skin", "dry_skin", "low_libido",
                          "vaginal_itch", "joint_pain", "abdominal_cramps", "gas", 
                          "hair_loss", "dry_mouth"]:
        return "yes_no"
    else:
        return "text"


def should_skip_question(question_key: str, gender: Optional[str]) -> bool:
    """
    Определить, нужно ли пропустить вопрос в зависимости от пола
    
    Вопросы для женщин (пропускаем для мужчин):
    - menstrual_cycle
    - vaginal_itch
    """
    if gender is None:
        return False  # Если пол еще не определен, показываем все вопросы
    
    if gender == "male" or gender == "мужской":
        # Мужчинам не показываем вопросы для женщин
        if question_key in ["menstrual_cycle", "vaginal_itch"]:
            return True
    
    return False


async def save_answer(session: AsyncSession, user_id: int, answer: Any, skip: bool = False, state_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Сохранить ответ на вопрос и перейти к следующему"""
    user = await session.get(User, user_id)
    if not user:
        raise ValueError("User not found")
    
    # Используем переданное состояние или создаём новое
    if state_data is None:
        state_data = user.state_data or {}
    
    current_index = state_data.get("current_question_index", 0)
    answers = state_data.get("answers", {})
    
    question_key = QUESTIONNAIRE_FLOW[current_index]
    
    # Нормализуем ответ для gender (мужской -> male, женский -> female)
    if question_key == "gender":
        if answer == "мужской":
            answer = "male"
        elif answer == "женский":
            answer = "female"
    
    # Опциональные вопросы можно пропустить
    optional_questions = ["chest_circumference", "waist_circumference", "hips_circumference"]
    if skip and question_key in optional_questions:
        answers[question_key] = None
    else:
        answers[question_key] = answer
    
    # Определяем пол для проверки следующих вопросов
    gender = answers.get("gender")
    
    current_index += 1
    
    # Пропускаем вопросы, которые не относятся к полу пользователя
    while current_index < len(QUESTIONNAIRE_FLOW):
        next_question_key = QUESTIONNAIRE_FLOW[current_index]
        if should_skip_question(next_question_key, gender):
            # Пропускаем вопрос для противоположного пола
            answers[next_question_key] = None
            current_index += 1
        else:
            break
    
    # Обновляем состояние для возврата
    state_data["current_question_index"] = current_index
    state_data["answers"] = answers
    
    # Сохраняем в БД для совместимости
    user.state_data = state_data
    await session.commit()
    
    # Проверяем, завершена ли анкета
    if current_index >= len(QUESTIONNAIRE_FLOW):
        # Завершаем анкетирование
        return await complete_onboarding(session, user_id, answers)
    
    next_question = get_current_question(current_index, answers)
    return {
        "completed": False,
        "next_question": next_question,
        "state_data": state_data
    }


async def complete_onboarding(session: AsyncSession, user_id: int, answers: Dict[str, Any]) -> Dict[str, Any]:
    """Завершить онбординг и рассчитать результаты"""
    user = await session.get(User, user_id)
    if not user:
        raise ValueError("User not found")
    
    # Создаём запись анкеты
    questionnaire = Questionnaire(
        user_id=user_id,
        type="primary",
        **{k: v for k, v in answers.items() if hasattr(Questionnaire, k)}
    )
    
    # Рассчитываем показатели
    height = answers.get("height")
    weight = answers.get("weight")
    
    if height and weight:
        bmi = calculate_bmi(height, weight)
        questionnaire.bmi = bmi
        
        # Рассчитываем баллы (по новой системе 0-5 и 0-10)
        health_score = calculate_health_score_new(answers)
        questionnaire.health_score = health_score
        
        general_score = calculate_general_score(answers)
        questionnaire.general_score = general_score
        
        # Рекомендации - профессиональный расчет калорий как у диетолога
        # Определяем пол из поля gender (теперь это первый вопрос)
        gender = answers.get("gender", "female")  # По умолчанию female для безопасности
        
        # Получаем данные для расчета
        age = None  # Возраст пока не в анкете, будет использовано среднее значение 30 лет
        average_steps = answers.get("average_steps")
        additional_activity = answers.get("additional_activity_frequency")
        
        recommended_calories = calculate_recommended_calories(
            bmi=bmi,
            weight=weight,
            height=height,
            gender=gender,
            age=age,
            average_steps=average_steps,
            additional_activity=additional_activity
        )
        questionnaire.recommended_calories = recommended_calories
        
        # Рассчитываем БЖУ с учетом цели (похудение/поддержание/набор)
        goal = "weight_loss" if bmi >= 25 else ("weight_gain" if bmi < 18.5 else "maintenance")
        bju = calculate_bju(recommended_calories, bmi=bmi, goal=goal)
        questionnaire.recommended_protein = bju["protein"]
        questionnaire.recommended_fats = bju["fats"]
        questionnaire.recommended_carbs = bju["carbs"]
        questionnaire.recommended_water = calculate_water_norm(weight) / 1000  # в литрах
        
        # Формируем результаты
        bmi_category = get_bmi_category(bmi)
        zones_text = get_attention_zones(answers, health_score)
        
        result_message = format_questionnaire_results_new(
            bmi=bmi,
            bmi_category=bmi_category,
            health_score=health_score,
            energy_level=answers.get("energy_level", 0),
            sleep_quality=answers.get("sleep_quality", 0),
            general_score=general_score,
            recommended_calories=recommended_calories,
            recommended_water=questionnaire.recommended_water,
            zones_text=zones_text
        )
    else:
        result_message = "✅ Анкетирование завершено, но для полного анализа не хватает данных о росте и весе."
    
    session.add(questionnaire)
    
    # Обновляем статус пользователя
    user.onboarding_completed = True
    user.onboarding_completed_at = datetime.now()
    user.current_state = "settings_notifications"  # Переходим к настройке уведомлений
    user.state_data = {}  # Очищаем состояние
    
    await session.commit()
    
    return {
        "completed": True,
        "message": result_message,
        "questionnaire_id": questionnaire.id,
        "needs_notification_setup": True  # Нужна настройка уведомлений
    }


def calculate_health_score_new(answers: Dict[str, Any]) -> float:
    """Рассчитать балл здоровья по новой системе (0-10)"""
    score = 10.0
    
    # Энергия (макс -2 балла) - шкала 1-5, среднее значение 3
    energy_level = answers.get("energy_level", 3)
    score -= (5 - energy_level) * 0.4
    
    # Сон (макс -2 балла) - шкала 1-5, среднее значение 3
    sleep_quality = answers.get("sleep_quality", 3)
    score -= (5 - sleep_quality) * 0.4
    
    # Стресс (макс -2 балла) - шкала 1-5, низкий стресс = высокое значение
    stress_level = answers.get("stress_level", 3)
    # Инвертируем: высокий стресс (1) = плохо, низкий стресс (5) = хорошо
    score -= (5 - stress_level) * 0.4
    
    # Симптомы (каждый -0.5 балла, макс -4 балла)
    symptoms = [
        "concentration", "irritability", "sleepiness", "headaches",
        "shortness_of_breath", "cold_hands_feet", "skin_itch", "abdominal_cramps"
    ]
    symptom_count = sum(1 for s in symptoms if answers.get(s))
    score -= symptom_count * 0.5
    
    return max(0.0, min(10.0, round(score, 1)))


def calculate_general_score(answers: Dict[str, Any]) -> float:
    """Рассчитать общий балл (0-100)"""
    score = 100.0
    
    # Энергия (1-5) -> до 20 баллов, среднее значение 3
    energy = answers.get("energy_level", 3)
    score -= (5 - energy) * 4
    
    # Сон (1-5) -> до 20 баллов, среднее значение 3
    sleep = answers.get("sleep_quality", 3)
    score -= (5 - sleep) * 4
    
    # Стресс (1-5) -> до 20 баллов, низкий стресс = высокое значение, среднее 3
    stress = answers.get("stress_level", 3)
    # Инвертируем: высокий стресс (1) = плохо, низкий стресс (5) = хорошо
    score -= (5 - stress) * 4
    
    # Симптомы -> до 40 баллов
    all_symptoms = [
        "concentration", "irritability", "sleepiness", "headaches",
        "shortness_of_breath", "cold_hands_feet", "skin_itch", "abdominal_cramps",
        "gas", "hair_loss", "dry_mouth", "joint_pain"
    ]
    symptom_count = sum(1 for s in all_symptoms if answers.get(s))
    score -= min(symptom_count * 3, 40)
    
    return max(0.0, min(100.0, round(score, 1)))


def get_attention_zones(answers: Dict[str, Any], health_score: float) -> str:
    """
    Получить зоны внимания на основе всех проблем, отмеченных в анкете
    Учитывает пол пользователя для исключения нерелевантных вопросов
    """
    zones = []
    gender = answers.get("gender", "female")  # Определяем пол пользователя
    is_female = (gender == "female" or gender == "женский")
    
    # Самочувствие (шкала 1-5)
    if answers.get("energy_level", 5) < 3:
        zones.append("Низкий уровень энергии")
    
    if answers.get("sleep_quality", 5) < 3:
        zones.append("Проблемы со сном")
    
    # Стресс: 1 = много стресса, 5 = мало стресса, порог = 3
    if answers.get("stress_level", 5) < 3:
        zones.append("Высокий уровень стресса")
    
    if answers.get("concentration") is True:
        zones.append("Снижение концентрации")
    
    if answers.get("irritability") is True:
        zones.append("Дневная раздражительность")
    
    if answers.get("sleepiness") is True:
        zones.append("Дневная сонливость")
    
    # ЖКТ проблемы
    has_gi_issues = False
    gi_issues_list = []
    
    if answers.get("abdominal_cramps") is True:
        gi_issues_list.append("боли или спазмы в животе")
        has_gi_issues = True
    
    if answers.get("gas") is True:
        gi_issues_list.append("повышенное газообразование")
        has_gi_issues = True
    
    if answers.get("bloating") is True:
        gi_issues_list.append("вздутие живота")
        has_gi_issues = True
    
    if answers.get("cramps") is True:
        gi_issues_list.append("спазмы")
        has_gi_issues = True
    
    # Объединяем проблемы ЖКТ в одну зону, если их несколько
    if has_gi_issues:
        if len(gi_issues_list) > 1:
            zones.append(f"Дискомфорт в ЖКТ ({', '.join(gi_issues_list)})")
        else:
            zones.append(f"Дискомфорт в ЖКТ ({gi_issues_list[0]})")
    
    # Проблемы со стулом
    stool_frequency = answers.get("stool_frequency", "")
    if stool_frequency in ["1 раз в 2–3 дня", "1 раз в 3–5 дней"]:
        zones.append("Редкий стул")
    elif stool_frequency == "2–3 раза в сутки":
        zones.append("Учащённый стул")
    
    stool_character = answers.get("stool_character", "")
    if stool_character in ["твёрдый", "жидкий", "иногда твёрдый, иногда жидкий", "чередуется"]:
        zones.append(f"Изменения характера стула ({stool_character})")
    
    # Головные боли и другие симптомы
    if answers.get("headaches") is True:
        zones.append("Головные боли")
    
    if answers.get("shortness_of_breath") is True:
        zones.append("Одышка или учащённое сердцебиение")
    
    if answers.get("joint_pain") is True:
        zones.append("Боли в суставах")
    
    # Гормональные / общий фон признаки
    if answers.get("cold_hands_feet") is True:
        zones.append("Холодные руки и ноги")
    
    if answers.get("skin_itch") is True:
        zones.append("Кожный зуд")
    
    if answers.get("dry_mouth") is True:
        zones.append("Сухость во рту")
    
    if answers.get("hair_loss") is True:
        zones.append("Выпадение волос")
    
    if answers.get("low_libido") is True:
        zones.append("Снижение либидо")
    
    if answers.get("blue_sclera") is True:
        zones.append("Голубоватый оттенок склер")
    
    # Проблемы с кожей
    if answers.get("oily_skin") is True:
        zones.append("Повышенная жирность кожи")
    
    if answers.get("dry_skin") is True:
        zones.append("Сухость кожи")
    
    # Женские проблемы (только для женщин)
    gender = answers.get("gender", "female")
    is_female = (gender == "female" or gender == "женский")
    
    if is_female:
        if answers.get("vaginal_itch") is True:
            zones.append("Вагинальный зуд")
        
        menstrual_cycle = answers.get("menstrual_cycle", "")
        if menstrual_cycle == "нерегулярный":
            zones.append("Нерегулярный менструальный цикл")
    
    # Аппетит и тяги
    appetite = answers.get("appetite", "")
    if appetite == "повышенный":
        zones.append("Повышенный аппетит")
    elif appetite == "пониженный":
        zones.append("Пониженный аппетит")
    
    if answers.get("sugar_craving") is True:
        zones.append("Тяга к сладкому")
    
    if answers.get("fat_craving") is True:
        zones.append("Тяга к жирному")
    
    # Всегда перечисляем все выявленные зоны внимания
    if zones:
        zones_text = "\n".join([f"• {zone}" for zone in zones])
        # Если зон больше 5, добавляем рекомендацию в конце
        if len(zones) > 5:
            zones_text += "\n\n💡 Имеет смысл обсудить состояние со специалистом"
        return zones_text
    
    return "Особых зон внимания не выявлено"
