"""Расчёты показателей здоровья"""
from typing import Dict, Any, Optional


def calculate_bmi(height: float, weight: float) -> float:
    """Рассчитать ИМТ (Индекс массы тела)"""
    if height <= 0 or weight <= 0:
        return 0.0
    height_m = height / 100
    return round(weight / (height_m ** 2), 1)


def get_bmi_category(bmi: float) -> str:
    """Определить категорию ИМТ"""
    if bmi < 18.5:
        return "недостаточная масса тела"
    elif bmi < 25:
        return "нормальная масса тела"
    elif bmi < 30:
        return "избыточная масса тела"
    elif bmi < 35:
        return "ожирение I степени"
    elif bmi < 40:
        return "ожирение II степени"
    else:
        return "ожирение III степени"


def calculate_health_score(questionnaire_data: Dict[str, Any]) -> float:
    """
    Рассчитать общий балл здоровья (0-100)
    Баллы распределяются по весам вопросов
    """
    score = 100.0
    
    # Энергия (макс -10 баллов)
    energy_level = questionnaire_data.get("energy_level", 5)
    score -= (10 - energy_level)
    
    # Сон (макс -10 баллов)
    sleep_quality = questionnaire_data.get("sleep_quality", 5)
    score -= (10 - sleep_quality)
    
    # Стресс (макс -10 баллов)
    stress_level = questionnaire_data.get("stress_level", 5)
    score -= stress_level
    
    # ЖКТ проблемы (макс -15 баллов)
    if questionnaire_data.get("bloating"):
        score -= 5
    if questionnaire_data.get("cramps"):
        score -= 5
    if questionnaire_data.get("gas"):
        score -= 5
    
    # Головные боли (макс -10 баллов)
    if questionnaire_data.get("headaches"):
        frequency = questionnaire_data.get("headache_frequency", "редко")
        if frequency == "ежедневно":
            score -= 10
        elif frequency == "несколько раз в неделю":
            score -= 7
        elif frequency == "раз в неделю":
            score -= 5
        elif frequency == "редко":
            score -= 2
    
    # Концентрация (макс -5 баллов)
    concentration = questionnaire_data.get("concentration", 5)
    score -= (10 - concentration) / 2
    
    # Раздражительность (макс -5 баллов)
    if questionnaire_data.get("irritability"):
        score -= 5
    
    # Сонливость (макс -5 баллов)
    if questionnaire_data.get("sleepiness"):
        score -= 5
    
    # Гормональные признаки (макс -15 баллов)
    if questionnaire_data.get("cold_hands_feet"):
        score -= 3
    if questionnaire_data.get("skin_itch"):
        score -= 3
    if questionnaire_data.get("dry_mouth"):
        score -= 3
    if questionnaire_data.get("hair_loss"):
        score -= 3
    if questionnaire_data.get("low_libido"):
        score -= 3
    
    # Аппетит (макс -5 баллов)
    appetite = questionnaire_data.get("appetite", "normal")
    if appetite == "increased":
        score -= 3
    elif appetite == "decreased":
        score -= 2
    
    # Тяги (макс -5 баллов)
    if questionnaire_data.get("sugar_craving"):
        score -= 3
    if questionnaire_data.get("fat_craving"):
        score -= 2
    
    return max(0.0, min(100.0, round(score, 1)))


def calculate_bmr_mifflin_st_jeor(weight: float, height: float, age: int, is_male: bool) -> float:
    """
    Рассчитать BMR (базовый метаболизм) по формуле Mifflin-St Jeor
    Это наиболее точная формула, используемая профессиональными диетологами
    """
    if is_male:
        # Для мужчин: BMR = (10 × вес в кг) + (6.25 × рост в см) − (5 × возраст) + 5
        bmr = (10 * weight) + (6.25 * height) - (5 * age) + 5
    else:
        # Для женщин: BMR = (10 × вес в кг) + (6.25 × рост в см) − (5 × возраст) − 161
        bmr = (10 * weight) + (6.25 * height) - (5 * age) - 161
    
    return max(800, bmr)  # Минимальный BMR для безопасности


def get_activity_factor(average_steps: Optional[int] = None, additional_activity: Optional[str] = None) -> float:
    """
    Определить коэффициент активности для расчета TDEE на основе шагов и дополнительной активности
    
    Уровни активности (по стандартам диетологии):
    - Сидячий (1.2): < 5000 шагов, нет дополнительной активности
    - Легкая (1.375): 5000-7499 шагов или 1-2 тренировки в неделю
    - Умеренная (1.55): 7500-9999 шагов или 3-4 тренировки в неделю
    - Высокая (1.725): ≥ 10000 шагов и 3+ тренировки в неделю
    - Очень высокая (1.9): ≥ 12000 шагов и ежедневные тренировки
    """
    # Если нет данных об активности, используем минимальный коэффициент
    if average_steps is None and additional_activity is None:
        return 1.2  # Сидячий образ жизни (по умолчанию)
    
    steps = average_steps or 0
    activity = additional_activity or "нет"
    
    # Определяем уровень активности по комбинации шагов и тренировок
    if steps >= 12000 and activity == "3 и более раз в неделю":
        # Очень высокая активность: очень много шагов + частые тренировки
        return 1.9
    elif steps >= 10000 and activity == "3 и более раз в неделю":
        # Высокая активность: много шагов + регулярные тренировки
        return 1.725
    elif steps >= 10000 or activity == "3 и более раз в неделю":
        # Умеренно-высокая активность: много шагов ИЛИ регулярные тренировки
        return 1.55
    elif steps >= 7500 or activity == "1-2 раза в неделю":
        # Умеренная активность
        return 1.375
    elif steps >= 5000:
        # Легкая активность
        return 1.2
    else:
        # Сидячий образ жизни (менее 5000 шагов, нет тренировок)
        return 1.2


def calculate_tdee(bmr: float, activity_factor: float) -> float:
    """
    Рассчитать TDEE (общий дневной расход энергии)
    TDEE = BMR × коэффициент активности
    """
    return bmr * activity_factor


def get_calorie_goal_adjustment(bmi: float, weight: float) -> float:
    """
    Определить коррекцию калорийности в зависимости от цели
    На основе BMI определяем, нужен ли дефицит или профицит калорий
    """
    if bmi >= 30:
        # Ожирение - умеренный дефицит для безопасного похудения (500 ккал)
        return -500
    elif bmi >= 25:
        # Избыточный вес - небольшой дефицит (300-400 ккал)
        return -350
    elif bmi < 18.5:
        # Недостаточный вес - небольшой профицит для набора веса
        return 300
    else:
        # Нормальный вес - поддержание (без коррекции)
        return 0


def calculate_recommended_calories(
    bmi: float, 
    weight: float, 
    height: Optional[float] = None,
    gender: Optional[str] = None,
    age: Optional[int] = None,
    average_steps: Optional[int] = None,
    additional_activity: Optional[str] = None
) -> int:
    """
    Профессиональный расчет рекомендуемой калорийности как у диетолога
    
    Использует формулу Mifflin-St Jeor для BMR и учитывает:
    - Пол (определяется из gender или menstrual_cycle)
    - Возраст (если не указан, используется 30 лет)
    - Уровень физической активности
    - Цель (похудение/поддержание/набор) на основе BMI
    
    Если height не указан, используется упрощенный расчет на основе веса и BMI
    """
    # Если рост не указан, вычисляем его из BMI и веса для расчета BMR
    if height is None or height <= 0:
        # Вычисляем рост из BMI: height = sqrt(weight / bmi) * 100
        if bmi > 0:
            height_estimated = (weight / bmi) ** 0.5 * 100
            height = max(140, min(220, height_estimated))  # Ограничения: 140-220 см
        else:
            height = 170  # Средний рост по умолчанию
    
    # Определяем пол: если gender = "male" или из menstrual_cycle = "я мужчина"
    if gender == "male" or gender == "мужской":
        is_male = True
    elif gender == "female" or gender == "женский":
        is_male = False
    else:
        # По умолчанию считаем женским (для безопасности расчета)
        is_male = False
    
    # Используем возраст, если указан, иначе средний возраст 30 лет
    age_value = age if age and 18 <= age <= 100 else 30
    
    # Рассчитываем BMR по формуле Mifflin-St Jeor
    bmr = calculate_bmr_mifflin_st_jeor(weight, height, age_value, is_male)
    
    # Определяем коэффициент активности
    activity_factor = get_activity_factor(average_steps, additional_activity)
    
    # Рассчитываем TDEE (общий расход энергии)
    tdee = calculate_tdee(bmr, activity_factor)
    
    # Определяем коррекцию для цели
    goal_adjustment = get_calorie_goal_adjustment(bmi, weight)
    
    # Финальная калорийность
    recommended_calories = tdee + goal_adjustment
    
    # Ограничения для безопасности
    min_calories = 1200 if not is_male else 1500  # Минимум для женщин и мужчин
    max_calories = 3000  # Максимум
    
    return int(max(min_calories, min(max_calories, round(recommended_calories))))


def calculate_bju(calories: int, bmi: Optional[float] = None, goal: Optional[str] = None) -> Dict[str, float]:
    """
    Профессиональный расчет БЖУ (белки, жиры, углеводы) с учетом цели
    
    Распределение БЖУ зависит от цели:
    - Похудение: больше белка (30-35%), умеренные жиры (25-30%), меньше углеводов (35-40%)
    - Поддержание: сбалансированное (25-30% белки, 25-30% жиры, 40-50% углеводы)
    - Набор веса: больше углеводов (45-50%), белки (25-30%), жиры (25-30%)
    """
    # Определяем цель на основе BMI, если не указана явно
    if goal is None:
        if bmi and bmi >= 25:
            goal = "weight_loss"  # Похудение
        elif bmi and bmi < 18.5:
            goal = "weight_gain"  # Набор веса
        else:
            goal = "maintenance"  # Поддержание
    
    if goal == "weight_loss":
        # Похудение: высокий белок, умеренные жиры и углеводы
        protein_percent = 0.32  # 32%
        fats_percent = 0.28     # 28%
        carbs_percent = 0.40    # 40%
    elif goal == "weight_gain":
        # Набор веса: больше углеводов для энергии
        protein_percent = 0.25  # 25%
        fats_percent = 0.28     # 28%
        carbs_percent = 0.47    # 47%
    else:  # maintenance
        # Поддержание: сбалансированное распределение
        protein_percent = 0.28  # 28%
        fats_percent = 0.30     # 30%
        carbs_percent = 0.42    # 42%
    
    # Рассчитываем калории из каждого макронутриента
    protein_calories = calories * protein_percent
    fats_calories = calories * fats_percent
    carbs_calories = calories * carbs_percent
    
    # Калорийность: белки 4 ккал/г, жиры 9 ккал/г, углеводы 4 ккал/г
    protein = round(protein_calories / 4, 1)
    fats = round(fats_calories / 9, 1)
    carbs = round(carbs_calories / 4, 1)
    
    return {
        "protein": protein,
        "fats": fats,
        "carbs": carbs
    }


def calculate_water_norm(weight: float) -> float:
    """Рассчитать норму воды: 30 мл × вес (кг)"""
    return round(weight * 30, 0)


def get_recommendations(bmi: float, health_score: float, questionnaire_data: Dict[str, Any]) -> list:
    """Получить текстовые рекомендации на основе данных анкеты"""
    recommendations = []
    
    if bmi > 25:
        recommendations.append("💡 Рекомендуется снизить калорийность рациона до 1700 ккал в день")
        recommendations.append("💡 Увеличьте физическую активность: минимум 8000 шагов в день")
    
    if health_score < 60:
        recommendations.append("⚠️ Ваш общий балл здоровья ниже нормы. Рекомендуем обратиться к специалисту")
    
    sleep_quality = questionnaire_data.get("sleep_quality", 5)
    if sleep_quality < 6:
        recommendations.append("😴 Улучшите качество сна: ложитесь спать до 23:00, избегайте экранов за час до сна")
    
    stress_level = questionnaire_data.get("stress_level", 5)
    if stress_level > 7:
        recommendations.append("🧘 Высокий уровень стресса. Рекомендуем техники релаксации и дыхательные упражнения")
    
    if questionnaire_data.get("bloating") or questionnaire_data.get("cramps"):
        recommendations.append("🌿 При проблемах с ЖКТ исключите продукты, вызывающие дискомфорт, ведите пищевой дневник")
    
    if questionnaire_data.get("headaches"):
        recommendations.append("💊 При частых головных болях обратитесь к врачу и отслеживайте триггеры")
    
    if questionnaire_data.get("cold_hands_feet"):
        recommendations.append("🔥 При зябкости конечностей проверьте уровень железа и функцию щитовидной железы")
    
    if not questionnaire_data.get("physical_activity"):
        recommendations.append("🏃 Регулярная физическая активность улучшит общее самочувствие")
    
    if not recommendations:
        recommendations.append("✅ Ваши показатели в норме! Продолжайте вести здоровый образ жизни")
    
    return recommendations
