"""Подключение к базе данных"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from config import settings
import os

# Создаём директорию для БД если её нет
os.makedirs(os.path.dirname(settings.DATABASE_URL.replace("sqlite+aiosqlite:///", "")), exist_ok=True)

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    future=True
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

Base = declarative_base()


async def get_db() -> AsyncSession:
    """Получить сессию БД"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """Инициализировать БД (создать таблицы и применить миграции)"""
    from database.models import User, Questionnaire, DailyRecord, NutritionRecord, AdminRequest, MonthlyMeasurement
    from sqlalchemy import inspect, text
    
    async with engine.begin() as conn:
        # Создаем все таблицы
        await conn.run_sync(Base.metadata.create_all)
        
        # Применяем миграции для существующих таблиц
        def check_and_migrate(connection):
            inspector = inspect(connection)
            if 'daily_records' in inspector.get_table_names():
                columns = [col['name'] for col in inspector.get_columns('daily_records')]
                
                # Миграция для morning_sleep_hours
                if 'morning_sleep_hours' not in columns:
                    try:
                        connection.execute(text("ALTER TABLE daily_records ADD COLUMN morning_sleep_hours INTEGER"))
                    except Exception:
                        pass
                
                # Миграция для activity_type
                if 'activity_type' not in columns:
                    try:
                        connection.execute(text("ALTER TABLE daily_records ADD COLUMN activity_type VARCHAR"))
                    except Exception:
                        pass
                
                # Миграция для active_calories
                if 'active_calories' not in columns:
                    try:
                        connection.execute(text("ALTER TABLE daily_records ADD COLUMN active_calories FLOAT DEFAULT 0"))
                    except Exception:
                        pass
                
                # Миграция для water_intake
                if 'water_intake' not in columns:
                    try:
                        connection.execute(text("ALTER TABLE daily_records ADD COLUMN water_intake FLOAT DEFAULT 0"))
                    except Exception:
                        pass
        
        await conn.run_sync(check_and_migrate)
