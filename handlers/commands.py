"""Обработчики команд для aiogram"""
import asyncio
from pathlib import Path
from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile
from aiogram.filters import Command
from aiogram.exceptions import TelegramNetworkError
from sqlalchemy.ext.asyncio import AsyncSession
from database.db import AsyncSessionLocal
from services.onboarding import get_or_create_user, start_onboarding
from services.statistics import get_weekly_statistics, get_monthly_statistics, get_admin_statistics
from services.retest import start_retest
from services.admin import is_admin
from utils.templates import format_statistics
from utils.logger import setup_logger
from config import settings
from handlers.fsm_states import OnboardingStates, AddingFoodStates
from aiogram.fsm.context import FSMContext
from keyboards.main_menu import get_main_menu_keyboard

router = Router()
logger = setup_logger(__name__, settings.LOG_LEVEL, settings.DEBUG)

# Путь к фото приветствия (относительно корня проекта)
# Получаем корень проекта (на уровень выше handlers/)
PROJECT_ROOT = Path(__file__).parent.parent
WELCOME_PHOTO_PATH = PROJECT_ROOT / "asserts" / "welcome.jpg"


@router.message(Command("start"))
async def start_command(message: Message, state: FSMContext):
    """Обработчик команды /start"""
    user = message.from_user
    logger.info(f"User {user.id} (@{user.username}) started the bot")
    
    try:
        async with AsyncSessionLocal() as session:
            # Получаем или создаём пользователя
            db_user = await get_or_create_user(
                session=session,
                telegram_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name
            )
            
            # Если онбординг не пройден, начинаем его
            if not db_user.onboarding_completed:
                logger.debug(f"User {user.id} starting onboarding")
                result = await start_onboarding(session, db_user.id)
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Начать анкетирование", callback_data="start_questionnaire")]
                ])
                
                # Отправляем фото приветствия с текстом
                photo_sent = False
                try:
                    if WELCOME_PHOTO_PATH.exists():
                        photo = FSInputFile(WELCOME_PHOTO_PATH)
                        # Пытаемся отправить фото с retry для сетевых ошибок
                        max_retries = 2
                        for attempt in range(max_retries):
                            try:
                                await message.answer_photo(
                                    photo=photo,
                                    caption=result["message"],
                                    reply_markup=keyboard
                                )
                                logger.debug(f"Welcome photo sent to user {user.id}")
                                photo_sent = True
                                break
                            except TelegramNetworkError as network_error:
                                if attempt < max_retries - 1:
                                    wait_time = (attempt + 1) * 1  # 1, 2 секунды
                                    logger.warning(
                                        f"Network error sending photo to user {user.id} (attempt {attempt + 1}/{max_retries}): {network_error}. "
                                        f"Retrying in {wait_time}s..."
                                    )
                                    await asyncio.sleep(wait_time)
                                else:
                                    logger.warning(f"Failed to send welcome photo to user {user.id} after {max_retries} attempts: {network_error}")
                                    raise
                    else:
                        logger.warning(f"Welcome photo not found at {WELCOME_PHOTO_PATH}, sending text only")
                        await message.answer(result["message"], reply_markup=keyboard)
                        photo_sent = True
                except Exception as e:
                    # Логируем сетевые ошибки как WARNING, остальные как ERROR
                    if isinstance(e, TelegramNetworkError):
                        logger.warning(f"Network error sending welcome photo to user {user.id}: {e}")
                    else:
                        logger.error(f"Error sending welcome photo to user {user.id}: {e}", exc_info=True)
                
                # Если фото не удалось отправить, отправляем текстовое сообщение
                if not photo_sent:
                    try:
                        await message.answer(result["message"], reply_markup=keyboard)
                        logger.debug(f"Sent text welcome message to user {user.id} (photo failed)")
                    except Exception as fallback_error:
                        logger.error(f"Failed to send fallback text message to user {user.id}: {fallback_error}", exc_info=True)
            else:
                # Показываем постоянную клавиатуру меню
                menu_keyboard = get_main_menu_keyboard(user.id)
                
                # Отправляем фото приветствия для возвращающихся пользователей
                photo_sent = False
                welcome_back_text = (
                    "👋 Добро пожаловать обратно!\n\n"
                    "Используйте кнопки меню для доступа к функциям бота."
                )
                try:
                    if WELCOME_PHOTO_PATH.exists():
                        photo = FSInputFile(WELCOME_PHOTO_PATH)
                        # Пытаемся отправить фото с retry для сетевых ошибок
                        max_retries = 2
                        for attempt in range(max_retries):
                            try:
                                await message.answer_photo(
                                    photo=photo,
                                    caption=welcome_back_text,
                                    reply_markup=menu_keyboard
                                )
                                logger.debug(f"Welcome photo sent to returning user {user.id}")
                                photo_sent = True
                                break
                            except TelegramNetworkError as network_error:
                                if attempt < max_retries - 1:
                                    wait_time = (attempt + 1) * 1  # 1, 2 секунды
                                    logger.warning(
                                        f"Network error sending photo to returning user {user.id} (attempt {attempt + 1}/{max_retries}): {network_error}. "
                                        f"Retrying in {wait_time}s..."
                                    )
                                    await asyncio.sleep(wait_time)
                                else:
                                    logger.warning(f"Failed to send welcome back photo to user {user.id} after {max_retries} attempts: {network_error}")
                                    raise
                    else:
                        logger.warning(f"Welcome photo not found at {WELCOME_PHOTO_PATH}, sending text only")
                        await message.answer(welcome_back_text, reply_markup=menu_keyboard)
                        photo_sent = True
                except Exception as e:
                    # Логируем сетевые ошибки как WARNING, остальные как ERROR
                    if isinstance(e, TelegramNetworkError):
                        logger.warning(f"Network error sending welcome back photo to user {user.id}: {e}")
                    else:
                        logger.error(f"Error sending welcome back photo to user {user.id}: {e}", exc_info=True)
                
                # Если фото не удалось отправить, отправляем текстовое сообщение
                if not photo_sent:
                    try:
                        await message.answer(welcome_back_text, reply_markup=menu_keyboard)
                        logger.debug(f"Sent text welcome back message to user {user.id} (photo failed)")
                    except Exception as fallback_error:
                        logger.error(f"Failed to send fallback text message to user {user.id}: {fallback_error}", exc_info=True)
                logger.debug(f"User {user.id} already completed onboarding, showing menu keyboard")
    except Exception as e:
        logger.error(f"Error in start_command for user {user.id}: {e}", exc_info=True)
        await message.answer("Произошла ошибка. Попробуйте позже.")
        raise


@router.message(Command("statistics"))
async def statistics_command(message: Message):
    """Обработчик команды /statistics"""
    user_id = message.from_user.id
    async with AsyncSessionLocal() as session:
        from database.models import User
        from sqlalchemy import select
        
        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        db_user = result.scalar_one_or_none()
        
        if not db_user or not db_user.onboarding_completed:
            await message.answer("Сначала пройдите первичное анкетирование через /start")
            return
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Неделя", callback_data="stats_week")],
            [InlineKeyboardButton(text="📅 Месяц", callback_data="stats_month")],
        ])
        
        await message.answer("Выберите период для просмотра статистики:", reply_markup=keyboard)


@router.message(Command("report"))
async def report_command(message: Message):
    """Обработчик команды /report - показать дневной отчёт"""
    user_id = message.from_user.id
    async with AsyncSessionLocal() as session:
        from services.daily_scenarios import get_or_create_daily_record
        from database.models import Questionnaire, User
        from sqlalchemy import select
        from utils.calculations import calculate_bju
        from datetime import date
        
        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        db_user = result.scalar_one_or_none()
        
        if not db_user:
            await message.answer("Пользователь не найден")
            return
        
        daily_record = await get_or_create_daily_record(session, db_user.id)
        
        # Получаем рекомендации
        q_result = await session.execute(
            select(Questionnaire).where(
                Questionnaire.user_id == db_user.id
            ).order_by(Questionnaire.created_at.desc()).limit(1)
        )
        questionnaire = q_result.scalar_one_or_none()
        
        recommended_calories = 2000
        recommended_bju = calculate_bju(recommended_calories)
        
        if questionnaire:
            recommended_calories = questionnaire.recommended_calories or 2000
            recommended_bju = {
                "protein": questionnaire.recommended_protein or 150,
                "fats": questionnaire.recommended_fats or 55,
                "carbs": questionnaire.recommended_carbs or 225
            }
        
        from utils.templates import format_daily_report
        
        if daily_record.evening_wellbeing is None:
            await message.answer(
                "Вечерний отчёт ещё не заполнен. Используйте кнопки меню для заполнения вечернего отчёта."
            )
            return
        
        report_text = format_daily_report(
            wellbeing=daily_record.evening_wellbeing,
            energy=daily_record.evening_energy,
            calories=daily_record.total_calories,
            protein=daily_record.total_protein,
            fats=daily_record.total_fats,
            carbs=daily_record.total_carbs,
            fiber=daily_record.total_fiber,
            recommended_calories=recommended_calories,
            recommended_bju=recommended_bju
        )
        
        await message.answer(report_text)


@router.message(Command("contact_admin"))
async def contact_admin_command(message: Message):
    """Обработчик команды /contact_admin"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Общее обращение", callback_data="admin_request_contact")],
        [InlineKeyboardButton(text="😞 Жалоба", callback_data="admin_request_complaint")],
        [InlineKeyboardButton(text="🍳 Публикация рецепта", callback_data="admin_request_recipe")],
        [InlineKeyboardButton(text="📸 Публикация результатов", callback_data="admin_request_results")],
    ])
    
    await message.answer(
        "👨‍💼 СВЯЗЬ С АДМИНИСТРАЦИЕЙ\n\nВыберите тип обращения:",
        reply_markup=keyboard
    )


@router.message(Command("retest"))
async def retest_command(message: Message, state: FSMContext):
    """Обработчик команды /retest"""
    user_id = message.from_user.id
    async with AsyncSessionLocal() as session:
        from database.models import User
        from sqlalchemy import select
        
        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        db_user = result.scalar_one_or_none()
        
        if not db_user:
            await message.answer("Пользователь не найден")
            return
        
        result = await start_retest(session, db_user.id)
        
        if "error" in result:
            await message.answer(result["error"])
        else:
            await message.answer(result["message"])
            if "current_question" in result and result["current_question"]:
                await send_question(message, result["current_question"], state)


async def send_question(message: Message, question: dict, state: FSMContext = None):
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
        reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
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
        reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
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
        reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    elif question_type == "yes_no":
        keyboard = [
            [InlineKeyboardButton(text="Да", callback_data="answer_yes")],
            [InlineKeyboardButton(text="Нет", callback_data="answer_no")]
        ]
        if is_optional:
            keyboard.append([InlineKeyboardButton(text="⏭️ Пропустить", callback_data="answer_skip")])
        reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    elif question_type == "choice" and options:
        keyboard = []
        for option in options:
            keyboard.append([InlineKeyboardButton(text=option, callback_data=f"answer_{option}")])
        if is_optional:
            keyboard.append([InlineKeyboardButton(text="⏭️ Пропустить", callback_data="answer_skip")])
        reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    else:
        reply_markup = None
    
    await message.answer(text, reply_markup=reply_markup)
