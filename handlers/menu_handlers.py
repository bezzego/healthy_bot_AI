"""Обработчики текстовых сообщений для постоянной клавиатуры меню"""
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import StateFilter
from sqlalchemy.ext.asyncio import AsyncSession
from database.db import AsyncSessionLocal
from database.models import User
from sqlalchemy import select
from utils.logger import setup_logger
from config import settings
from services.admin import is_admin
from keyboards.main_menu import get_main_menu_keyboard
from keyboards.admin_menu import get_admin_menu_keyboard
from handlers.fsm_states import AddingFoodStates

router = Router()
logger = setup_logger(__name__, settings.LOG_LEVEL, settings.DEBUG)


@router.message(F.text == "📊 Статистика")
async def handle_statistics_button(message: Message):
    """Обработка кнопки 'Статистика'"""
    logger.info(f"User {message.from_user.id} clicked Statistics button")
    
    user_id = message.from_user.id
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        db_user = result.scalar_one_or_none()
        
        if not db_user or not db_user.onboarding_completed:
            await message.answer("Сначала пройдите первичное анкетирование через /start")
            return
        
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Неделя", callback_data="stats_week")],
            [InlineKeyboardButton(text="📅 Месяц", callback_data="stats_month")],
        ])
        
        await message.answer("Выберите период для просмотра статистики:", reply_markup=keyboard)


@router.message(F.text == "🍽️ Питание сегодня")
async def handle_nutrition_button(message: Message):
    """Обработка кнопки 'Питание сегодня'"""
    logger.info(f"User {message.from_user.id} clicked Nutrition button")
    
    user_id = message.from_user.id
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        db_user = result.scalar_one_or_none()
        
        if not db_user:
            await message.answer("Пользователь не найден")
            return
        
        from services.nutrition import get_today_nutrition
        nutrition_data = await get_today_nutrition(session, db_user.id)
        
        if nutrition_data["total_calories"] == 0:
            await message.answer(
                "🍽️ ПИТАНИЕ ЗА СЕГОДНЯ\n\n"
                "Пока нет записей о питании.\n"
                "Используйте кнопку '📸 Добавить еду' для добавления блюд."
            )
        else:
            text = f"🍽️ ПИТАНИЕ ЗА СЕГОДНЯ\n\n"
            text += f"🔥 Калории: {nutrition_data['total_calories']:.0f} ккал\n"
            text += f"🥩 Белки: {nutrition_data['total_protein']:.1f} г\n"
            text += f"🥑 Жиры: {nutrition_data['total_fats']:.1f} г\n"
            text += f"🍞 Углеводы: {nutrition_data['total_carbs']:.1f} г\n\n"
            
            if nutrition_data.get('records'):
                text += "📋 Записи:\n"
                for record in nutrition_data['records'][:10]:  # Показываем максимум 10 записей
                    text += f"• {record['food_name']}: {record['calories']} ккал\n"
                if len(nutrition_data['records']) > 10:
                    text += f"... и ещё {len(nutrition_data['records']) - 10} записей\n"
            
            await message.answer(text)


@router.message(F.text == "📸 Добавить еду")
async def handle_add_food_button(message: Message, state):
    """Обработка кнопки 'Добавить еду'"""
    logger.info(f"User {message.from_user.id} clicked Add Food button")
    
    user_id = message.from_user.id
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        db_user = result.scalar_one_or_none()
        
        if not db_user:
            await message.answer("Пользователь не найден")
            return
        
        await state.set_state(AddingFoodStates.waiting_for_food)
        await message.answer(
            "🍽️ Добавление еды\n\n"
            "Отправьте название блюда или продукта.\n"
            "Можно также отправить фото еды."
        )


@router.message(F.text == "🔄 Повторное тестирование")
async def handle_retest_button(message: Message, state):
    """Обработка кнопки 'Повторное тестирование'"""
    logger.info(f"User {message.from_user.id} clicked Retest button")
    
    user_id = message.from_user.id
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        db_user = result.scalar_one_or_none()
        
        if not db_user:
            await message.answer("Пользователь не найден")
            return
        
        from services.retest import start_retest
        from handlers.commands import send_question
        
        retest_result = await start_retest(session, db_user.id)
        
        if "error" in retest_result:
            await message.answer(retest_result["error"])
        else:
            await message.answer(retest_result["message"])
            if "current_question" in retest_result and retest_result["current_question"]:
                await send_question(message, retest_result["current_question"], state)


@router.message(F.text == "👨‍💼 Связаться с админом")
async def handle_contact_admin_button(message: Message):
    """Обработка кнопки 'Связаться с админом' - просто ссылка на аккаунт"""
    logger.info(f"User {message.from_user.id} clicked Contact Admin button")
    
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👨‍💼 Связаться с админом", url="https://t.me/doc_kazachkova_team")],
    ])
    
    await message.answer(
        "👨‍💼 Свяжитесь с администратором:\n\n"
        "https://t.me/doc_kazachkova_team",
        reply_markup=keyboard
    )


@router.message(F.text == "⚙️ Админ-панель")
async def handle_admin_panel_button(message: Message):
    """Обработка кнопки 'Админ-панель' (только для администраторов)"""
    user_id = message.from_user.id
    logger.info(f"User {user_id} clicked Admin Panel button")
    
    if not is_admin(user_id):
        await message.answer("❌ У вас нет доступа к админ-панели.")
        return
    
    admin_keyboard = get_admin_menu_keyboard()
    await message.answer(
        "⚙️ АДМИН-ПАНЕЛЬ\n\nВыберите действие:",
        reply_markup=admin_keyboard
    )


@router.message(F.text == "📊 Статистика пользователей")
async def handle_admin_statistics_button(message: Message):
    """Обработка кнопки 'Статистика пользователей' в админ-панели"""
    user_id = message.from_user.id
    logger.info(f"User {user_id} clicked Admin Statistics button")
    
    if not is_admin(user_id):
        await message.answer("❌ У вас нет доступа.")
        return
    
    async with AsyncSessionLocal() as session:
        from services.statistics import get_admin_statistics
        stats = await get_admin_statistics(session)
        from utils.templates import format_statistics
        
        text = format_statistics(stats)
        await message.answer(text)


@router.message(F.text == "📝 Заявки")
async def handle_admin_requests_button(message: Message):
    """Обработка кнопки 'Заявки' в админ-панели"""
    user_id = message.from_user.id
    logger.info(f"User {user_id} clicked Admin Requests button")
    
    if not is_admin(user_id):
        logger.warning(f"Non-admin user {user_id} attempted to access admin requests")
        await message.answer("❌ У вас нет доступа.")
        return
    
    try:
        async with AsyncSessionLocal() as session:
            from services.admin import get_pending_requests
            
            # Получаем заявки с загруженными пользователями
            requests = await get_pending_requests(session)
            logger.debug(f"Found {len(requests)} pending requests")
            
            if not requests:
                await message.answer("✅ Нет необработанных заявок.")
            else:
                from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                
                text = f"📝 Необработанные заявки: {len(requests)}\n\n"
                keyboard = []
                
                for req in requests[:10]:  # Показываем максимум 10 заявок
                    try:
                        # Получаем telegram_id пользователя через связь
                        user_telegram_id = req.user.telegram_id if req.user else "N/A"
                        username = req.user.username if req.user and req.user.username else "без username"
                        text += f"Заявка #{req.id}\n"
                        text += f"Тип: {req.request_type}\n"
                        text += f"От: {user_telegram_id} (@{username})\n\n"
                        
                        keyboard.append([
                            InlineKeyboardButton(
                                text=f"Открыть #{req.id}",
                                callback_data=f"admin_request_{req.id}"
                            )
                        ])
                    except Exception as e:
                        logger.error(f"Error processing request {req.id}: {e}", exc_info=True)
                        text += f"Заявка #{req.id} - ошибка обработки\n\n"
                
                reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
                await message.answer(text, reply_markup=reply_markup)
                logger.info(f"Admin requests list sent to user {user_id}")
    except Exception as e:
        logger.error(f"Error in handle_admin_requests_button for user {user_id}: {e}", exc_info=True)
        await message.answer("Произошла ошибка при получении заявок. Попробуйте позже.")


@router.message(F.text == "◀️ Назад в меню")
async def handle_back_to_menu_button(message: Message):
    """Обработка кнопки 'Назад в меню'"""
    user_id = message.from_user.id
    logger.info(f"User {user_id} clicked Back to Menu button")
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        db_user = result.scalar_one_or_none()
        
        if not db_user or not db_user.onboarding_completed:
            await message.answer("Сначала пройдите первичное анкетирование через /start")
            return
    
    menu_keyboard = get_main_menu_keyboard(user_id)
    await message.answer("📱 Главное меню:", reply_markup=menu_keyboard)
