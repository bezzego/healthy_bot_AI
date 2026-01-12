"""Конфигурация приложения"""
import os
from typing import List
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    """Настройки приложения"""
    
    # Telegram Bot
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/healthy_bot.db")
    
    # Admin IDs (через запятую)
    ADMIN_USER_IDS: str = os.getenv("ADMIN_USER_IDS", "")
    
    # Scheduling
    WATER_REMINDER_HOURS: str = os.getenv("WATER_REMINDER_HOURS", "11,15")  # 11:30 и 15:30
    EVENING_REPORT_HOUR: int = int(os.getenv("EVENING_REPORT_HOUR", "22"))
    MORNING_GREETING_HOUR: int = int(os.getenv("MORNING_GREETING_HOUR", "8"))
    
    # Settings
    DEBUG: bool = os.getenv("DEBUG", "False").lower() == "true"
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    
    # Timezone для всего проекта (московское время)
    DEFAULT_TIMEZONE: str = "Europe/Moscow"
    
    # OpenAI API для распознавания еды
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    
    # Группа для проверки подписки (обязательная подписка)
    REQUIRED_GROUP_ID: int = int(os.getenv("REQUIRED_GROUP_ID", "-1003681799465"))
    
    @property
    def admin_ids(self) -> List[int]:
        """Получить список ID администраторов"""
        if not self.ADMIN_USER_IDS:
            return []
        return [int(uid.strip()) for uid in self.ADMIN_USER_IDS.split(",") if uid.strip()]
    
    @property
    def water_reminder_hours_list(self) -> List[int]:
        """Получить список часов для напоминаний о воде"""
        return [int(h.strip()) for h in self.WATER_REMINDER_HOURS.split(",") if h.strip()]


settings = Settings()
