"""Сервис для недельных и месячных отчётов"""
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from datetime import datetime, date, timedelta
from database.models import DailyRecord, User


async def get_weekly_report(session: AsyncSession, user_id: int) -> Dict[str, Any]:
    """Получить недельный отчёт"""
    today = date.today()
    week_start = today - timedelta(days=6)  # Последние 7 дней
    
    result = await session.execute(
        select(DailyRecord).where(
            DailyRecord.user_id == user_id,
            func.date(DailyRecord.date) >= week_start,
            func.date(DailyRecord.date) <= today
        )
    )
    records = list(result.scalars().all())
    
    # Подсчёт статистики
    morning_count = sum(1 for r in records if r.morning_sleep_quality is not None)
    evening_count = sum(1 for r in records if r.evening_mood is not None)
    
    # Сон
    good_sleep = sum(1 for r in records if r.morning_sleep_quality == "Спала отлично, не просыпалась")
    moderate_sleep = sum(1 for r in records if r.morning_sleep_quality == "Проснулась 1 раз")
    bad_sleep = sum(1 for r in records if r.morning_sleep_quality in ["Просыпалась 2 раза и более", "Почти не спала / бессонница"])
    
    # Энергия
    good_energy = sum(1 for r in records if r.morning_energy and r.morning_energy >= 4)
    moderate_energy = sum(1 for r in records if r.morning_energy == 3)
    low_energy = sum(1 for r in records if r.morning_energy and r.morning_energy <= 2)
    
    # Настроение
    positive_mood = sum(1 for r in records if r.evening_mood in ["Хорошее настроение, удовлетворение", "Очень довольна собой, отличное настроение"])
    neutral_mood = sum(1 for r in records if r.evening_mood == "Спокойно, без сильных эмоций")
    negative_mood = sum(1 for r in records if r.evening_mood in ["Раздражение, напряжение", "Усталость, апатия"])
    
    # Шаги
    steps_records = [r.daily_steps for r in records if r.daily_steps]
    avg_steps = sum(steps_records) / len(steps_records) if steps_records else 0
    
    # Активность
    activity_days = sum(1 for r in records if r.physical_activity)
    
    # Стул
    normal_stool = sum(1 for r in records if r.evening_stool == "Да, нормальный")
    irregular_stool = sum(1 for r in records if r.evening_stool in ["Да, плотный", "Да, жидкий"])
    bad_stool = sum(1 for r in records if r.evening_stool in ["Да, жидкий более 2 раз", "Нет"])
    
    return {
        "morning_count": morning_count,
        "evening_count": evening_count,
        "good_sleep": good_sleep,
        "moderate_sleep": moderate_sleep,
        "bad_sleep": bad_sleep,
        "good_energy": good_energy,
        "moderate_energy": moderate_energy,
        "low_energy": low_energy,
        "positive_mood": positive_mood,
        "neutral_mood": neutral_mood,
        "negative_mood": negative_mood,
        "avg_steps": int(avg_steps),
        "activity_days": activity_days,
        "normal_stool": normal_stool,
        "irregular_stool": irregular_stool,
        "bad_stool": bad_stool,
        "total_days": 7
    }


async def get_monthly_report(session: AsyncSession, user_id: int, current_measurement: Optional[Any] = None, previous_measurement: Optional[Any] = None) -> Dict[str, Any]:
    """Получить месячный отчёт"""
    today = date.today()
    month_start = date(today.year, today.month, 1)
    
    result = await session.execute(
        select(DailyRecord).where(
            DailyRecord.user_id == user_id,
            func.date(DailyRecord.date) >= month_start,
            func.date(DailyRecord.date) <= today
        )
    )
    records = list(result.scalars().all())
    
    # Подсчёт статистики
    morning_count = sum(1 for r in records if r.morning_sleep_quality is not None)
    evening_count = sum(1 for r in records if r.evening_mood is not None)
    
    # Сон
    good_sleep = sum(1 for r in records if r.morning_sleep_quality == "Спала отлично, не просыпалась")
    bad_sleep = sum(1 for r in records if r.morning_sleep_quality in ["Просыпалась 2 раза и более", "Почти не спала / бессонница"])
    
    # Энергия
    energy_values = [r.morning_energy for r in records if r.morning_energy]
    avg_energy = sum(energy_values) / len(energy_values) if energy_values else 0
    
    # Сравнение с началом месяца
    first_week_energy = [r.morning_energy for r in records[:7] if r.morning_energy]
    last_week_energy = [r.morning_energy for r in records[-7:] if r.morning_energy]
    
    energy_trend = "→"
    if first_week_energy and last_week_energy:
        first_avg = sum(first_week_energy) / len(first_week_energy)
        last_avg = sum(last_week_energy) / len(last_week_energy)
        if last_avg > first_avg + 0.5:
            energy_trend = "↑"
        elif last_avg < first_avg - 0.5:
            energy_trend = "↓"
    
    # Настроение
    mood_counts = {}
    for r in records:
        if r.evening_mood:
            mood_counts[r.evening_mood] = mood_counts.get(r.evening_mood, 0) + 1
    
    most_common_mood = max(mood_counts.items(), key=lambda x: x[1])[0] if mood_counts else "нет данных"
    
    # Шаги
    steps_records = [r.daily_steps for r in records if r.daily_steps]
    avg_steps = sum(steps_records) / len(steps_records) if steps_records else 0
    
    # Активность
    activity_count = sum(1 for r in records if r.physical_activity)
    
    # Стул
    normal_stool_count = sum(1 for r in records if r.evening_stool == "Да, нормальный")
    total_stool_count = sum(1 for r in records if r.evening_stool and r.evening_stool != "Нет")
    stool_stability = "стабильная" if (total_stool_count > 0 and normal_stool_count > total_stool_count * 0.7) else "нестабильная"
    
    result = {
        "morning_count": morning_count,
        "evening_count": evening_count,
        "good_sleep": good_sleep,
        "bad_sleep": bad_sleep,
        "avg_energy": round(avg_energy, 1),
        "energy_trend": energy_trend,
        "most_common_mood": most_common_mood,
        "avg_steps": int(avg_steps),
        "activity_count": activity_count,
        "stool_stability": stool_stability,
        "normal_stool_count": normal_stool_count,
        "total_stool_count": total_stool_count,
        "total_days": len(records)
    }
    
    # Добавляем данные о замерах, если они есть
    if current_measurement:
        result["current_weight"] = current_measurement.weight
        result["current_waist"] = current_measurement.waist_circumference
        result["current_hips"] = current_measurement.hips_circumference
        result["current_chest"] = current_measurement.chest_circumference
        
        # Добавляем сравнение с предыдущим месяцем, если есть
        if previous_measurement:
            result["previous_weight"] = previous_measurement.weight
            result["previous_waist"] = previous_measurement.waist_circumference
            result["previous_hips"] = previous_measurement.hips_circumference
            result["previous_chest"] = previous_measurement.chest_circumference
            
            # Вычисляем изменения
            if current_measurement.weight and previous_measurement.weight:
                result["weight_change"] = round(current_measurement.weight - previous_measurement.weight, 1)
            if current_measurement.waist_circumference and previous_measurement.waist_circumference:
                result["waist_change"] = round(current_measurement.waist_circumference - previous_measurement.waist_circumference, 1)
            if current_measurement.hips_circumference and previous_measurement.hips_circumference:
                result["hips_change"] = round(current_measurement.hips_circumference - previous_measurement.hips_circumference, 1)
            if current_measurement.chest_circumference and previous_measurement.chest_circumference:
                result["chest_change"] = round(current_measurement.chest_circumference - previous_measurement.chest_circumference, 1)
    
    return result


def format_weekly_report_text(stats: Dict[str, Any]) -> str:
    """Форматировать текст недельного отчёта"""
    text = "📊 Недельный отчёт\n\n"
    
    text += f"Регулярность ваших заполнений\n"
    text += f"🔹 Утренний чек-ин: {stats['morning_count']} / 7 дней\n"
    text += f"🔹 Вечерний чек-ин: {stats['evening_count']} / 7 дней\n\n"
    
    text += "Как в среднем проходил сон:\n"
    text += f"🟢 Хорошо (без пробуждений): {stats['good_sleep']} дней\n"
    text += f"🟡 Умеренно (1 пробуждение): {stats['moderate_sleep']} дней\n"
    text += f"🔴 Плохо (2+ пробуждений / бессонница): {stats['bad_sleep']} дней\n\n"
    
    text += "Уровень энергии после пробуждения:\n"
    text += f"🟢 Хорошая энергия (4–5): {stats['good_energy']} дней\n"
    text += f"🟡 Средняя (3): {stats['moderate_energy']} дней\n"
    text += f"🔴 Низкая (1–2): {stats['low_energy']} дней\n\n"
    
    text += "Как вы чувствовали себя в конце дня:\n"
    text += f"🟢 Позитивное / удовлетворение: {stats['positive_mood']} дней\n"
    text += f"🟡 Нейтральное: {stats['neutral_mood']} дней\n"
    text += f"🔴 Напряжение / усталость / раздражение: {stats['negative_mood']} дней\n\n"
    
    text += f"Среднее количество шагов в день: {stats['avg_steps']}\n"
    text += f"Дней с дополнительной физической активностью: {stats['activity_days']} / 7\n\n"
    
    text += "Регулярность стула:\n"
    text += f"🟢 Регулярный, нормальный: {stats['normal_stool']} дней\n"
    text += f"🟡 Отклонения (плотный / редкий): {stats['irregular_stool']} дней\n"
    text += f"🔴 Нестабильный / отсутствовал: {stats['bad_stool']} дней\n\n"
    
    # Общий результат недели
    red_count = stats['bad_sleep'] + stats['low_energy'] + stats['negative_mood'] + stats['bad_stool']
    green_count = stats['good_sleep'] + stats['good_energy'] + stats['positive_mood'] + stats['normal_stool']
    
    if red_count > green_count:
        text += "Общий результат недели:\n"
        text += "На этой неделе тело часто давало сигналы усталости.\n"
        text += "Начнём с простого: режим сна, вода и ежедневное лёгкое движение 💚"
    elif green_count > red_count * 2:
        text += "Общий результат недели:\n"
        text += "Отличная неделя — состояние было стабильным.\n"
        text += "Продолжаем в том же ритме 🌿"
    else:
        text += "Общий результат недели:\n"
        text += "Состояние было нестабильным, но вы регулярно отмечались — это уже важный шаг 🤍"
    
    return text


def format_monthly_report_text(stats: Dict[str, Any]) -> str:
    """Форматировать текст месячного отчёта"""
    text = "📊 Готов ваш отчёт за месяц\n\n"
    text += "Посмотрим общую картину и динамику.\n\n"
    
    # Замеры и вес (если есть)
    if stats.get('current_weight'):
        text += "⚖️ ВЕС И ЗАМЕРЫ:\n"
        text += f"Вес: {stats['current_weight']:.1f} кг"
        
        if stats.get('weight_change') is not None:
            change = stats['weight_change']
            if change > 0:
                text += f" (+{change:.1f} кг)"
            elif change < 0:
                text += f" ({change:.1f} кг)"  # Отрицательное значение уже содержит минус
            else:
                text += " (без изменений)"
        text += "\n"
        
        if stats.get('current_waist'):
            text += f"Талия: {stats['current_waist']:.1f} см"
            if stats.get('waist_change') is not None:
                change = stats['waist_change']
                if change != 0:
                    text += f" ({change:+.1f} см)"
            text += "\n"
        
        if stats.get('current_hips'):
            text += f"Бёдра: {stats['current_hips']:.1f} см"
            if stats.get('hips_change') is not None:
                change = stats['hips_change']
                if change != 0:
                    text += f" ({change:+.1f} см)"
            text += "\n"
        
        if stats.get('current_chest'):
            text += f"Грудь: {stats['current_chest']:.1f} см"
            if stats.get('chest_change') is not None:
                change = stats['chest_change']
                if change != 0:
                    text += f" ({change:+.1f} см)"
            text += "\n"
        
        text += "\n"
    
    text += f"Дней с утренними чек-инами: {stats['morning_count']}\n"
    text += f"Дней с вечерними чек-инами: {stats['evening_count']}\n\n"
    
    text += f"Дней с хорошим сном: {stats['good_sleep']}\n"
    text += f"Дней с плохим сном: {stats['bad_sleep']}\n\n"
    
    text += f"Средний уровень энергии утром: {stats['avg_energy']} / 5\n"
    text += f"Тенденция: {stats['energy_trend']}\n\n"
    
    text += f"Чаще всего в опросах эмоционального состояния вы отмечали:\n{stats['most_common_mood']}\n\n"
    
    text += f"Среднее количество шагов в день: {stats['avg_steps']}\n"
    text += f"Дополнительная активность: {stats['activity_count']} раз за месяц\n\n"
    
    text += f"Регулярность стула: {stats['stool_stability']}\n"
    
    total_stool_days = stats.get('total_stool_count', stats.get('evening_count', 0))
    if total_stool_days > 0 and stats.get('normal_stool_count', 0) > total_stool_days * 0.7:
        text += "\n✅ Есть тенденция к улучшению"
    else:
        text += "\n📊 Без значительных изменений"
    
    return text
