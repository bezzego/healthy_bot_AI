"""Конфигурация приложения"""
import os
from typing import List
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    """Настройки приложения"""
    
    # Telegram Bot
    BOT_TOKEN: str = ""
    
    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/healthy_bot.db"
    
    # Admin IDs (через запятую)
    ADMIN_USER_IDS: str = ""
    
    # Scheduling
    WATER_REMINDER_HOURS: str = "11,15"  # 11:30 и 15:30
    EVENING_REPORT_HOUR: int = 22
    MORNING_GREETING_HOUR: int = 8
    
    # Settings
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    
    # Timezone для всего проекта (московское время)
    DEFAULT_TIMEZONE: str = "Europe/Moscow"
    
    # OpenAI API для распознавания еды
    OPENAI_API_KEY: str = ""
    # Прокси для OpenAI API (для работы из России)
    # Формат: http://user:pass@host:port или http://host:port
    OPENAI_PROXY: str = ""
    
    # Группа для проверки подписки (обязательная подписка)
    REQUIRED_GROUP_ID: int = -1003681799465
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
    
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
