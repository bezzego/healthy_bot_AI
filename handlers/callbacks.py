"""Обработчики callback'ов для aiogram"""
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession
from database.db import AsyncSessionLocal
from database.models import User
from sqlalchemy import select
from services.onboarding import start_onboarding, save_answer, get_current_question
from services.statistics import get_weekly_statistics, get_monthly_statistics, get_admin_statistics
from services.retest import start_retest, save_retest_answer
from services.nutrition import get_today_nutrition, search_food_in_database, FOOD_DATABASE
from services.admin import get_pending_requests, update_request_status, is_admin
from utils.templates import format_statistics
from utils.logger import setup_logger
from config import settings
from handlers.commands import send_question
from handlers.fsm_states import OnboardingStates, RetestStates, AddingFoodStates, WaterStates
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
import json

router = Router()
logger = setup_logger(__name__, settings.LOG_LEVEL, settings.DEBUG)


async def safe_edit_message(callback: CallbackQuery, text: str, reply_markup=None):
    """
    Безопасное редактирование сообщения с проверкой наличия текста.
    Если сообщение не содержит текста (например, фото), отправляет новое сообщение.
    """
    try:
        if callback.message and callback.message.text:
            # Сообщение содержит текст - можно редактировать
            await callback.message.edit_text(text, reply_markup=reply_markup)
        else:
            # Сообщение не содержит текста (фото/медиа) - отправляем новое сообщение
            await callback.message.answer(text, reply_markup=reply_markup)
            # Пытаемся удалить старое сообщение с кнопкой, если оно есть
            try:
                if callback.message:
                    await callback.message.delete()
            except Exception:
                pass  # Игнорируем ошибки при удалении
    except Exception as e:
        # Если редактирование не удалось, отправляем новое сообщение
        logger.debug(f"Failed to edit message, sending new one: {e}")
        try:
            await callback.message.answer(text, reply_markup=reply_markup)
        except Exception as send_error:
            logger.error(f"Failed to send message: {send_error}", exc_info=True)
            raise


@router.callback_query(F.data == "start_questionnaire")
async def handle_start_questionnaire(callback: CallbackQuery, state: FSMContext):
    """Начать анкетирование"""
    await callback.answer()
    user_id = callback.from_user.id
    logger.info(f"User {user_id} starting questionnaire")
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        db_user = result.scalar_one_or_none()
        
        if not db_user:
            await safe_edit_message(callback, "Пользователь не найден")
            return
        
        result = await start_onboarding(session, db_user.id)
        await state.set_state(OnboardingStates.in_progress)
        
        if "current_question" in result:
            await send_question_message(callback, result["current_question"], state)


@router.callback_query(F.data.startswith("answer_") & ~F.data.startswith("evening_"))
async def handle_answer(callback: CallbackQuery, state: FSMContext):
    """Обработка ответа на вопрос"""
    await callback.answer()
    
    data = callback.data
    user_id = callback.from_user.id
    answer_value = data.replace("answer_", "")
    skip = False
    
    # Преобразуем ответ
    if answer_value == "yes":
        answer = True
    elif answer_value == "no":
        answer = False
    elif answer_value == "skip":
        answer = None
        skip = True
    elif answer_value.isdigit():
        answer = int(answer_value)
    elif answer_value in ["мужской", "женский"]:
        # Сохраняем как есть для gender, преобразование будет в save_answer
        answer = answer_value
    else:
        answer = answer_value
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        db_user = result.scalar_one_or_none()
        
        if not db_user:
            await callback.message.edit_text("Пользователь не найден")
            return
        
        current_state = await state.get_state()
        
        # Получаем текущее состояние FSM
        state_data = await state.get_data()
        
        # Определяем тип тестирования
        if current_state == OnboardingStates.in_progress:
            result = await save_answer(session, db_user.id, answer, skip=skip, state_data=state_data)
        elif current_state == RetestStates.in_progress:
            result = await save_retest_answer(session, db_user.id, answer, state_data=state_data)
        
        elif current_state is None and answer_value.isdigit():
            # Старый формат (для совместимости)
            from services.daily_scenarios import save_morning_sleep_quality
            await save_morning_sleep_quality(session, db_user.id, int(answer_value))
            await callback.message.edit_text(f"✅ Спасибо! Качество сна: {answer_value}/10")
            return
        else:
            await callback.message.edit_text("Неожиданное состояние")
            return
        
        if result.get("completed"):
            await callback.message.edit_text(result["message"])
            
            # Если нужна настройка уведомлений после завершения анкеты
            if result.get("needs_notification_setup"):
                from handlers.fsm_states import NotificationSettingsStates
                from utils.templates import TIMEZONE_OPTIONS
                from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                
                await state.set_state(NotificationSettingsStates.waiting_for_timezone)
                
                # Создаем клавиатуру с часовыми поясами (по 2 в ряд)
                keyboard_rows = []
                for i in range(0, len(TIMEZONE_OPTIONS), 2):
                    row = []
                    for j in range(2):
                        if i + j < len(TIMEZONE_OPTIONS):
                            tz_name, tz_value = TIMEZONE_OPTIONS[i + j]
                            row.append(InlineKeyboardButton(text=tz_name, callback_data=f"timezone_{tz_value}"))
                    if row:
                        keyboard_rows.append(row)
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
                
                await callback.message.answer(
                    "🌍 Следующий шаг — настройка уведомлений.\n\n"
                    "Сначала выберите ваш часовой пояс — это важно для корректной работы уведомлений:",
                    reply_markup=keyboard
                )
            else:
                # Если настройка уведомлений не требуется, сразу показываем меню
                await state.clear()
                from keyboards.main_menu import get_main_menu_keyboard
                menu_keyboard = get_main_menu_keyboard(callback.from_user.id)
                await callback.message.answer(
                    "📱 Теперь вы можете использовать функции бота через меню:",
                    reply_markup=menu_keyboard
                )
        elif result.get("next_question"):
            # Обновляем состояние FSM
            if "state_data" in result:
                await state.update_data(**result["state_data"])
            await send_question_message(callback, result["next_question"], state)
        else:
            await callback.message.edit_text("Ошибка обработки ответа")


@router.callback_query(F.data == "statistics")
async def handle_statistics(callback: CallbackQuery):
    """Показать меню статистики"""
    await callback.answer()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Неделя", callback_data="stats_week")],
        [InlineKeyboardButton(text="📅 Месяц", callback_data="stats_month")]
    ])
    await callback.message.edit_text("Выберите период:", reply_markup=keyboard)


@router.callback_query(F.data == "stats_week")
async def handle_stats_week(callback: CallbackQuery):
    """Показать статистику за неделю"""
    await callback.answer()
    
    user_id = callback.from_user.id
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        db_user = result.scalar_one_or_none()
        
        if db_user:
            # Используем новый формат отчёта
            from services.reports import get_weekly_report, format_weekly_report_text
            try:
                stats = await get_weekly_report(session, db_user.id)
                text = format_weekly_report_text(stats)
            except:
                # Fallback на старый формат
                stats = await get_weekly_statistics(session, db_user.id)
                text = format_statistics(stats, "неделю")
            await callback.message.edit_text(text)


@router.callback_query(F.data == "stats_month")
async def handle_stats_month(callback: CallbackQuery):
    """Показать статистику за месяц"""
    await callback.answer()
    
    user_id = callback.from_user.id
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        db_user = result.scalar_one_or_none()
        
        if db_user:
            # Используем новый формат отчёта
            from services.reports import get_monthly_report, format_monthly_report_text
            try:
                stats = await get_monthly_report(session, db_user.id)
                text = format_monthly_report_text(stats)
            except:
                # Fallback на старый формат
                stats = await get_monthly_statistics(session, db_user.id)
                text = format_statistics(stats, "месяц")
            await callback.message.edit_text(text)


@router.callback_query(F.data == "nutrition_today")
async def handle_nutrition_today(callback: CallbackQuery):
    """Показать питание за сегодня"""
    await callback.answer()
    
    user_id = callback.from_user.id
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        db_user = result.scalar_one_or_none()
        
        if db_user:
            nutrition = await get_today_nutrition(session, db_user.id)
            text = f"🍽️ ПИТАНИЕ ЗА СЕГОДНЯ\n\n"
            text += f"🔥 Калории: {nutrition['total_calories']:.0f} ккал\n"
            text += f"🥩 Белки: {nutrition['total_protein']:.1f} г\n"
            text += f"🥑 Жиры: {nutrition['total_fats']:.1f} г\n"
            text += f"🍞 Углеводы: {nutrition['total_carbs']:.1f} г\n\n"
            
            if nutrition['records']:
                text += "📋 Записи:\n"
                for record in nutrition['records']:
                    text += f"• {record['food_name']}: {record['calories']:.0f} ккал\n"
            else:
                text += "Записей о питании пока нет.\n"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Добавить блюдо", callback_data="add_food")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_back")]
            ])
            await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(F.data == "add_food")
async def handle_add_food(callback: CallbackQuery, state: FSMContext):
    """Начать добавление еды"""
    await callback.answer()
    
    await state.set_state(AddingFoodStates.waiting_for_food)
    await callback.message.edit_text(
        "📝 Отправьте название блюда или продукта, и я найду его в базе.\n"
        "Или отправьте фото еды с подписью, указывающей калорийность (например: 'Овсянка, 250 ккал')"
    )


@router.callback_query(F.data == "admin_panel")
async def handle_admin_panel(callback: CallbackQuery):
    """Админ панель"""
    await callback.answer()
    
    user_id = callback.from_user.id
    if not is_admin(user_id):
        await callback.message.edit_text("Доступ запрещён")
        return
    
    async with AsyncSessionLocal() as session:
        requests = await get_pending_requests(session)
        text = f"⚙️ АДМИН-ПАНЕЛЬ\n\nОжидающих обращений: {len(requests)}\n\n"
        
        stats = await get_admin_statistics(session)
        text += "📊 СРЕДНИЕ ПОКАЗАТЕЛИ ЗА НЕДЕЛЮ:\n"
        text += f"😊 Самочувствие: {stats['avg_wellbeing']:.1f}/10\n"
        text += f"⚡ Энергия: {stats['avg_energy']:.1f}/10\n"
        text += f"😴 Сон: {stats['avg_sleep']:.1f}/10\n"
        text += f"🔥 Калории: {stats['avg_calories']:.0f} ккал\n"
        text += f"👥 Участников: {stats['total_users']}\n"
        
        keyboard_buttons = []
        if requests:
            keyboard_buttons.append([InlineKeyboardButton(
                text=f"📬 Обращения ({len(requests)})",
                callback_data="admin_requests_list"
            )])
        keyboard_buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu_back")])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(F.data == "retest")
async def handle_retest(callback: CallbackQuery, state: FSMContext):
    """Начать повторное тестирование"""
    await callback.answer()
    
    user_id = callback.from_user.id
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        db_user = result.scalar_one_or_none()
        
        if not db_user:
            await callback.message.edit_text("Пользователь не найден")
            return
        
        result = await start_retest(session, db_user.id)
        if "error" in result:
            await callback.message.edit_text(result["error"])
        else:
            await state.set_state(RetestStates.in_progress)
            await callback.message.edit_text(result["message"])
            if "current_question" in result and result["current_question"]:
                await send_question_message(callback, result["current_question"], state)




@router.callback_query(F.data.startswith("morning_sleep_") & ~F.data.startswith("morning_sleep_hours_"))
async def handle_morning_sleep(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора качества сна в утреннем чек-ине"""
    await callback.answer()
    
    user_id = callback.from_user.id
    logger.info(f"User {user_id} selected morning sleep: {callback.data}")
    
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == user_id)
            )
            db_user = result.scalar_one_or_none()
            
            if not db_user:
                await callback.message.edit_text("Пользователь не найден")
                return
            
            from utils.templates import MORNING_SLEEP_OPTIONS, get_morning_sleep_hours_question
            from services.daily_scenarios import save_morning_sleep_quality
            from handlers.fsm_states import MorningCheckinStates
            
            sleep_index = int(callback.data.split("_")[-1])
            sleep_quality = MORNING_SLEEP_OPTIONS[sleep_index] if sleep_index < len(MORNING_SLEEP_OPTIONS) else MORNING_SLEEP_OPTIONS[0]
            
            await save_morning_sleep_quality(session, db_user.id, sleep_quality)
            await state.set_state(MorningCheckinStates.waiting_for_sleep_hours)
            
            # Создаем клавиатуру для выбора количества часов сна (1-12)
            keyboard = []
            row = []
            for i in range(1, 13):  # 1-12 часов
                row.append(InlineKeyboardButton(text=str(i), callback_data=f"morning_sleep_hours_{i}"))
                if len(row) == 4:  # 4 кнопки в ряд
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)
            reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
            
            await callback.message.edit_text(
                get_morning_sleep_hours_question(),
                reply_markup=reply_markup
            )
            logger.info(f"User {user_id} sleep quality saved: {sleep_quality}, waiting for sleep hours")
    except Exception as e:
        logger.error(f"Error in handle_morning_sleep for user {user_id}: {e}", exc_info=True)
        await callback.message.edit_text("Произошла ошибка. Попробуйте снова.")


@router.callback_query(F.data.startswith("morning_sleep_hours_"))
async def handle_morning_sleep_hours(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора количества часов сна в утреннем чек-ине"""
    await callback.answer()
    
    user_id = callback.from_user.id
    logger.info(f"User {user_id} selected morning sleep hours: {callback.data}")
    
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == user_id)
            )
            db_user = result.scalar_one_or_none()
            
            if not db_user:
                await callback.message.edit_text("Пользователь не найден")
                return
            
            from services.daily_scenarios import save_morning_sleep_hours
            from handlers.fsm_states import MorningCheckinStates
            
            sleep_hours = int(callback.data.split("_")[-1])
            
            if sleep_hours < 1 or sleep_hours > 12:
                await callback.message.edit_text("Количество часов сна должно быть от 1 до 12. Попробуйте еще раз.")
                return
            
            await save_morning_sleep_hours(session, db_user.id, sleep_hours)
            await state.set_state(MorningCheckinStates.waiting_for_energy)
            
            keyboard = []
            row = []
            for i in range(1, 6):  # Шкала 1-5
                row.append(InlineKeyboardButton(text=str(i), callback_data=f"morning_energy_{i}"))
                if len(row) == 3:
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)
            
            reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
            
            await callback.message.edit_text(
                "⚡ Как вы себя чувствуете? Оцените энергию от 1 до 5, где 1 - нет сил, а 5 - много энергии",
                reply_markup=reply_markup
            )
            logger.info(f"User {user_id} sleep hours saved: {sleep_hours}, waiting for energy")
    except Exception as e:
        logger.error(f"Error in handle_morning_sleep_hours for user {user_id}: {e}", exc_info=True)
        await callback.message.edit_text("Произошла ошибка. Попробуйте снова.")


@router.callback_query(F.data.startswith("morning_energy_"))
async def handle_morning_energy(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора энергии в утреннем чек-ине"""
    await callback.answer()
    
    user_id = callback.from_user.id
    logger.info(f"User {user_id} selected morning energy: {callback.data}")
    
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == user_id)
            )
            db_user = result.scalar_one_or_none()
            
            if not db_user:
                await callback.message.edit_text("Пользователь не найден")
                return
            
            from services.daily_scenarios import save_morning_energy, get_morning_wish
            
            energy = int(callback.data.split("_")[-1])
            await save_morning_energy(session, db_user.id, energy)
            
            wish = get_morning_wish()
            await callback.message.edit_text(
                f"Зафиксировал ваши ответы. Не забудьте выпить стакан воды. {wish}"
            )
            await state.clear()
            logger.info(f"User {user_id} morning check-in completed, energy: {energy}")
    except Exception as e:
        logger.error(f"Error in handle_morning_energy for user {user_id}: {e}", exc_info=True)
        await callback.message.edit_text("Произошла ошибка. Попробуйте снова.")


@router.callback_query(F.data == "menu_back")
async def handle_menu_back(callback: CallbackQuery):
    """Вернуться в меню"""
    await callback.answer()
    
    user_id = callback.from_user.id
    from keyboards.main_menu import get_main_menu_keyboard
    
    menu_keyboard = get_main_menu_keyboard(user_id)
    await callback.message.edit_text("📱 Главное меню:")
    await callback.message.answer("📱 Главное меню:", reply_markup=menu_keyboard)


@router.callback_query(F.data.startswith("select_food_"))
async def handle_select_food(callback: CallbackQuery):
    """Выбрать продукт из базы"""
    await callback.answer()
    
    food_name = callback.data.replace("select_food_", "")
    user_id = callback.from_user.id
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        db_user = result.scalar_one_or_none()
        
        if not db_user:
            await callback.message.edit_text("Пользователь не найден")
            return
        
        if food_name in FOOD_DATABASE:
            food = FOOD_DATABASE[food_name]
            from services.nutrition import add_nutrition_record
            try:
                await add_nutrition_record(
                    session=session,
                    user_id=db_user.id,
                    food_name=food_name,
                    calories=food["calories"],
                    protein=food.get("protein", 0),
                    fats=food.get("fats", 0),
                    carbs=food.get("carbs", 0),
                    fiber=food.get("fiber", 0)
                )
                await callback.message.edit_text(f"✅ Добавлено: {food_name} - {food['calories']} ккал")
            except Exception as e:
                await callback.message.edit_text(f"Ошибка: {str(e)}")


@router.callback_query(F.data == "evening_report")
async def handle_evening_report_start(callback: CallbackQuery, state: FSMContext):
    """Начать вечерний отчёт (новый формат)"""
    await callback.answer()
    
    logger.info(f"User {callback.from_user.id} (@{callback.from_user.username}) starting evening report")
    
    try:
        from handlers.fsm_states import EveningCheckinStates
        from utils.templates import EVENING_MOOD_OPTIONS
        
        await state.set_state(EveningCheckinStates.waiting_for_mood)
        logger.debug(f"State set to EveningCheckinStates.waiting_for_mood for user {callback.from_user.id}")
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=mood, callback_data=f"evening_mood_{i}")]
            for i, mood in enumerate(EVENING_MOOD_OPTIONS)
        ])
        
        await callback.message.edit_text(
            "Добрый вечер 🤍\n"
            "Настало время подвести итоги дня!\n\n"
            "Какое состояние лучше всего описывает ваш день?",
            reply_markup=keyboard
        )
        logger.debug(f"Evening report mood question sent to user {callback.from_user.id}")
    except Exception as e:
        logger.error(f"Error in handle_evening_report_start for user {callback.from_user.id}: {e}", exc_info=True)
        await callback.message.edit_text("Произошла ошибка при запуске вечернего отчёта. Попробуйте позже.")


@router.callback_query(F.data.startswith("evening_mood_"))
async def handle_evening_mood(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора настроения в вечернем чек-ине"""
    await callback.answer()
    
    logger.debug(f"User {callback.from_user.id} selected mood")
    
    try:
        from handlers.fsm_states import EveningCheckinStates
        from utils.templates import EVENING_MOOD_OPTIONS
        
        mood_index = int(callback.data.split("_")[-1])
        mood = EVENING_MOOD_OPTIONS[mood_index] if mood_index < len(EVENING_MOOD_OPTIONS) else EVENING_MOOD_OPTIONS[0]
        
        await state.update_data(evening_mood=mood)
        await state.set_state(EveningCheckinStates.waiting_for_steps)
        
        logger.debug(f"User {callback.from_user.id} mood: {mood}, waiting for steps")
        
        await callback.message.edit_text("Сколько шагов вы прошли сегодня?\n\nВведите число:")
    except Exception as e:
        logger.error(f"Error in handle_evening_mood for user {callback.from_user.id}: {e}", exc_info=True)
        await callback.message.edit_text("Произошла ошибка. Попробуйте снова.")


@router.callback_query(F.data.startswith("evening_activity_") & ~F.data.startswith("evening_activity_duration_"))
async def handle_evening_activity_callback(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора типа активности в вечернем чек-ине"""
    await callback.answer()
    
    logger.debug(f"User {callback.from_user.id} selected activity: {callback.data}")
    
    try:
        from handlers.fsm_states import EveningCheckinStates
        from utils.templates import ACTIVITY_TYPES
        
        # Проверяем, выбрана ли активность "Нет активности"
        if callback.data == "evening_activity_0":
            # Нет активности - сразу переходим к стулу
            await state.update_data(activity_type="Нет активности", activity_duration=0, active_calories=0)
            await state.set_state(EveningCheckinStates.waiting_for_stool)
            
            from utils.templates import EVENING_STOOL_OPTIONS
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=stool, callback_data=f"evening_stool_{i}")]
                for i, stool in enumerate(EVENING_STOOL_OPTIONS)
            ])
            
            await callback.message.edit_text("Был ли сегодня стул?", reply_markup=keyboard)
            return
        
        # Получаем индекс активности
        activity_index = int(callback.data.split("_")[-1])
        if activity_index < len(ACTIVITY_TYPES):
            activity_name, _, activity_desc = ACTIVITY_TYPES[activity_index]
            await state.update_data(activity_type=activity_name)
            await state.set_state(EveningCheckinStates.waiting_for_activity_duration)
            
            await callback.message.edit_text(
                f"Выбрана активность: {activity_name}\n"
                f"{activity_desc}\n\n"
                "Сколько минут вы занимались? Введите число:"
            )
            logger.debug(f"User {callback.from_user.id} selected activity: {activity_name}, waiting for duration")
        else:
            await callback.message.edit_text("Ошибка: активность не найдена. Попробуйте снова.")
    except Exception as e:
        logger.error(f"Error in handle_evening_activity_callback for user {callback.from_user.id}: {e}", exc_info=True)
        await callback.message.edit_text("Произошла ошибка. Попробуйте снова.")


@router.callback_query(F.data.startswith("evening_stool_"))
async def handle_evening_stool_callback(callback: CallbackQuery, state: FSMContext):
    """Завершение вечернего чек-ина"""
    await callback.answer()
    
    logger.debug(f"User {callback.from_user.id} selected stool, completing evening report")
    
    from utils.templates import EVENING_STOOL_OPTIONS, EVENING_WISHES
    from services.daily_scenarios import save_evening_report
    from database.db import AsyncSessionLocal
    from database.models import User
    from sqlalchemy import select
    import random
    
    stool_index = int(callback.data.split("_")[-1])
    stool = EVENING_STOOL_OPTIONS[stool_index] if stool_index < len(EVENING_STOOL_OPTIONS) else EVENING_STOOL_OPTIONS[0]
    
    state_data = await state.get_data()
    mood = state_data.get("evening_mood")
    steps = state_data.get("steps", 0)
    activity_type = state_data.get("activity_type")
    activity_duration = state_data.get("activity_duration", 0)
    active_calories = state_data.get("active_calories", 0)
    
    user_id = callback.from_user.id
    
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == user_id)
            )
            db_user = result.scalar_one_or_none()
            
            if db_user:
                # Сохраняем вечерний отчет с новыми полями
                from services.daily_scenarios import get_or_create_daily_record
                from datetime import date
                daily_record = await get_or_create_daily_record(session, db_user.id, date.today())
                
                daily_record.evening_mood = mood
                daily_record.daily_steps = steps
                daily_record.evening_stool = stool
                
                # Новые поля для активности
                if activity_type:
                    daily_record.activity_type = activity_type
                    daily_record.active_calories = active_calories
                    daily_record.physical_activity = (activity_type != "Нет активности")
                else:
                    daily_record.physical_activity = False
                    daily_record.active_calories = 0
                
                await session.commit()
                
                # Формируем и отправляем вечернюю сводку
                await send_evening_summary(session, db_user.id, callback.message)
                
                await state.clear()
                logger.info(f"Evening report completed for user {user_id}: mood={mood}, steps={steps}, activity={activity_type}, active_calories={active_calories}, stool={stool}")
            else:
                logger.warning(f"User {user_id} not found when completing evening report")
                await callback.message.edit_text("Ошибка: пользователь не найден")
    except Exception as e:
        logger.error(f"Error completing evening report for user {user_id}: {e}", exc_info=True)
        await callback.message.edit_text("Произошла ошибка при сохранении данных. Попробуйте позже.")


@router.callback_query(F.data.startswith("evening_wellbeing_"))
async def handle_evening_wellbeing_old(callback: CallbackQuery, state: FSMContext):
    """Обработка старого формата wellbeing (для совместимости)"""
    await callback.answer()
    logger.debug(f"User {callback.from_user.id} using old wellbeing format")
    
    try:
        wellbeing = int(callback.data.split("_")[-1])
        await state.update_data(evening_wellbeing=wellbeing)
        
        keyboard = []
        row = []
        for i in range(0, 11):
            row.append(InlineKeyboardButton(text=str(i), callback_data=f"evening_energy_{i}"))
            if len(row) == 5:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
        
        await callback.message.edit_text("Оцените уровень энергии (0-10):", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error in handle_evening_wellbeing_old: {e}", exc_info=True)
        await callback.message.edit_text("Произошла ошибка. Попробуйте снова.")


@router.callback_query(F.data.startswith("evening_energy_"))
async def handle_evening_energy_old(callback: CallbackQuery, state: FSMContext):
    """Обработка старого формата energy (для совместимости)"""
    await callback.answer()
    logger.debug(f"User {callback.from_user.id} using old energy format")
    
    try:
        user_id = callback.from_user.id
        energy = int(callback.data.split("_")[-1])
        state_data = await state.get_data()
        wellbeing = state_data.get("evening_wellbeing", 5)
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == user_id)
            )
            db_user = result.scalar_one_or_none()
            
            if db_user:
                from services.daily_scenarios import save_evening_report
                report_result = await save_evening_report(
                    session, db_user.id, 
                    wellbeing=wellbeing,
                    energy=energy
                )
                await state.clear()
                await callback.message.edit_text(report_result["message"])
                logger.info(f"Old format evening report completed for user {user_id}")
            else:
                await callback.message.edit_text("Пользователь не найден")
    except Exception as e:
        logger.error(f"Error in handle_evening_energy_old for user {callback.from_user.id}: {e}", exc_info=True)
        await callback.message.edit_text("Произошла ошибка. Попробуйте снова.")


@router.callback_query(F.data == "food_confirm")
async def handle_food_confirm(callback: CallbackQuery, state: FSMContext):
    """Подтверждение и сохранение информации о еде"""
    await callback.answer()
    user_id = callback.from_user.id
    
    try:
        state_data = await state.get_data()
        food_name = state_data.get("food_name")
        total_calories = state_data.get("total_calories", 0)
        total_protein = state_data.get("total_protein", 0)
        total_fats = state_data.get("total_fats", 0)
        total_carbs = state_data.get("total_carbs", 0)
        photo_file_id = state_data.get("photo_file_id")
        
        if not food_name or total_calories == 0:
            await safe_edit_message(callback, "Ошибка: данные о еде не найдены. Попробуйте снова.")
            await state.clear()
            return
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == user_id)
            )
            db_user = result.scalar_one_or_none()
            
            if not db_user:
                await safe_edit_message(callback, "Пользователь не найден")
                await state.clear()
                return
            
            from services.nutrition import add_nutrition_record
            await add_nutrition_record(
                session=session,
                user_id=db_user.id,
                food_name=food_name,
                calories=total_calories,
                protein=total_protein,
                fats=total_fats,
                carbs=total_carbs,
                photo_file_id=photo_file_id
            )
            
            await safe_edit_message(
                callback,
                f"✅ Блюдо '{food_name}' зафиксировано!\n\n"
                f"📊 {total_calories:.0f} ккал (Б:{total_protein:.0f} Ж:{total_fats:.0f} У:{total_carbs:.0f})"
            )
            await state.clear()
            logger.info(
                f"User {user_id} confirmed food '{food_name}' "
                f"({total_calories:.0f} kcal) from photo"
            )
    except Exception as e:
        logger.error(f"Error confirming food for user {user_id}: {e}", exc_info=True)
        await safe_edit_message(callback, "Произошла ошибка при сохранении. Попробуйте снова.")
        await state.clear()


@router.callback_query(F.data == "food_cancel")
async def handle_food_cancel(callback: CallbackQuery, state: FSMContext):
    """Отмена добавления еды"""
    await callback.answer()
    await safe_edit_message(callback, "❌ Добавление еды отменено.")
    await state.clear()
    logger.info(f"User {callback.from_user.id} cancelled food addition")


@router.callback_query(F.data == "food_correct")
async def handle_food_correct(callback: CallbackQuery, state: FSMContext):
    """Начать редактирование информации о еде"""
    await callback.answer()
    user_id = callback.from_user.id
    
    await state.set_state(AddingFoodStates.waiting_for_food_correction)
    await safe_edit_message(
        callback,
        "📝 Пришли текст или голосовое сообщение: что добавить или изменить.\n\n"
        "Ты можешь скорректировать, если я ошиблась с граммовкой или неверно распознала блюдо.\n\n"
        "Можно перечислить несколько пунктов сразу:\n"
        "• «Здесь не 100 грамм, а 50»\n"
        "• «Это не йогурт, а сметана»\n"
        "• «Добавь еще сыр, 30 грамм»\n"
        "• «Убери помидоры, вместо них огурцы»\n\n"
        "Или просто одним предложением опиши изменения."
    )
    logger.info(f"User {user_id} requested food information correction")


async def send_question_message(callback: CallbackQuery, question: dict, state: FSMContext):
    """Отправить вопрос пользователю"""
    text = question["text"]
    question_type = question["type"]
    options = question.get("options")
    is_optional = question.get("optional", False)
    
    keyboard = []
    
    if question_type == "scale_0_10":
        row = []
        for i in range(0, 11):
            row.append(InlineKeyboardButton(text=str(i), callback_data=f"answer_{i}"))
            if len(row) == 5:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        if is_optional:
            keyboard.append([InlineKeyboardButton(text="⏭️ Пропустить", callback_data="answer_skip")])
    elif question_type == "scale_1_5":
        # Шкала 1-5
        row = []
        for i in range(1, 6):
            row.append(InlineKeyboardButton(text=str(i), callback_data=f"answer_{i}"))
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        if is_optional:
            keyboard.append([InlineKeyboardButton(text="⏭️ Пропустить", callback_data="answer_skip")])
    elif question_type == "scale_0_5":
        # Старая шкала 0-5 (для совместимости)
        row = []
        for i in range(0, 6):
            row.append(InlineKeyboardButton(text=str(i), callback_data=f"answer_{i}"))
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        if is_optional:
            keyboard.append([InlineKeyboardButton(text="⏭️ Пропустить", callback_data="answer_skip")])
    elif question_type == "yes_no":
        keyboard = [
            [InlineKeyboardButton(text="Да", callback_data="answer_yes")],
            [InlineKeyboardButton(text="Нет", callback_data="answer_no")]
        ]
        if is_optional:
            keyboard.append([InlineKeyboardButton(text="⏭️ Пропустить", callback_data="answer_skip")])
    elif question_type == "choice" and options:
        for option in options:
            keyboard.append([InlineKeyboardButton(text=option, callback_data=f"answer_{option}")])
        if is_optional:
            keyboard.append([InlineKeyboardButton(text="⏭️ Пропустить", callback_data="answer_skip")])
    
    reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard) if keyboard else None
    await safe_edit_message(callback, text, reply_markup)


async def send_evening_summary(session, user_id: int, message):
    """Отправить вечернюю сводку пользователю"""
    from services.daily_scenarios import get_or_create_daily_record
    from services.nutrition import get_today_nutrition
    from database.models import DailyRecord
    from sqlalchemy import select, func
    from datetime import date, timedelta
    
    today = date.today()
    daily_record = await get_or_create_daily_record(session, user_id, today)
    
    # Получаем питание за сегодня
    nutrition = await get_today_nutrition(session, user_id)
    
    # Получаем шаги за сегодня
    today_steps = daily_record.daily_steps or 0
    
    # Получаем средние шаги за неделю
    week_start = today - timedelta(days=6)
    week_records_result = await session.execute(
        select(DailyRecord).where(
            DailyRecord.user_id == user_id,
            func.date(DailyRecord.date) >= week_start,
            func.date(DailyRecord.date) <= today
        )
    )
    week_records = list(week_records_result.scalars().all())
    week_steps = [r.daily_steps for r in week_records if r.daily_steps]
    avg_week_steps = sum(week_steps) / len(week_steps) if week_steps else 0
    
    # Получаем средние шаги за прошлую неделю
    last_week_start = week_start - timedelta(days=7)
    last_week_end = week_start - timedelta(days=1)
    last_week_records_result = await session.execute(
        select(DailyRecord).where(
            DailyRecord.user_id == user_id,
            func.date(DailyRecord.date) >= last_week_start,
            func.date(DailyRecord.date) <= last_week_end
        )
    )
    last_week_records = list(last_week_records_result.scalars().all())
    last_week_steps = [r.daily_steps for r in last_week_records if r.daily_steps]
    avg_last_week_steps = sum(last_week_steps) / len(last_week_steps) if last_week_steps else 0
    
    # Сравнение шагов
    steps_diff = today_steps - avg_last_week_steps if avg_last_week_steps > 0 else 0
    steps_diff_percent = (steps_diff / avg_last_week_steps * 100) if avg_last_week_steps > 0 else 0
    
    # Активные калории
    active_calories = daily_record.active_calories or 0
    
    # Формируем сводку
    summary_text = "📊 СТАТИСТИКА ЗА ДЕНЬ\n\n"
    
    # Активность
    summary_text += f"🏃 АКТИВНОСТЬ:\n"
    summary_text += f"• Шаги: {today_steps:,}\n"
    if avg_week_steps > 0:
        summary_text += f"• Среднее за неделю: {avg_week_steps:.0f} шагов\n"
    if avg_last_week_steps > 0:
        if steps_diff > 0:
            summary_text += f"• На {steps_diff:.0f} шагов больше, чем на прошлой неделе (+{steps_diff_percent:.0f}%)\n"
        elif steps_diff < 0:
            summary_text += f"• На {abs(steps_diff):.0f} шагов меньше, чем на прошлой неделе ({steps_diff_percent:.0f}%)\n"
    
    if active_calories > 0:
        summary_text += f"• Активные калории: {active_calories:.0f} ккал\n"
        if daily_record.activity_type:
            summary_text += f"• Тип активности: {daily_record.activity_type}\n"
    summary_text += "\n"
    
    # КБЖУ
    total_calories = nutrition.get('total_calories', 0) or 0
    total_protein = nutrition.get('total_protein', 0) or 0
    total_fats = nutrition.get('total_fats', 0) or 0
    total_carbs = nutrition.get('total_carbs', 0) or 0
    
    summary_text += f"🍽️ КБЖУ:\n"
    summary_text += f"• Калории: {total_calories:.0f} ккал\n"
    summary_text += f"• Белки: {total_protein:.1f} г\n"
    summary_text += f"• Жиры: {total_fats:.1f} г\n"
    summary_text += f"• Углеводы: {total_carbs:.1f} г\n"
    summary_text += "\n"
    
    # Еда (список блюд)
    records = nutrition.get('records', [])
    if records:
        summary_text += f"🍴 ЕДА ЗА ДЕНЬ:\n"
        for i, record in enumerate(records, 1):
            food_name = record.get('food_name', 'Неизвестное блюдо')
            calories = record.get('calories', 0) or 0
            summary_text += f"{i}. {food_name} - {calories:.0f} ккал\n"
        summary_text += "\n"
    else:
        summary_text += f"🍴 ЕДА ЗА ДЕНЬ:\n"
        summary_text += f"• Записей о еде пока нет\n"
        summary_text += "\n"
    
    # Вода
    water_ml = daily_record.water_intake or 0
    water_liters = water_ml / 1000.0
    summary_text += f"💧 ВОДА: {water_liters:.1f} л ({water_ml:.0f} мл)\n"
    
    await message.answer(summary_text)


@router.callback_query(F.data.startswith("water_add_"))
async def handle_water_add(callback: CallbackQuery):
    """Обработка добавления воды по кнопке"""
    await callback.answer()
    
    user_id = callback.from_user.id
    logger.info(f"User {user_id} adding water: {callback.data}")
    
    try:
        from utils.templates import WATER_VOLUMES
        from services.daily_scenarios import get_or_create_daily_record
        from database.db import AsyncSessionLocal
        from database.models import User
        from sqlalchemy import select
        from datetime import date
        
        volume_index = int(callback.data.split("_")[-1])
        if volume_index < len(WATER_VOLUMES):
            _, volume_ml = WATER_VOLUMES[volume_index]
            
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(User).where(User.telegram_id == user_id)
                )
                db_user = result.scalar_one_or_none()
                
                if db_user:
                    daily_record = await get_or_create_daily_record(session, db_user.id, date.today())
                    daily_record.water_intake = (daily_record.water_intake or 0) + volume_ml
                    await session.commit()
                    
                    total_water_ml = daily_record.water_intake
                    total_water_liters = total_water_ml / 1000.0
                    
                    await callback.message.edit_text(
                        f"✅ Добавлено {volume_ml} мл воды\n\n"
                        f"💧 Всего за сегодня: {total_water_liters:.1f} л ({total_water_ml:.0f} мл)"
                    )
                    logger.info(f"User {user_id} added {volume_ml} ml water, total: {total_water_ml} ml")
                else:
                    await callback.message.edit_text("Пользователь не найден")
        else:
            await callback.message.edit_text("Ошибка: объем не найден")
    except Exception as e:
        logger.error(f"Error adding water for user {user_id}: {e}", exc_info=True)
        await callback.message.edit_text("Произошла ошибка. Попробуйте снова.")


@router.callback_query(F.data == "water_manual")
async def handle_water_manual(callback: CallbackQuery, state: FSMContext):
    """Обработка запроса на ввод воды вручную"""
    await callback.answer()
    
    await state.set_state(WaterStates.waiting_for_water_manual)
    await callback.message.edit_text(
        "💧 ВВОД ВОДЫ ВРУЧНУЮ\n\n"
        "Введите количество воды в миллилитрах (мл).\n"
        "Например: 250, 500, 750, 1000"
    )
