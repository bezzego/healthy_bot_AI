"""Обработчики сообщений для aiogram"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import StateFilter
from sqlalchemy.ext.asyncio import AsyncSession
from database.db import AsyncSessionLocal
from database.models import User
from sqlalchemy import select
from services.nutrition import add_nutrition_record, search_food_in_database
from services.daily_scenarios import save_morning_sleep_quality, save_evening_report
from services.admin import create_admin_request
from services.onboarding import save_answer, QUESTIONNAIRE_FLOW, get_current_question
from services.retest import save_retest_answer
from utils.validators import parse_number, validate_scale_value
from utils.logger import setup_logger
from config import settings
from handlers.commands import send_question
from handlers.fsm_states import (
    OnboardingStates, RetestStates, AddingFoodStates, AdminRequestStates,
    MorningCheckinStates, EveningCheckinStates
)
from aiogram.fsm.context import FSMContext

router = Router()
logger = setup_logger(__name__, settings.LOG_LEVEL, settings.DEBUG)


@router.message(StateFilter(OnboardingStates.in_progress, RetestStates.in_progress))
async def handle_questionnaire_answer(message: Message, state: FSMContext):
    """Обработка ответа на вопрос анкеты"""
    user_id = message.from_user.id
    text = message.text
    
    username = message.from_user.username or "без username"
    text_preview = text[:50] if text else "[no text]"
    logger.info(f"User {user_id} (@{username}) answering questionnaire: '{text_preview}'")
    
    try:
        async with AsyncSessionLocal() as session:
            result_db = await session.execute(
                select(User).where(User.telegram_id == user_id)
            )
            db_user = result_db.scalar_one_or_none()
            
            if not db_user:
                await message.answer("Пользователь не найден. Используйте /start")
                return
            
            state_data = await state.get_data()
            current_index = state_data.get("current_question_index", 0)
            answers = state_data.get("answers", {})
            
            if current_index >= len(QUESTIONNAIRE_FLOW):
                await message.answer("Анкета уже завершена")
                return
            
            question_key = QUESTIONNAIRE_FLOW[current_index]
            question = get_current_question(current_index, answers)
            
            if not question:
                await message.answer("Ошибка получения вопроса")
                return
            
            # Проверяем, можно ли пропустить вопрос
            if text.lower().strip() in ["пропустить", "skip", "пропустить этот вопрос"] and question.get("optional"):
                skip = True
                answer = None
            else:
                skip = False
                # Парсим ответ в зависимости от типа вопроса
                if question["type"] == "number":
                    is_valid, value, error = parse_number(text)
                    if not is_valid:
                        await message.answer(error)
                        return
                    answer = value
                elif question["type"] == "scale_0_10":
                    is_valid, value, error = parse_number(text)
                    if not is_valid:
                        await message.answer("Введите число от 0 до 10")
                        return
                    is_valid, error = validate_scale_value(int(value))
                    if not is_valid:
                        await message.answer(error)
                        return
                    answer = int(value)
                elif question["type"] == "scale_1_5":
                    is_valid, value, error = parse_number(text)
                    if not is_valid:
                        await message.answer("Введите число от 1 до 5")
                        return
                    from utils.validators import validate_scale_1_5
                    is_valid, error = validate_scale_1_5(int(value))
                    if not is_valid:
                        await message.answer(error)
                        return
                    answer = int(value)
                elif question["type"] == "scale_0_5":
                    # Старая версия для совместимости
                    is_valid, value, error = parse_number(text)
                    if not is_valid:
                        await message.answer("Введите число от 0 до 5")
                        return
                    from utils.validators import validate_scale_0_5
                    is_valid, error = validate_scale_0_5(int(value))
                    if not is_valid:
                        await message.answer(error)
                        return
                    answer = int(value)
                else:
                    answer = text
            
            # Сохраняем ответ
            current_state = await state.get_state()
            if current_state == OnboardingStates.in_progress:
                result = await save_answer(session, db_user.id, answer, skip=skip, state_data=state_data)
            elif current_state == RetestStates.in_progress:
                result = await save_retest_answer(session, db_user.id, answer, state_data=state_data)
            else:
                return
            
            # Обновляем состояние FSM
            if result.get("completed"):
                await state.clear()
                await message.answer(result["message"])
            elif result.get("next_question"):
                # Обновляем состояние FSM из результата
                if "state_data" in result:
                    await state.update_data(**result["state_data"])
                await send_question(message, result["next_question"], state)
    except Exception as e:
        logger.error(f"Error in handle_questionnaire_answer for user {user_id}: {e}", exc_info=True)
        await message.answer("Произошла ошибка при обработке ответа. Попробуйте снова.")


@router.message(StateFilter(AddingFoodStates.waiting_for_food))
async def handle_adding_food(message: Message, state: FSMContext):
    """Обработка добавления еды"""
    text = message.text
    user_id = message.from_user.id
    username = message.from_user.username or "без username"
    
    # Проверяем, что это текст (не фото)
    if message.photo:
        # Если фото, оно обработается в handle_photo
        logger.debug(f"User {user_id} sent photo in adding_food state, will be handled by handle_photo")
        return
    
    if not text:
        logger.warning(f"User {user_id} sent message without text in adding_food state")
        await message.answer("Пожалуйста, отправьте название блюда текстом или фото еды.")
        return
    
    text_preview = text[:50] if text else "[no text]"
    logger.info(f"User {user_id} (@{username}) adding food: '{text_preview}'")
    
    try:
        async with AsyncSessionLocal() as session:
            result_db = await session.execute(
                select(User).where(User.telegram_id == user_id)
            )
            db_user = result_db.scalar_one_or_none()
            
            if not db_user:
                logger.warning(f"User {user_id} not found in database")
                await message.answer("Пользователь не найден")
                return
            
            # Пытаемся найти продукт в базе
            foods = search_food_in_database(text)
        
            if foods:
                # Если найдено несколько, предлагаем выбрать
                if len(foods) == 1:
                    food = foods[0]
                    # Автоматически добавляем
                    try:
                        await add_nutrition_record(
                            session=session,
                            user_id=db_user.id,
                            food_name=food["name"],
                            calories=food["calories"],
                            protein=food.get("protein", 0),
                            fats=food.get("fats", 0),
                            carbs=food.get("carbs", 0),
                            fiber=food.get("fiber", 0)
                        )
                        await message.answer(
                            f"✅ Добавлено: {food['name']} - {food['calories']} ккал"
                        )
                        await state.clear()
                    except Exception as e:
                        await message.answer(f"Ошибка: {str(e)}")
                else:
                    # Множественный выбор
                    keyboard = []
                    for food in foods[:5]:  # Максимум 5 вариантов
                        keyboard.append([InlineKeyboardButton(
                            text=f"{food['name']} ({food['calories']} ккал)",
                            callback_data=f"select_food_{food['name']}"
                        )])
                    reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
                    await message.answer(
                        "Найдено несколько вариантов. Выберите нужный:",
                        reply_markup=reply_markup
                    )
            else:
                # Не найдено - просим ввести калории вручную
                await message.answer(
                    "Продукт не найден в базе. Отправьте калорийность блюда в формате:\n"
                    "'Название блюда, калории' (например: 'Овсянка с фруктами, 350')"
                )
                await state.update_data(food_name=text)
                await state.set_state(AddingFoodStates.waiting_for_calories)
                logger.debug(f"User {user_id} food '{text}' not found, asked for calories")
    except Exception as e:
        logger.error(f"Error in handle_adding_food for user {user_id}: {e}", exc_info=True)
        await message.answer("Произошла ошибка. Попробуйте снова.")


@router.message(StateFilter(AddingFoodStates.waiting_for_calories))
async def handle_food_calories(message: Message, state: FSMContext):
    """Обработка ввода калорий для еды"""
    text = message.text
    user_id = message.from_user.id
    username = message.from_user.username or "без username"
    state_data = await state.get_data()
    food_name = state_data.get("food_name", "Неизвестное блюдо")
    
    if not text:
        logger.warning(f"User {user_id} sent message without text in waiting_for_calories state")
        await message.answer("Пожалуйста, отправьте калорийность числом.")
        return
    
    logger.info(f"User {user_id} (@{username}) entering calories for '{food_name}': '{text}'")
    
    # Парсим калории
    parts = text.split(",")
    if len(parts) > 1:
        food_name = parts[0].strip()
        is_valid, value, _ = parse_number(parts[1])
        if is_valid:
            calories = value
        else:
            await message.answer("Не удалось распознать калорийность. Попробуйте ещё раз.")
            return
    else:
        is_valid, value, error = parse_number(text)
        if not is_valid:
            await message.answer(error)
            return
        calories = value
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        db_user = result.scalar_one_or_none()
        
        if db_user:
            try:
                # Проверяем, есть ли сохранённое фото
                photo_file_id = state_data.get("photo_file_id")
                
                await add_nutrition_record(
                    session=session,
                    user_id=db_user.id,
                    food_name=food_name,
                    calories=calories,
                    photo_file_id=photo_file_id
                )
                await message.answer(f"✅ Добавлено: {food_name} - {calories:.0f} ккал")
                await state.clear()
                logger.info(f"User {user_id} successfully added food '{food_name}' ({calories} kcal)")
            except Exception as e:
                logger.error(f"Error adding nutrition record for user {user_id}: {e}", exc_info=True)
                await message.answer(f"Ошибка при добавлении записи: {str(e)}")
        else:
            logger.warning(f"User {user_id} not found when adding calories")
            await message.answer("Пользователь не найден")


@router.message(StateFilter(AdminRequestStates.waiting_for_message))
async def handle_admin_request(message: Message, state: FSMContext):
    """Обработка обращения к администратору"""
    text = message.text
    user_id = message.from_user.id
    state_data = await state.get_data()
    request_type = state_data.get("type", "contact")
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        db_user = result.scalar_one_or_none()
        
        if db_user:
            try:
                request = await create_admin_request(
                    session=session,
                    user_id=db_user.id,
                    request_type=request_type,
                    message=text
                )
                await message.answer(
                    "✅ Ваше обращение отправлено администратору. Мы свяжемся с вами в ближайшее время."
                )
                await state.clear()
            except Exception as e:
                await message.answer(f"Ошибка отправки обращения: {str(e)}")


@router.message(StateFilter(AdminRequestStates.waiting_for_recipe_composition))
async def handle_recipe_composition(message: Message, state: FSMContext):
    """Обработка состава рецепта"""
    await state.update_data(composition=message.text)
    await state.set_state(AdminRequestStates.waiting_for_recipe_description)
    await message.answer("Теперь отправьте описание рецепта (пошаговое приготовление):")


@router.message(StateFilter(AdminRequestStates.waiting_for_recipe_description))
async def handle_recipe_description(message: Message, state: FSMContext):
    """Обработка описания рецепта"""
    await state.update_data(description=message.text)
    await state.set_state(AdminRequestStates.waiting_for_recipe_photo)
    await message.answer("Отправьте фото рецепта (или отправьте 'пропустить' чтобы продолжить без фото):")


@router.message(StateFilter(AdminRequestStates.waiting_for_results_data))
async def handle_results_data(message: Message, state: FSMContext):
    """Обработка данных результатов"""
    await message.answer(
        "Для публикации результатов отправьте данные в формате:\n"
        "'Возраст, рост, вес до (дата), вес после (дата), комментарий'\n"
        "Или используйте интерактивную форму через кнопки."
    )


@router.message(F.photo)
async def handle_photo(message: Message, state: FSMContext):
    """Обработка фото"""
    user_id = message.from_user.id
    username = message.from_user.username or "без username"
    photo = message.photo[-1] if message.photo else None
    
    if not photo:
        logger.warning(f"User {user_id} sent message with F.photo filter but no photo found")
        return
    
    file_id = photo.file_id if photo else "None"
    logger.info(f"User {user_id} (@{username}) sent photo (file_id: {file_id[:20]}...)")
    caption = message.caption or ""
    
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == user_id)
            )
            db_user = result.scalar_one_or_none()
            
            if not db_user:
                logger.warning(f"User {user_id} not found in database when processing photo")
                await message.answer("Пользователь не найден. Используйте /start для начала работы.")
                return
            
            current_state = await state.get_state()
            state_data = await state.get_data()
            
            # Фото еды
            if current_state == AddingFoodStates.waiting_for_food or current_state == AddingFoodStates.waiting_for_calories:
                logger.debug(f"User {user_id} sent photo for adding food, state: {current_state}")
                # Пытаемся извлечь калории из подписи
                food_name = state_data.get("food_name", "Неизвестное блюдо")
                calories = 0
                
                # Парсим калории из подписи
                if caption:
                    logger.debug(f"Photo has caption: '{caption[:50]}'")
                    parts = caption.split(",")
                    if parts:
                        food_name = parts[0].strip()
                    if len(parts) > 1:
                        is_valid, value, _ = parse_number(parts[1])
                        if is_valid:
                            calories = int(value)
                            logger.debug(f"Parsed calories from caption: {calories}")
                
                if calories == 0:
                    logger.debug(f"Calories not provided, asking user {user_id} for calories")
                    await message.answer(
                        "Калорийность не указана. Введите калорийность этого блюда числом:"
                    )
                    await state.update_data(food_name=food_name, photo_file_id=photo.file_id)
                    await state.set_state(AddingFoodStates.waiting_for_calories)
                    return
                
                try:
                    await add_nutrition_record(
                        session=session,
                        user_id=db_user.id,
                        food_name=food_name,
                        calories=calories,
                        photo_file_id=photo.file_id
                    )
                    await message.answer(
                        f"✅ Добавлено фото еды: {food_name} - {calories:.0f} ккал"
                    )
                    await state.clear()
                    logger.info(f"User {user_id} successfully added food '{food_name}' ({calories} kcal) from photo")
                except Exception as e:
                    logger.error(f"Error adding nutrition record for user {user_id}: {e}", exc_info=True)
                    await message.answer(f"Ошибка при добавлении записи: {str(e)}")
            # Фото для рецепта или результатов
            elif current_state == AdminRequestStates.waiting_for_recipe_photo:
                logger.debug(f"User {user_id} sent photo for recipe")
                await state.update_data(recipe_photo_file_id=photo.file_id)
                await message.answer("Фото сохранено. Теперь отправьте текст обращения.")
                await state.set_state(AdminRequestStates.waiting_for_message)
            elif current_state == AdminRequestStates.waiting_for_results_data:
                logger.debug(f"User {user_id} sent photo for results")
                if "results_before_photo_file_id" not in state_data or not state_data.get("results_before_photo_file_id"):
                    await state.update_data(results_before_photo_file_id=photo.file_id)
                    await message.answer("Фото 'до' сохранено. Теперь отправьте фото 'после'.")
                else:
                    await state.update_data(results_after_photo_file_id=photo.file_id)
                    await message.answer("Фото 'после' сохранено. Теперь отправьте данные (возраст, рост, вес до, вес после, даты, комментарий).")
            else:
                # Фото вне состояния добавления еды
                logger.debug(f"User {user_id} sent photo but not in any relevant state (current: {current_state})")
                await message.answer("Для добавления еды используйте кнопку '📸 Добавить еду' из меню.")
    except Exception as e:
        logger.error(f"Error in handle_photo for user {user_id}: {e}", exc_info=True)
        await message.answer("Произошла ошибка при обработке фото. Попробуйте снова.")


@router.message(StateFilter(EveningCheckinStates.waiting_for_steps))
async def handle_evening_steps(message: Message, state: FSMContext):
    """Обработка ввода шагов в вечернем чек-ине"""
    logger.debug(f"User {message.from_user.id} entering steps: {message.text}")
    
    from utils.validators import parse_number
    
    is_valid, value, error = parse_number(message.text)
    if not is_valid:
        logger.warning(f"Invalid steps input from user {message.from_user.id}: {message.text}")
        await message.answer("Введите число шагов:")
        return
    
    steps = int(value)
    logger.debug(f"User {message.from_user.id} steps: {steps}")
    
    await state.update_data(steps=steps)
    await state.set_state(EveningCheckinStates.waiting_for_activity)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Да", callback_data="evening_activity_yes")],
        [InlineKeyboardButton(text="Нет", callback_data="evening_activity_no")]
    ])
    
    await message.answer("Была ли сегодня дополнительная физическая активность?", reply_markup=keyboard)
    logger.debug(f"User {message.from_user.id} waiting for activity answer")




@router.message()
async def handle_default(message: Message):
    """Обработчик по умолчанию"""
    await message.answer("Используйте кнопки меню для доступа к функциям бота.")
