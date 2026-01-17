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
from services.onboarding import save_answer, QUESTIONNAIRE_FLOW, get_current_question
from services.retest import save_retest_answer
from utils.validators import parse_number, validate_scale_value
from utils.logger import setup_logger
from config import settings
from handlers.commands import send_question
from handlers.fsm_states import (
    OnboardingStates, RetestStates, AddingFoodStates,
    MorningCheckinStates, EveningCheckinStates, MonthlyMeasurementStates
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


@router.message(StateFilter(AddingFoodStates.waiting_for_food), ~F.photo)
async def handle_adding_food(message: Message, state: FSMContext):
    """Обработка добавления еды (только текст, не фото)"""
    text = message.text
    user_id = message.from_user.id
    username = message.from_user.username or "без username"
    
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


@router.message(StateFilter(AddingFoodStates.waiting_for_food_confirmation))
async def handle_food_confirmation_text_or_voice(message: Message, state: FSMContext):
    """Обработка текстовых или голосовых коррекций в состоянии подтверждения"""
    user_id = message.from_user.id
    username = message.from_user.username or "без username"
    
    try:
        state_data = await state.get_data()
        
        # Получаем текст коррекции
        correction_text = None
        
        if message.text:
            # Текстовое сообщение
            correction_text = message.text
            logger.info(f"User {user_id} (@{username}) sent text correction: '{correction_text[:50]}'")
        elif message.voice:
            # Голосовое сообщение - расшифровываем
            processing_msg = await message.answer("🔊 Расшифровываю голосовое сообщение...")
            try:
                from services.food_recognition import transcribe_voice_to_text
                bot_instance = message.bot
                correction_text = await transcribe_voice_to_text(bot_instance, message.voice.file_id)
                await processing_msg.delete()
                logger.info(f"User {user_id} voice transcribed: '{correction_text[:50]}'")
            except Exception as e:
                await processing_msg.delete()
                logger.error(f"Error transcribing voice for user {user_id}: {e}", exc_info=True)
                await message.answer("❌ Не удалось расшифровать голосовое сообщение. Попробуйте отправить текстом.")
                return
        else:
            await message.answer("Пожалуйста, отправьте текст или голосовое сообщение с коррекцией.")
            return
        
        if not correction_text or not correction_text.strip():
            await message.answer("Текст коррекции пуст. Попробуйте еще раз.")
            return
        
        # Обрабатываем коррекцию через нейросеть
        processing_msg = await message.answer("🤖 Обрабатываю коррекцию через нейросеть...")
        
        try:
            from services.food_recognition import process_food_correction
            
            # Формируем текущие данные о еде
            current_food_data = {
                "food_name": state_data.get("food_name", "Неизвестное блюдо"),
                "ingredients": state_data.get("ingredients", []),
                "total_calories": state_data.get("total_calories", 0),
                "total_protein": state_data.get("total_protein", 0),
                "total_fats": state_data.get("total_fats", 0),
                "total_carbs": state_data.get("total_carbs", 0)
            }
            
            # Обрабатываем коррекцию
            updated_data = await process_food_correction(current_food_data, correction_text)
            
            await processing_msg.delete()
            
            # Обновляем данные в состоянии
            await state.update_data(
                food_name=updated_data["food_name"],
                total_calories=updated_data["total_calories"],
                total_protein=updated_data["total_protein"],
                total_fats=updated_data["total_fats"],
                total_carbs=updated_data["total_carbs"],
                ingredients=updated_data.get("ingredients", [])
            )
            
            # Формируем обновленное сообщение с информацией
            food_name = updated_data["food_name"]
            ingredients = updated_data.get("ingredients", [])
            total_calories = updated_data["total_calories"]
            total_protein = updated_data["total_protein"]
            total_fats = updated_data["total_fats"]
            total_carbs = updated_data["total_carbs"]
            
            result_text = f"✅ Название: {food_name}\n"
            
            # Список ингредиентов
            if ingredients and len(ingredients) > 0:
                ingredient_names = [ing.get("name", "") for ing in ingredients if ing.get("name")]
                if ingredient_names:
                    result_text += f"📌 Ингредиенты: {', '.join(ingredient_names)}\n"
            
            # Вес порции
            total_weight = 0
            if ingredients:
                import re
                for ing in ingredients:
                    amount_str = ing.get("amount", "")
                    if amount_str:
                        weight_match = re.search(r'(\d+)', amount_str.replace(' ', ''))
                        if weight_match:
                            total_weight += int(weight_match.group(1))
            
            if total_weight > 0:
                result_text += f"⚖️ Вес порции: {total_weight} грамм\n"
            
            # КБЖУ
            result_text += f"⚡️ Калорийность: {total_calories:.0f} ккал\n"
            result_text += f"🍖 Белки: {total_protein:.0f} грамм\n"
            result_text += f"🍕 Жиры: {total_fats:.0f} грамм\n"
            result_text += f"🍞 Углеводы: {total_carbs:.0f} грамм\n"
            result_text += f"💡 Общая калорийность: {total_calories:.0f} ккал"
            
            # Добавляем кнопки
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="Зафиксировать", callback_data="food_confirm"),
                    InlineKeyboardButton(text="Исправить", callback_data="food_correct")
                ],
                [InlineKeyboardButton(text="Отменить", callback_data="food_cancel")]
            ])
            
            await message.answer(result_text, reply_markup=keyboard)
            logger.info(
                f"User {user_id}: Food data updated after correction "
                f"({total_calories:.0f} kcal), waiting for confirmation"
            )
            
        except Exception as e:
            await processing_msg.delete()
            logger.error(f"Error processing food correction for user {user_id}: {e}", exc_info=True)
            await message.answer(
                "❌ Не удалось обработать коррекцию. "
                "Попробуйте еще раз или используйте кнопки для продолжения."
            )
    
    except Exception as e:
        logger.error(f"Error in handle_food_confirmation_text_or_voice for user {user_id}: {e}", exc_info=True)
        await message.answer("Произошла ошибка при обработке коррекции. Попробуйте еще раз.")


@router.message(StateFilter(AddingFoodStates.waiting_for_food_correction))
async def handle_food_correction(message: Message, state: FSMContext):
    """Обработка корректировки информации о еде (старый путь через кнопку 'Исправить')"""
    user_id = message.from_user.id
    correction_text = message.text
    
    try:
        state_data = await state.get_data()
        
        # Просим указать название и калории вручную после коррекции
        await state.update_data(
            photo_file_id=state_data.get("photo_file_id"),
            correction=correction_text
        )
        await state.set_state(AddingFoodStates.waiting_for_calories)
        
        await message.answer(
            "Понял, что нужно исправить. Укажите название блюда и калорийность:\n\n"
            "Например: Овсянка с бананом, 350"
        )
        logger.info(f"User {user_id} provided correction: {correction_text[:50]}")
    except Exception as e:
        logger.error(f"Error handling food correction for user {user_id}: {e}", exc_info=True)
        await message.answer("Произошла ошибка. Попробуйте еще раз.")
        await state.clear()


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


@router.message(F.photo)
async def handle_photo(message: Message, state: FSMContext):
    """Обработка фото"""
    user_id = message.from_user.id
    username = message.from_user.username or "без username"
    
    # Логируем в самом начале
    logger.info(f"🔵 handle_photo triggered for user {user_id} (@{username})")
    
    photo = message.photo[-1] if message.photo else None
    
    if not photo:
        logger.warning(f"User {user_id} sent message with F.photo filter but no photo found")
        return
    
    file_id = photo.file_id if photo else "None"
    logger.info(f"📸 User {user_id} (@{username}) sent photo (file_id: {file_id[:20]}...)")
    caption = message.caption or ""
    
    # Логируем текущее состояние
    current_state = await state.get_state()
    logger.info(f"📋 Current state: {current_state}")
    
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
            
            # current_state уже получен выше
            state_data = await state.get_data()
            logger.debug(f"State data: {state_data}")
            
            # Обрабатываем фото только в нужных состояниях
            if current_state not in [
                AddingFoodStates.waiting_for_food,
                AddingFoodStates.waiting_for_calories
            ]:
                logger.debug(f"User {user_id} sent photo but not in relevant state (current: {current_state})")
                await message.answer("Для добавления еды используйте кнопку '📸 Добавить еду' из меню.")
                return
            
            # Фото еды
            if current_state == AddingFoodStates.waiting_for_food or current_state == AddingFoodStates.waiting_for_calories:
                logger.debug(f"User {user_id} sent photo for adding food, state: {current_state}")
                
                # Отправляем сообщение о начале обработки
                processing_msg = await message.answer("🔍 Анализирую фото еды... Пожалуйста, подождите.")
                
                try:
                    # Распознаем еду через OpenAI GPT-4 Vision
                    from services.food_recognition import recognize_food_from_telegram_photo
                    
                    bot_instance = message.bot  # Получаем бот из message
                    recognition_result = await recognize_food_from_telegram_photo(bot_instance, photo.file_id)
                    
                    food_name = recognition_result["food_name"]
                    ingredients = recognition_result.get("ingredients", [])
                    total_calories = recognition_result.get("total_calories", recognition_result.get("calories", 0))
                    total_protein = recognition_result.get("total_protein", recognition_result.get("protein", 0))
                    total_fats = recognition_result.get("total_fats", recognition_result.get("fats", 0))
                    total_carbs = recognition_result.get("total_carbs", recognition_result.get("carbs", 0))
                    
                    # Если пользователь указал калории в подписи, используем их (приоритет над AI)
                    if caption:
                        logger.debug(f"Photo has caption: '{caption[:50]}'")
                        parts = caption.split(",")
                        if parts and len(parts) > 1:
                            is_valid, value, _ = parse_number(parts[1])
                            if is_valid and value > 0:
                                total_calories = float(value)
                                logger.debug(f"Using calories from caption: {total_calories}")
                    
                    # Если калории = 0 (не распознано), показываем лояльное сообщение
                    if total_calories == 0:
                        await processing_msg.delete()
                        await message.answer(
                            "Не могу понять, что у вас на фото 😔\n\n"
                            "Опишите блюдо в голосовом сообщении или текстом.\n\n"
                            "Например:\n"
                            "• «Овсянка с бананом, 350 ккал»\n"
                            "• «Куриная грудка с овощами, 280 ккал»"
                        )
                        await state.clear()
                        logger.info(f"User {user_id}: Food not recognized (calories=0), requested manual input")
                    else:
                        # Не сохраняем сразу, а показываем кнопки для подтверждения
                        await processing_msg.delete()
                        
                        # Сохраняем данные во временное состояние
                        await state.update_data(
                            food_name=food_name,
                            total_calories=total_calories,
                            total_protein=total_protein,
                            total_fats=total_fats,
                            total_carbs=total_carbs,
                            ingredients=ingredients,
                            photo_file_id=photo.file_id
                        )
                        await state.set_state(AddingFoodStates.waiting_for_food_confirmation)
                        
                        # Формируем сообщение в новом формате
                        result_text = f"✅ Название: {food_name}\n"
                        
                        # Список ингредиентов через запятую
                        if ingredients and len(ingredients) > 0:
                            ingredient_names = [ing.get("name", "") for ing in ingredients if ing.get("name")]
                            if ingredient_names:
                                result_text += f"📌 Ингредиенты: {', '.join(ingredient_names)}\n"
                        
                        # Вес порции (суммируем из amount или используем общий вес)
                        total_weight = 0
                        if ingredients and len(ingredients) > 0:
                            import re
                            for ing in ingredients:
                                amount_str = ing.get("amount", "")
                                if amount_str:
                                    # Пытаемся извлечь число из строки типа "150г", "200 г"
                                    weight_match = re.search(r'(\d+)', amount_str.replace(' ', ''))
                                    if weight_match:
                                        total_weight += int(weight_match.group(1))
                        
                        if total_weight > 0:
                            result_text += f"⚖️ Вес порции: {total_weight} грамм\n"
                        
                        # КБЖУ
                        result_text += f"⚡️ Калорийность: {total_calories:.0f} ккал\n"
                        result_text += f"🍖 Белки: {total_protein:.0f} грамм\n"
                        result_text += f"🍕 Жиры: {total_fats:.0f} грамм\n"
                        result_text += f"🍞 Углеводы: {total_carbs:.0f} грамм\n"
                        result_text += f"💡 Общая калорийность: {total_calories:.0f} ккал"
                        
                        # Добавляем кнопки
                        keyboard = InlineKeyboardMarkup(inline_keyboard=[
                            [
                                InlineKeyboardButton(text="Зафиксировать", callback_data="food_confirm"),
                                InlineKeyboardButton(text="Исправить", callback_data="food_correct")
                            ],
                            [InlineKeyboardButton(text="Отменить", callback_data="food_cancel")]
                        ])
                        
                        await message.answer(result_text, reply_markup=keyboard)
                        logger.info(
                            f"User {user_id}: Food recognized '{food_name}' "
                            f"({total_calories:.0f} kcal), waiting for confirmation"
                        )
                
                except Exception as e:
                    await processing_msg.delete()
                    error_msg = str(e)
                    logger.error(f"Error recognizing food for user {user_id}: {e}", exc_info=True)
                    
                    # Определяем тип ошибки: техническая или нетехническая
                    is_technical_error = any(keyword in error_msg.lower() for keyword in [
                        "api key", "openai api ключ", "не настроен", "недоступен",
                        "connection", "timeout", "network", "proxy", "403", "401",
                        "rate limit", "quota", "server error", "500", "502", "503"
                    ])
                    
                    if is_technical_error:
                        # Техническая ошибка - показываем базовое сообщение и уведомляем админов
                        from main import send_error_to_admins
                        await send_error_to_admins(
                            f"Техническая ошибка при распознавании еды",
                            f"User: {user_id} (@{username})\nError: {error_msg}",
                            f"Photo recognition failed"
                        )
                        
                        await state.update_data(photo_file_id=photo.file_id)
                        await state.set_state(AddingFoodStates.waiting_for_calories)
                        await message.answer(
                            "❌ Не удалось автоматически распознать еду на фото.\n\n"
                            "Пожалуйста, укажите:\n"
                            "1. Название блюда\n"
                            "2. Калорийность (например: Овсянка, 350)"
                        )
                        logger.warning(f"Technical error in food recognition for user {user_id}, admins notified")
                    else:
                        # Нетехническая ошибка (не распознано) - лояльное сообщение
                        await message.answer(
                            "Не могу понять, что у вас на фото 😔\n\n"
                            "Опишите блюдо в голосовом сообщении или текстом.\n\n"
                            "Например:\n"
                            "• «Овсянка с бананом, 350 ккал»\n"
                            "• «Куриная грудка с овощами, 280 ккал»"
                        )
                        await state.clear()
                        logger.info(f"User {user_id}: Food not recognized (non-technical error), requested manual input")
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




@router.message(StateFilter(MonthlyMeasurementStates.waiting_for_weight))
async def handle_monthly_weight(message: Message, state: FSMContext):
    """Обработка веса в ежемесячных замерах"""
    user_id = message.from_user.id
    text = message.text
    
    try:
        from utils.validators import parse_number
        
        is_valid, value, error = parse_number(text)
        if not is_valid:
            await message.answer(f"Пожалуйста, введите число (вес в кг). Например: 65.5")
            return
        
        weight = float(value)
        if weight <= 0 or weight > 300:
            await message.answer("Вес должен быть от 1 до 300 кг. Попробуйте еще раз.")
            return
        
        await state.update_data(weight=weight)
        await state.set_state(MonthlyMeasurementStates.waiting_for_waist)
        await message.answer("Укажите обхват талии (см):\nНапример: 75")
        
    except Exception as e:
        logger.error(f"Error handling monthly weight for user {user_id}: {e}", exc_info=True)
        await message.answer("Произошла ошибка. Попробуйте еще раз.")


@router.message(StateFilter(MonthlyMeasurementStates.waiting_for_waist))
async def handle_monthly_waist(message: Message, state: FSMContext):
    """Обработка обхвата талии"""
    user_id = message.from_user.id
    text = message.text
    
    try:
        from utils.validators import parse_number
        
        is_valid, value, error = parse_number(text)
        if not is_valid:
            await message.answer(f"Пожалуйста, введите число (обхват талии в см). Например: 75")
            return
        
        waist = float(value)
        if waist <= 0 or waist > 200:
            await message.answer("Обхват талии должен быть от 1 до 200 см. Попробуйте еще раз.")
            return
        
        await state.update_data(waist_circumference=waist)
        await state.set_state(MonthlyMeasurementStates.waiting_for_hips)
        await message.answer("Укажите обхват бёдер (см):\nНапример: 95")
        
    except Exception as e:
        logger.error(f"Error handling monthly waist for user {user_id}: {e}", exc_info=True)
        await message.answer("Произошла ошибка. Попробуйте еще раз.")


@router.message(StateFilter(MonthlyMeasurementStates.waiting_for_hips))
async def handle_monthly_hips(message: Message, state: FSMContext):
    """Обработка обхвата бёдер"""
    user_id = message.from_user.id
    text = message.text
    
    try:
        from utils.validators import parse_number
        
        is_valid, value, error = parse_number(text)
        if not is_valid:
            await message.answer(f"Пожалуйста, введите число (обхват бёдер в см). Например: 95")
            return
        
        hips = float(value)
        if hips <= 0 or hips > 200:
            await message.answer("Обхват бёдер должен быть от 1 до 200 см. Попробуйте еще раз.")
            return
        
        await state.update_data(hips_circumference=hips)
        await state.set_state(MonthlyMeasurementStates.waiting_for_chest)
        await message.answer("Укажите обхват груди (см):\nНапример: 90")
        
    except Exception as e:
        logger.error(f"Error handling monthly hips for user {user_id}: {e}", exc_info=True)
        await message.answer("Произошла ошибка. Попробуйте еще раз.")


@router.message(StateFilter(MonthlyMeasurementStates.waiting_for_chest))
async def handle_monthly_chest(message: Message, state: FSMContext):
    """Обработка обхвата груди и завершение замеров"""
    user_id = message.from_user.id
    text = message.text
    
    try:
        from utils.validators import parse_number
        from services.monthly_measurements import save_monthly_measurement
        from services.reports import get_monthly_report, format_monthly_report_text
        from services.monthly_measurements import get_previous_month_measurement
        
        is_valid, value, error = parse_number(text)
        if not is_valid:
            await message.answer(f"Пожалуйста, введите число (обхват груди в см). Например: 90")
            return
        
        chest = float(value)
        if chest <= 0 or chest > 200:
            await message.answer("Обхват груди должен быть от 1 до 200 см. Попробуйте еще раз.")
            return
        
        state_data = await state.get_data()
        weight = state_data.get("weight")
        waist = state_data.get("waist_circumference")
        hips = state_data.get("hips_circumference")
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == user_id)
            )
            db_user = result.scalar_one_or_none()
            
            if not db_user:
                await message.answer("Пользователь не найден")
                await state.clear()
                return
            
            # Сохраняем замеры
            measurement = await save_monthly_measurement(
                session=session,
                user_id=db_user.id,
                weight=weight,
                waist_circumference=waist,
                hips_circumference=hips,
                chest_circumference=chest
            )
            
            # Получаем предыдущий месяц для сравнения
            previous_measurement = await get_previous_month_measurement(session, db_user.id)
            
            # Получаем статистику за месяц
            stats = await get_monthly_report(session, db_user.id, measurement, previous_measurement)
            
            # Формируем и отправляем отчет
            report_text = format_monthly_report_text(stats)
            await message.answer(report_text)
            
            await state.clear()
            logger.info(
                f"Monthly measurements saved and report sent to user {user_id}: "
                f"weight={weight}, waist={waist}, hips={hips}, chest={chest}"
            )
        
    except Exception as e:
        logger.error(f"Error handling monthly chest for user {user_id}: {e}", exc_info=True)
        await message.answer("Произошла ошибка при сохранении замеров. Попробуйте еще раз.")


@router.message(F.chat.type == "private")
async def handle_default(message: Message):
    """Обработчик по умолчанию (только для приватных чатов)"""
    await message.answer("Используйте кнопки меню для доступа к функциям бота.")
