"""Главный файл запуска бота для aiogram"""
import asyncio
import logging
import sys
import traceback
from typing import Optional
from datetime import datetime
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Update
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from config import settings
from database.db import init_db
from handlers import commands, callbacks, messages, settings as handlers_settings, menu_handlers

# Настройка подробного цветного логирования
from utils.logger import setup_logger

logger = setup_logger(__name__, settings.LOG_LEVEL, settings.DEBUG)

# Глобальная переменная для бота (для отправки ошибок админам)
_bot_instance: Optional[Bot] = None


async def send_error_to_admins(error_message: str, error_details: str = "", update_info: str = ""):
    """Отправить подробную ошибку администраторам"""
    global _bot_instance
    if not _bot_instance:
        logger.warning("Bot instance not available, cannot send error to admins")
        return
    
    try:
        admin_ids = settings.admin_ids
        if not admin_ids:
            logger.warning("No admin IDs configured, skipping error notification")
            return
        
        logger.debug(f"Preparing error notification for {len(admin_ids)} admin(s)")
        
        full_message = f"🚨 <b>ОШИБКА В БОТЕ</b>\n\n"
        full_message += f"<b>Сообщение:</b> {error_message}\n"
        
        if update_info:
            full_message += f"<b>Контекст:</b> {update_info}\n"
        
        if error_details:
            # Ограничиваем длину деталей для Telegram (до 4000 символов)
            details = error_details[:3500]
            if len(error_details) > 3500:
                details += "\n\n... (обрезано)"
            full_message += f"\n<b>Детали:</b>\n<code>{details}</code>\n"
        
        full_message += f"\n<b>Время:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        sent_count = 0
        failed_count = 0
        for admin_id in admin_ids:
            try:
                logger.debug(f"Sending error notification to admin {admin_id}")
                await _bot_instance.send_message(
                    chat_id=admin_id,
                    text=full_message,
                    parse_mode="HTML"
                )
                sent_count += 1
                logger.info(f"✅ Error notification sent to admin {admin_id}")
            except Exception as e:
                from aiogram.exceptions import TelegramBadRequest
                error_str = str(e)
                error_type = type(e).__name__
                
                # Если админ не начал диалог с ботом - это не критическая ошибка
                if (isinstance(e, TelegramBadRequest) and 
                    ("chat not found" in error_str.lower() or 
                     "bot was blocked" in error_str.lower() or
                     "chat_id is empty" in error_str.lower())):
                    logger.warning(f"⚠️ Admin {admin_id} chat not found or blocked. Admin needs to start chat with bot first.")
                else:
                    logger.error(f"❌ Failed to send error to admin {admin_id}: {error_type}: {error_str}", exc_info=True)
                failed_count += 1
        
        if sent_count > 0:
            logger.info(f"✅ Error notifications sent: {sent_count}/{len(admin_ids)}")
        if failed_count > 0:
            logger.warning(f"⚠️ Failed to send to {failed_count} admin(s)")
        
    except Exception as e:
        logger.critical(f"Critical error in send_error_to_admins: {e}", exc_info=True)


async def check_and_send_morning_greetings(bot: Bot):
    """Проверить и отправить утренние приветствия пользователям с учётом их персонального времени"""
    logger.debug("Checking users for morning greetings based on personal time")
    
    try:
        from services.daily_scenarios import get_morning_greeting, get_or_create_daily_record
        from utils.templates import get_morning_sleep_question, get_food_reminder, MORNING_SLEEP_OPTIONS
        from database.db import AsyncSessionLocal
        from database.models import User
        from sqlalchemy import select
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        from datetime import datetime, date
        import pytz
        
        # Текущее время в Москве (базовое время для проекта)
        moscow_tz = pytz.timezone(settings.DEFAULT_TIMEZONE)
        now_moscow = datetime.now(moscow_tz)
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.onboarding_completed == True)
            )
            users = result.scalars().all()
            
            sent_count = 0
            for user in users:
                try:
                    # Получаем настройки времени пользователя (по умолчанию московское время)
                    timezone_str = user.timezone or settings.DEFAULT_TIMEZONE
                    morning_time_str = user.morning_notification_time or "08:00"
                    
                    try:
                        # Преобразуем время пользователя из московского в его локальное время
                        user_tz = pytz.timezone(timezone_str)
                        hour, minute = map(int, morning_time_str.split(":"))
                        user_local_time = now_moscow.astimezone(user_tz)
                        
                        # Проверяем, наступило ли время утреннего приветствия (проверяем каждые 15 минут)
                        # Отправляем, если час совпадает и текущие минуты находятся в окне 15 минут от назначенного времени
                        current_minute = user_local_time.minute
                        current_hour = user_local_time.hour
                        
                        # Проверяем, что час совпадает и текущее время в пределах 15 минут от назначенного
                        # Например, для 08:00 отправляем при проверке в 08:00-08:14
                        if current_hour == hour:
                            time_diff = current_minute - minute
                            if 0 <= time_diff < 15:
                                # Проверяем, не отправляли ли уже сегодня (по локальной дате пользователя)
                                today = user_local_time.date()
                                daily_record = await get_or_create_daily_record(session, user.id, today)
                                
                                # Отправляем только если ещё не отправляли утреннее приветствие сегодня
                                # (проверяем, что нет утренних данных за сегодня)
                                if daily_record.morning_sleep_quality is None and daily_record.morning_energy is None:
                                    await send_morning_greeting_to_user(bot, session, user, daily_record)
                                    sent_count += 1
                                    logger.info(
                                        f"Morning greeting sent to user {user.telegram_id} at {timezone_str} "
                                        f"{morning_time_str} (local time: {user_local_time.strftime('%H:%M')})"
                                    )
                    except (ValueError, pytz.exceptions.UnknownTimeZoneError) as tz_error:
                        logger.warning(f"Invalid timezone for user {user.telegram_id} ({timezone_str}): {tz_error}")
                        # Fallback: используем дефолтное время 08:00 МСК
                        if now_moscow.hour == 8 and 0 <= now_moscow.minute < 15:
                            today_moscow = now_moscow.date()
                            daily_record = await get_or_create_daily_record(session, user.id, today_moscow)
                            if daily_record.morning_sleep_quality is None and daily_record.morning_energy is None:
                                await send_morning_greeting_to_user(bot, session, user, daily_record)
                                sent_count += 1
                                
                except Exception as e:
                    logger.error(f"Error checking morning greeting for user {user.telegram_id}: {e}", exc_info=True)
            
            if sent_count > 0:
                logger.info(f"Sent {sent_count} morning greetings")
            
    except Exception as e:
        logger.critical(f"Critical error in check_and_send_morning_greetings: {e}", exc_info=True)
        await send_error_to_admins("Critical error in check_and_send_morning_greetings", str(e))


async def send_morning_greeting_to_user(bot: Bot, session, user, daily_record):
    """Отправить утреннее приветствие конкретному пользователю"""
    from services.daily_scenarios import get_morning_greeting, get_or_create_daily_record
    from utils.templates import get_morning_sleep_question, get_food_reminder, MORNING_SLEEP_OPTIONS
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    
    greeting = get_morning_greeting()
    await bot.send_message(
        chat_id=user.telegram_id,
        text=greeting
    )
    
    # Вопрос о сне (новый формат)
    if daily_record.morning_sleep_quality is None:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=option, callback_data=f"morning_sleep_{i}")]
            for i, option in enumerate(MORNING_SLEEP_OPTIONS)
        ])
        
        await bot.send_message(
            chat_id=user.telegram_id,
            text=get_morning_sleep_question(),
            reply_markup=keyboard
        )
    
    # Напоминание о фото еды
    await bot.send_message(
        chat_id=user.telegram_id,
        text=get_food_reminder()
    )


async def check_and_send_water_reminders(bot: Bot):
    """Проверить и отправить напоминания о воде пользователям в их персональное время (11:30 и 15:30)"""
    logger.debug("Checking users for water reminders based on personal timezone")
    
    try:
        from services.daily_scenarios import get_water_tip
        from database.db import AsyncSessionLocal
        from database.models import User
        from sqlalchemy import select
        from datetime import datetime
        from config import settings
        import pytz
        
        # Текущее время в Москве (базовое время для проекта)
        moscow_tz = pytz.timezone(settings.DEFAULT_TIMEZONE)
        now_moscow = datetime.now(moscow_tz)
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.onboarding_completed == True)
            )
            users = result.scalars().all()
            
            sent_count = 0
            water_times = [11, 15]  # 11:30 и 15:30
            
            for user in users:
                try:
                    # Получаем настройки времени пользователя (по умолчанию московское время)
                    timezone_str = user.timezone or settings.DEFAULT_TIMEZONE
                    
                    try:
                        # Преобразуем время пользователя из московского в его локальное время
                        user_tz = pytz.timezone(timezone_str)
                        user_local_time = now_moscow.astimezone(user_tz)
                        current_hour = user_local_time.hour
                        current_minute = user_local_time.minute
                        
                        # Проверяем, наступило ли время водного напоминания (11:30 или 15:30)
                        # Проверяем каждые 15 минут: отправляем в окне 30-44 минут, но только один раз
                        should_send_water = False
                        water_hour = None
                        
                        for water_h in water_times:
                            # Проверяем окно: текущее время должно быть ровно в 30 минут или в пределах 30-44 минут
                            # Но отправляем только в первую проверку после 30 минут (30-32 минуты)
                            if current_hour == water_h:
                                time_diff = current_minute - 30
                                if 0 <= time_diff <= 2:  # Отправляем в окне 30-32 минуты для надежности
                                    should_send_water = True
                                    water_hour = water_h
                                    break
                        
                        if should_send_water:
                            # Отправляем напоминание о воде в персональное время пользователя
                            tip = get_water_tip()
                            await bot.send_message(
                                chat_id=user.telegram_id,
                                text=tip
                            )
                            sent_count += 1
                            logger.info(
                                f"Water reminder ({water_hour}:30) sent to user {user.telegram_id} at {timezone_str} "
                                f"(local time: {user_local_time.strftime('%H:%M')})"
                            )
                    except (ValueError, pytz.exceptions.UnknownTimeZoneError) as tz_error:
                        logger.warning(f"Invalid timezone for user {user.telegram_id} ({timezone_str}): {tz_error}")
                        
                except Exception as e:
                    logger.error(f"Error checking water reminder for user {user.telegram_id}: {e}", exc_info=True)
            
            if sent_count > 0:
                logger.info(f"Sent {sent_count} water reminders")
            
    except Exception as e:
        logger.critical(f"Critical error in check_and_send_water_reminders: {e}", exc_info=True)
        await send_error_to_admins("Critical error in check_and_send_water_reminders", str(e))


async def check_and_send_evening_reminders(bot: Bot):
    """Проверить и отправить вечерние напоминания пользователям с учётом их персонального времени"""
    logger.debug("Checking users for evening reminders based on personal time")
    
    try:
        from database.db import AsyncSessionLocal
        from database.models import User
        from sqlalchemy import select
        from services.daily_scenarios import get_or_create_daily_record
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        from datetime import datetime, date
        import pytz
        
        # Текущее время в Москве (базовое время для проекта)
        moscow_tz = pytz.timezone(settings.DEFAULT_TIMEZONE)
        now_moscow = datetime.now(moscow_tz)
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.onboarding_completed == True)
            )
            users = result.scalars().all()
            
            sent_count = 0
            for user in users:
                try:
                    # Получаем настройки времени пользователя (по умолчанию московское время)
                    timezone_str = user.timezone or settings.DEFAULT_TIMEZONE
                    evening_time_str = user.evening_notification_time or "22:00"
                    
                    try:
                        # Преобразуем время пользователя из московского в его локальное время
                        user_tz = pytz.timezone(timezone_str)
                        hour, minute = map(int, evening_time_str.split(":"))
                        user_local_time = now_moscow.astimezone(user_tz)
                        
                        # Проверяем, наступило ли время вечернего напоминания (проверяем каждые 15 минут)
                        # Отправляем, если час совпадает и текущие минуты находятся в окне 15 минут от назначенного времени
                        current_minute = user_local_time.minute
                        current_hour = user_local_time.hour
                        
                        # Проверяем, что час совпадает и текущее время в пределах 15 минут от назначенного
                        # Например, для 22:00 отправляем при проверке в 22:00-22:14
                        if current_hour == hour:
                            time_diff = current_minute - minute
                            if 0 <= time_diff < 15:
                                # Проверяем, не заполнен ли уже вечерний отчёт (по локальной дате пользователя)
                                today = user_local_time.date()
                                daily_record = await get_or_create_daily_record(session, user.id, today)
                                
                                if daily_record.evening_mood is None:
                                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                                        [InlineKeyboardButton(text="📊 Заполнить вечерний отчёт", callback_data="evening_report")],
                                    ])
                                    
                                    await bot.send_message(
                                        chat_id=user.telegram_id,
                                        text="🌙 Добрый вечер! Время заполнить дневной отчёт о самочувствии и активности.",
                                        reply_markup=keyboard
                                    )
                                    sent_count += 1
                                    logger.info(
                                        f"Evening reminder sent to user {user.telegram_id} at {timezone_str} "
                                        f"{evening_time_str} (local time: {user_local_time.strftime('%H:%M')})"
                                    )
                    except (ValueError, pytz.exceptions.UnknownTimeZoneError) as tz_error:
                        logger.warning(f"Invalid timezone for user {user.telegram_id} ({timezone_str}): {tz_error}")
                                
                except Exception as e:
                    logger.error(f"Error checking evening reminder for user {user.telegram_id}: {e}", exc_info=True)
            
            if sent_count > 0:
                logger.info(f"Sent {sent_count} evening reminders")
            
    except Exception as e:
        logger.critical(f"Critical error in check_and_send_evening_reminders: {e}", exc_info=True)
        await send_error_to_admins("Critical error in check_and_send_evening_reminders", str(e))


def setup_scheduler(bot: Bot):
    """Настроить планировщик задач для работы с персональными часовыми поясами пользователей"""
    moscow_tz = settings.DEFAULT_TIMEZONE
    scheduler = AsyncIOScheduler(timezone=moscow_tz)
    
    # Проверка утренних, вечерних и водных уведомлений каждые 15 минут
    # Это позволяет учитывать персональное время каждого пользователя с высокой точностью
    scheduler.add_job(
        check_and_send_morning_greetings,
        CronTrigger(minute="*/15", timezone=moscow_tz),  # Каждые 15 минут - проверяем всех пользователей
        args=[bot],
        id="check_morning_greetings",
        replace_existing=True
    )
    
    scheduler.add_job(
        check_and_send_evening_reminders,
        CronTrigger(minute="*/15", timezone=moscow_tz),  # Каждые 15 минут - проверяем всех пользователей
        args=[bot],
        id="check_evening_reminders",
        replace_existing=True
    )
    
    # Напоминания о воде проверяем каждые 15 минут для точной отправки в персональное время каждого пользователя
    scheduler.add_job(
        check_and_send_water_reminders,
        CronTrigger(minute="*/15", timezone=moscow_tz),  # Каждые 15 минут - проверяем всех пользователей
        args=[bot],
        id="check_water_reminders",
        replace_existing=True
    )
    
    # Недельный и месячный отчёты проверяем каждые 15 минут для отправки в персональное время каждого пользователя
    scheduler.add_job(
        check_and_send_weekly_reports,
        CronTrigger(minute="*/15", timezone=moscow_tz),  # Каждые 15 минут - проверяем всех пользователей
        args=[bot],
        id="check_weekly_reports",
        replace_existing=True
    )
    
    scheduler.add_job(
        check_and_send_monthly_reports,
        CronTrigger(minute="*/15", timezone=moscow_tz),  # Каждые 15 минут - проверяем всех пользователей
        args=[bot],
        id="check_monthly_reports",
        replace_existing=True
    )
    
    scheduler.start()
    logger.info(f"Scheduler started - all notifications use personal timezone for each user")
    logger.info(f"Base timezone: {moscow_tz}, check interval: every 15 minutes")
    return scheduler


async def check_and_send_weekly_reports(bot: Bot):
    """Проверить и отправить недельные отчёты пользователям в их персональное время (воскресенье в 22:00)"""
    logger.debug("Checking users for weekly reports based on personal timezone")
    
    try:
        from services.reports import get_weekly_report, format_weekly_report_text
        from database.db import AsyncSessionLocal
        from database.models import User
        from sqlalchemy import select
        from datetime import datetime
        from config import settings
        import pytz
    
        # Текущее время в Москве (базовое время для проекта)
        moscow_tz = pytz.timezone(settings.DEFAULT_TIMEZONE)
        now_moscow = datetime.now(moscow_tz)
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.onboarding_completed == True)
            )
            users = result.scalars().all()
            
            sent_count = 0
            for user in users:
                try:
                    # Получаем настройки времени пользователя (по умолчанию московское время)
                    timezone_str = user.timezone or settings.DEFAULT_TIMEZONE
                    
                    try:
                        # Преобразуем время пользователя из московского в его локальное время
                        user_tz = pytz.timezone(timezone_str)
                        user_local_time = now_moscow.astimezone(user_tz)
                        
                        # Проверяем, наступило ли время недельного отчета (воскресенье в 22:00)
                        # Проверяем каждые 15 минут: отправляем в окне 22:00-22:14
                        is_sunday = user_local_time.weekday() == 6  # Воскресенье = 6
                        current_hour = user_local_time.hour
                        current_minute = user_local_time.minute
                        
                        if is_sunday and current_hour == 22 and 0 <= current_minute < 15:
                            # Проверяем, не отправляли ли уже сегодня (по локальной дате пользователя)
                            today = user_local_time.date()
                            
                            # Получаем или создаем запись для отслеживания отправленных отчетов
                            # Используем поле last_weekly_report_date если оно есть, или проверяем по логике
                            # Для простоты отправляем только если есть данные за неделю
                            stats = await get_weekly_report(session, user.id)
                            
                            # Отправляем только если есть данные и еще не отправляли сегодня
                            # Проверка "не отправляли сегодня" реализуется через проверку времени последней отправки
                            # Для MVP: отправляем если есть данные (можно улучшить добавив поле last_weekly_report_date)
                            if stats.get("morning_count", 0) > 0 or stats.get("evening_count", 0) > 0:
                                report_text = format_weekly_report_text(stats)
                                
                                await bot.send_message(
                                    chat_id=user.telegram_id,
                                    text=report_text
                                )
                                sent_count += 1
                                logger.info(
                                    f"Weekly report sent to user {user.telegram_id} at {timezone_str} "
                                    f"Sunday 22:00 (local time: {user_local_time.strftime('%Y-%m-%d %H:%M')})"
                                )
                    except (ValueError, pytz.exceptions.UnknownTimeZoneError) as tz_error:
                        logger.warning(f"Invalid timezone for user {user.telegram_id} ({timezone_str}): {tz_error}")
                        
                except Exception as e:
                    logger.error(f"Error checking weekly report for user {user.telegram_id}: {e}", exc_info=True)
            
            if sent_count > 0:
                logger.info(f"Sent {sent_count} weekly reports")
            
    except Exception as e:
        logger.critical(f"Critical error in check_and_send_weekly_reports: {e}", exc_info=True)
        await send_error_to_admins("Critical error in check_and_send_weekly_reports", str(e))


async def check_and_send_monthly_reports(bot: Bot):
    """Проверить и отправить месячные отчёты пользователям в их персональное время (последний день месяца в 22:00)"""
    logger.debug("Checking users for monthly reports based on personal timezone")
    
    try:
        from services.reports import get_monthly_report, format_monthly_report_text
        from database.db import AsyncSessionLocal
        from database.models import User
        from sqlalchemy import select
        from datetime import datetime, timedelta
        from config import settings
        import pytz
        import calendar
    
        # Текущее время в Москве (базовое время для проекта)
        moscow_tz = pytz.timezone(settings.DEFAULT_TIMEZONE)
        now_moscow = datetime.now(moscow_tz)
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.onboarding_completed == True)
            )
            users = result.scalars().all()
            
            sent_count = 0
            for user in users:
                try:
                    # Получаем настройки времени пользователя (по умолчанию московское время)
                    timezone_str = user.timezone or settings.DEFAULT_TIMEZONE
                    
                    try:
                        # Преобразуем время пользователя из московского в его локальное время
                        user_tz = pytz.timezone(timezone_str)
                        user_local_time = now_moscow.astimezone(user_tz)
                        
                        # Проверяем, наступило ли время месячного отчета (последний день месяца в 22:00)
                        # Проверяем каждые 15 минут: отправляем в окне 22:00-22:14
                        current_date = user_local_time.date()
                        current_hour = user_local_time.hour
                        current_minute = user_local_time.minute
                        
                        # Определяем последний день месяца
                        last_day = calendar.monthrange(current_date.year, current_date.month)[1]
                        is_last_day = current_date.day == last_day
                        
                        if is_last_day and current_hour == 22 and 0 <= current_minute < 15:
                            # Получаем статистику за месяц
                            stats = await get_monthly_report(session, user.id)
                            
                            # Отправляем только если есть данные
                            if stats.get("morning_count", 0) > 0 or stats.get("evening_count", 0) > 0:
                                report_text = format_monthly_report_text(stats)
                                
                                await bot.send_message(
                                    chat_id=user.telegram_id,
                                    text=report_text
                                )
                                sent_count += 1
                                logger.info(
                                    f"Monthly report sent to user {user.telegram_id} at {timezone_str} "
                                    f"last day 22:00 (local time: {user_local_time.strftime('%Y-%m-%d %H:%M')})"
                                )
                    except (ValueError, pytz.exceptions.UnknownTimeZoneError) as tz_error:
                        logger.warning(f"Invalid timezone for user {user.telegram_id} ({timezone_str}): {tz_error}")
                        
                except Exception as e:
                    logger.error(f"Error checking monthly report for user {user.telegram_id}: {e}", exc_info=True)
            
            if sent_count > 0:
                logger.info(f"Sent {sent_count} monthly reports")
            
    except Exception as e:
        logger.critical(f"Critical error in check_and_send_monthly_reports: {e}", exc_info=True)
        await send_error_to_admins("Critical error in check_and_send_monthly_reports", str(e))


# Обработчик необработанных ошибок
async def error_handler(event) -> bool:
    """Обработчик глобальных ошибок с подробным логированием для aiogram 3.4"""
    from aiogram.types import ErrorEvent
    
    try:
        # В aiogram 3.4 event это ErrorEvent, который содержит update и exception
        if isinstance(event, ErrorEvent):
            update = event.update
            exception = event.exception
        else:
            # Fallback для совместимости
            update = getattr(event, 'update', None)
            exception = getattr(event, 'exception', None)
            if exception is None:
                exception = Exception("Unknown error")
        
        error_msg = str(exception)
        
        # Получаем traceback безопасно
        try:
            import sys
            import traceback
            error_details = ''.join(traceback.format_exception(type(exception), exception, exception.__traceback__))
        except Exception:
            error_details = f"Error type: {type(exception).__name__}, Message: {error_msg}"
        
        # Формируем информацию об update для контекста
        update_info = ""
        try:
            if update:
                if hasattr(update, 'message') and update.message:
                    user = update.message.from_user
                    username = getattr(user, 'username', None) or 'no username'
                    update_info = f"Message from user {user.id} (@{username})"
                    if hasattr(update.message, 'text') and update.message.text:
                        update_info += f", text: {update.message.text[:50]}"
                elif hasattr(update, 'callback_query') and update.callback_query:
                    user = update.callback_query.from_user
                    username = getattr(user, 'username', None) or 'no username'
                    callback_data = getattr(update.callback_query, 'data', None) or "[no data]"
                    update_info = f"Callback from user {user.id} (@{username}), data: {callback_data}"
        except Exception as e:
            update_info = f"Error extracting update info: {e}"
        
        # Логируем ошибку с правильным уровнем ERROR
        logger.error(
            f"❌ Unhandled error occurred: {error_msg} | Context: {update_info}",
            exc_info=exception
        )
        
        # Отправляем админам с полной информацией (в try-except, чтобы не создать рекурсию)
        try:
            await send_error_to_admins(error_msg, error_details, update_info)
        except Exception as admin_error:
            logger.error(f"Failed to send error to admins: {admin_error}", exc_info=True)
        
        # Пытаемся отправить сообщение пользователю, если есть update
        if update:
            try:
                bot = _bot_instance
                if bot:
                    if hasattr(update, 'message') and update.message:
                        await bot.send_message(
                            chat_id=update.message.chat.id,
                            text="❌ Произошла ошибка при обработке вашего запроса. "
                                 "Мы уже получили уведомление и исправим проблему."
                        )
                        logger.debug(f"Error notification sent to user {update.message.from_user.id}")
                    elif hasattr(update, 'callback_query') and update.callback_query:
                        await bot.answer_callback_query(
                            callback_query_id=update.callback_query.id,
                            text="Произошла ошибка. Мы уже получили уведомление.",
                            show_alert=True
                        )
                        logger.debug(f"Error notification sent to user {update.callback_query.from_user.id}")
            except Exception as user_error:
                logger.warning(f"Could not send error message to user: {user_error}", exc_info=True)
        
        return True
    except Exception as handler_error:
        # Если ошибка в самом error_handler, логируем и не поднимаем дальше
        logger.critical(f"Critical error in error_handler itself: {handler_error}", exc_info=True)
        return True


async def main():
    """Главная функция запуска бота"""
    global _bot_instance
    
    try:
        if not settings.BOT_TOKEN:
            error_msg = "BOT_TOKEN not set in environment variables!"
            logger.critical(error_msg)
            await send_error_to_admins(error_msg)
            sys.exit(1)
        
        logger.info("=" * 60)
        logger.info("Starting Healthy Bot AI...")
        logger.info(f"Debug mode: {settings.DEBUG}")
        logger.info(f"Log level: {settings.LOG_LEVEL}")
        logger.info("=" * 60)
        
        # Инициализация БД
        logger.debug("Initializing database...")
        await init_db()
        logger.info("✅ Database initialized successfully")
        
        # Создаём бота и диспетчер
        logger.debug("Creating bot instance...")
        bot = Bot(
            token=settings.BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        _bot_instance = bot  # Сохраняем для отправки ошибок
        logger.info("✅ Bot instance created")
        
        # Middleware для логирования всех входящих обновлений
        from aiogram import BaseMiddleware
        from aiogram.types import Update, Message, CallbackQuery
        
        class LoggingMiddleware(BaseMiddleware):
            """Middleware для логирования всех входящих обновлений"""
            async def __call__(self, handler, event: Update, data: dict):
                try:
                    if isinstance(event, Update):
                        if event.message:
                            user = event.message.from_user
                            username = user.username if user.username else "без username"
                            text_preview = (event.message.text[:100] if event.message.text else "[no text]")
                            logger.info(
                                f"📨 Message from user {user.id} (@{username}): "
                                f"text='{text_preview}' "
                                f"chat_id={event.message.chat.id}"
                            )
                        elif event.callback_query:
                            user = event.callback_query.from_user
                            username = user.username if user.username else "без username"
                            callback_data = event.callback_query.data or "[no data]"
                            chat_id = event.callback_query.message.chat.id if event.callback_query.message else 'N/A'
                            logger.info(
                                f"🔘 Callback from user {user.id} (@{username}): "
                                f"data='{callback_data}' "
                                f"chat_id={chat_id}"
                            )
                        elif event.edited_message:
                            user = event.edited_message.from_user
                            username = user.username if user.username else "без username"
                            logger.debug(
                                f"✏️ Edited message from user {user.id} (@{username})"
                            )
                    
                    result = await handler(event, data)
                    return result
                except Exception as e:
                    # Если ошибка в middleware, логируем и пробрасываем дальше
                    logger.error(f"Error in LoggingMiddleware: {e}", exc_info=True)
                    raise
        
        dp = Dispatcher()
        dp.update.middleware(LoggingMiddleware())
        logger.debug("Logging middleware registered")
        
        # Регистрируем обработчик ошибок (для aiogram 3.4)
        # В aiogram 3.4 используется декоратор @router.error() или dp.errors.register()
        # Создаём router для ошибок с декоратором
        from aiogram import Router
        from aiogram.types import ErrorEvent
        
        error_router = Router()
        
        @error_router.error()
        async def error_handler_decorated(event: ErrorEvent):
            """Обработчик ошибок через декоратор"""
            return await error_handler(event)
        
        dp.include_router(error_router)
        logger.debug("Error handler registered")
        
        # Регистрируем роутеры (порядок важен!)
        logger.debug("Registering routers...")
        dp.include_router(menu_handlers.router)  # Обработчики текстовых кнопок меню (высокий приоритет)
        logger.debug("  ✓ menu_handlers router")
        dp.include_router(commands.router)
        logger.debug("  ✓ commands router")
        dp.include_router(callbacks.router)
        logger.debug("  ✓ callbacks router")
        dp.include_router(handlers_settings.router)
        logger.debug("  ✓ settings router")
        dp.include_router(messages.router)
        logger.debug("  ✓ messages router")
        logger.info("✅ All routers registered")
        
        # Настраиваем планировщик
        logger.debug("Setting up scheduler...")
        scheduler = setup_scheduler(bot)
        logger.info("✅ Scheduler configured")
        
        logger.info("=" * 60)
        logger.info("🚀 Bot is starting...")
        logger.info("=" * 60)
        
        # Удаляем вебхук и запускаем polling
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook deleted, starting polling...")
        
        await dp.start_polling(bot)
        
    except KeyboardInterrupt:
        logger.warning("Bot stopped by user (KeyboardInterrupt)")
    except Exception as e:
        error_msg = f"Critical error in main(): {str(e)}"
        error_details = traceback.format_exc()
        logger.critical(error_msg, exc_info=e)
        await send_error_to_admins(error_msg, error_details)
        raise
    finally:
        logger.info("Shutting down...")
        if 'scheduler' in locals():
            scheduler.shutdown()
            logger.debug("Scheduler shut down")
        if 'bot' in locals():
            await bot.session.close()
            logger.debug("Bot session closed")
        logger.info("✅ Shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=e)
        sys.exit(1)
