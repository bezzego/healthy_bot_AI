"""Обработчики настройки уведомлений"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import StateFilter
from sqlalchemy.ext.asyncio import AsyncSession
from database.db import AsyncSessionLocal
from database.models import User
from sqlalchemy import select
from utils.logger import setup_logger
from config import settings
from handlers.fsm_states import NotificationSettingsStates
from aiogram.fsm.context import FSMContext
from utils.templates import MORNING_TIME_OPTIONS, EVENING_TIME_OPTIONS
from keyboards.main_menu import get_main_menu_keyboard
import pytz

router = Router()
logger = setup_logger(__name__, settings.LOG_LEVEL, settings.DEBUG)


@router.message(StateFilter(NotificationSettingsStates.waiting_for_timezone))
async def handle_timezone_setup(message: Message, state: FSMContext):
    """Обработка выбора часового пояса - показываем список популярных часовых поясов"""
    from utils.templates import TIMEZONE_OPTIONS
    
    # Создаем клавиатуру с часовыми поясами (по 2 в ряд для компактности)
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
    
    await message.answer(
        "🌍 Выберите ваш часовой пояс:\n\n"
        "Это важно для корректной работы уведомлений в ваше местное время.",
        reply_markup=keyboard
    )


@router.callback_query(F.data.startswith("timezone_"))
async def handle_timezone_selection(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора часового пояса пользователем"""
    await callback.answer()
    timezone_value = callback.data.replace("timezone_", "")
    
    # Находим название часового пояса для отображения
    from utils.templates import TIMEZONE_OPTIONS
    timezone_name = "Москва"
    for name, value in TIMEZONE_OPTIONS:
        if value == timezone_value:
            timezone_name = name.split(" (")[0]  # Убираем скобки с аббревиатурой
            break
    
    await state.update_data(timezone=timezone_value)
    
    # Показываем выбранный часовой пояс и переходим к выбору утреннего времени
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=time, callback_data=f"morning_time_{time}")] 
        for time in MORNING_TIME_OPTIONS
    ])
    
    await callback.message.edit_text(
        f"✅ Выбран часовой пояс: {timezone_name}\n\n"
        "Во сколько присылать утренние напоминания?",
        reply_markup=keyboard
    )
    await state.set_state(NotificationSettingsStates.waiting_for_morning_time)


@router.callback_query(F.data.startswith("morning_time_"))
async def handle_morning_time(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора времени утренних уведомлений"""
    await callback.answer()
    morning_time = callback.data.replace("morning_time_", "")
    
    await state.update_data(morning_time=morning_time)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=time, callback_data=f"evening_time_{time}")] 
        for time in EVENING_TIME_OPTIONS
    ])
    
    await callback.message.edit_text(
        "Во сколько присылать вечерние напоминания?",
        reply_markup=keyboard
    )
    await state.set_state(NotificationSettingsStates.waiting_for_evening_time)


@router.callback_query(F.data.startswith("evening_time_"))
async def handle_evening_time(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора времени вечерних уведомлений"""
    await callback.answer()
    evening_time = callback.data.replace("evening_time_", "")
    
    from config import settings
    state_data = await state.get_data()
    morning_time = state_data.get("morning_time", "08:00")
    timezone = state_data.get("timezone", settings.DEFAULT_TIMEZONE)
    
    user_id = callback.from_user.id
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if user:
            user.timezone = timezone
            user.morning_notification_time = morning_time
            user.evening_notification_time = evening_time
            user.current_state = "main_menu"
            await session.commit()
    
    # Получаем название часового пояса для отображения
    from utils.templates import TIMEZONE_OPTIONS
    timezone_name = "Москва"
    for name, value in TIMEZONE_OPTIONS:
        if value == timezone:
            timezone_name = name.split(" (")[0]
            break
    
    await callback.message.edit_text(
        f"✅ Настройки уведомлений сохранены!\n\n"
        f"Часовой пояс: {timezone_name}\n"
        f"Утренние напоминания: {morning_time}\n"
        f"Вечерние напоминания: {evening_time}\n\n"
        f"Бот будет отправлять вам напоминания в указанное время по вашему местному времени."
    )
    await state.clear()
    
    # Показываем постоянную клавиатуру меню после завершения настройки
    menu_keyboard = get_main_menu_keyboard(user_id)
    await callback.message.answer(
        "📱 Теперь вы можете использовать функции бота через меню:",
        reply_markup=menu_keyboard
    )
