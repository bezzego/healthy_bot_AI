"""Модели базы данных"""
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database.db import Base


class User(Base):
    """Модель пользователя"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(Integer, unique=True, index=True, nullable=False)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    
    # Статус онбординга
    onboarding_completed = Column(Boolean, default=False)
    onboarding_completed_at = Column(DateTime, nullable=True)
    
    # Дата регистрации
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    # Связи
    questionnaires = relationship("Questionnaire", back_populates="user")
    daily_records = relationship("DailyRecord", back_populates="user")
    nutrition_records = relationship("NutritionRecord", back_populates="user")
    admin_requests = relationship("AdminRequest", back_populates="user")
    monthly_measurements = relationship("MonthlyMeasurement", back_populates="user")
    
    # Состояние для FSM
    current_state = Column(String, nullable=True)
    state_data = Column(JSON, nullable=True)
    
    # Настройки уведомлений
    timezone = Column(String, default="Europe/Moscow")  # Часовой пояс (по умолчанию московское время)
    morning_notification_time = Column(String, default="08:00")  # Время утренних уведомлений
    evening_notification_time = Column(String, default="22:00")  # Время вечерних уведомлений


class Questionnaire(Base):
    """Модель анкеты (первичной и повторной)"""
    __tablename__ = "questionnaires"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Тип анкеты: primary или retest
    type = Column(String, nullable=False, default="primary")
    
    # Пол (определяется первым вопросом)
    gender = Column(String, nullable=True)  # "male" или "female"
    
    # Антропометрия
    height = Column(Float, nullable=True)  # см
    weight = Column(Float, nullable=True)  # кг
    chest_circumference = Column(Float, nullable=True)
    waist_circumference = Column(Float, nullable=True)
    hips_circumference = Column(Float, nullable=True)
    
    # ЖКТ
    stool_frequency = Column(String, nullable=True)
    stool_character = Column(String, nullable=True)
    bloating = Column(Boolean, nullable=True)
    cramps = Column(Boolean, nullable=True)
    gas = Column(Boolean, nullable=True)
    
    # Гормональный / общий фон
    menstrual_cycle = Column(String, nullable=True)
    cold_hands_feet = Column(Boolean, nullable=True)
    skin_itch = Column(Boolean, nullable=True)
    dry_mouth = Column(Boolean, nullable=True)
    hair_loss = Column(Boolean, nullable=True)
    low_libido = Column(Boolean, nullable=True)
    
    # Новые поля по ТЗ
    shortness_of_breath = Column(Boolean, nullable=True)  # Одышка или учащённое сердцебиение
    blue_sclera = Column(Boolean, nullable=True)  # Голубоватый оттенок склер
    oily_skin = Column(Boolean, nullable=True)  # Жирность кожи лица
    dry_skin = Column(Boolean, nullable=True)  # Сухость кожи лица
    vaginal_itch = Column(Boolean, nullable=True)  # Вагинальный зуд (для женщин)
    joint_pain = Column(Boolean, nullable=True)  # Боли в суставах
    abdominal_cramps = Column(Boolean, nullable=True)  # Боли или спазмы в животе
    
    # Самочувствие (шкала 1-5)
    energy_level = Column(Integer, nullable=True)  # 1-5
    stress_level = Column(Integer, nullable=True)  # 1-5
    sleep_quality = Column(Integer, nullable=True)  # 1-5
    concentration = Column(Boolean, nullable=True)  # снижение концентрации
    irritability = Column(Boolean, nullable=True)  # дневная раздражительность
    sleepiness = Column(Boolean, nullable=True)  # дневная сонливость
    headaches = Column(Boolean, nullable=True)
    # Удалён headache_frequency
    
    # Аппетит и тяги
    appetite = Column(String, nullable=True)  # normal/increased/decreased
    sugar_craving = Column(Boolean, nullable=True)
    fat_craving = Column(Boolean, nullable=True)
    
    # Физическая активность
    average_steps = Column(Integer, nullable=True)
    additional_activity_frequency = Column(String, nullable=True)
    
    # Рассчитанные показатели
    bmi = Column(Float, nullable=True)
    health_score = Column(Float, nullable=True)  # 0-10
    general_score = Column(Float, nullable=True)  # 0-100
    
    # Рекомендации
    recommended_calories = Column(Integer, nullable=True)
    recommended_protein = Column(Float, nullable=True)
    recommended_fats = Column(Float, nullable=True)
    recommended_carbs = Column(Float, nullable=True)
    recommended_water = Column(Float, nullable=True)  # литры
    
    created_at = Column(DateTime, server_default=func.now())
    
    # Связи
    user = relationship("User", back_populates="questionnaires")


class DailyRecord(Base):
    """Модель ежедневных записей"""
    __tablename__ = "daily_records"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date = Column(DateTime, nullable=False, index=True)
    
    # Утренние показатели
    morning_sleep_quality = Column(String, nullable=True)  # Варианты: "Почти не спала", "Просыпалась 2+ раза", "Проснулась 1 раз", "Спала отлично"
    morning_energy = Column(Integer, nullable=True)  # 1-5
    
    # Вечерние показатели
    evening_mood = Column(String, nullable=True)  # Варианты: "Раздражение", "Усталость", "Спокойно", "Хорошее настроение", "Отличное настроение"
    daily_steps = Column(Integer, nullable=True)
    physical_activity = Column(Boolean, nullable=True)
    evening_stool = Column(String, nullable=True)  # Варианты: "Да, нормальный", "Да, плотный", "Да, жидкий", "Да, жидкий более 2 раз", "Нет"
    
    # Питание за день
    total_calories = Column(Float, default=0)
    total_protein = Column(Float, default=0)
    total_fats = Column(Float, default=0)
    total_carbs = Column(Float, default=0)
    total_fiber = Column(Float, default=0)
    
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    # Связи
    user = relationship("User", back_populates="daily_records")


class NutritionRecord(Base):
    """Модель записи о питании"""
    __tablename__ = "nutrition_records"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    daily_record_id = Column(Integer, ForeignKey("daily_records.id"), nullable=True)
    
    # Данные о блюде
    food_name = Column(String, nullable=False)
    photo_file_id = Column(String, nullable=True)
    calories = Column(Float, nullable=False)
    protein = Column(Float, default=0)
    fats = Column(Float, default=0)
    carbs = Column(Float, default=0)
    fiber = Column(Float, default=0)
    
    # Время приёма пищи
    meal_time = Column(DateTime, nullable=False, server_default=func.now())
    
    created_at = Column(DateTime, server_default=func.now())
    
    # Связи
    user = relationship("User", back_populates="nutrition_records")


class AdminRequest(Base):
    """Модель обращений к администратору"""
    __tablename__ = "admin_requests"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Тип обращения
    request_type = Column(String, nullable=False)  # complaint/contact/recipe/results
    
    # Данные обращения
    title = Column(String, nullable=True)
    message = Column(Text, nullable=True)
    
    # Для рецепта
    recipe_composition = Column(Text, nullable=True)
    recipe_photo_file_id = Column(String, nullable=True)
    recipe_description = Column(Text, nullable=True)
    
    # Для результатов
    results_before_photo_file_id = Column(String, nullable=True)
    results_after_photo_file_id = Column(String, nullable=True)
    results_age = Column(Integer, nullable=True)
    results_height = Column(Float, nullable=True)
    results_weight_before = Column(Float, nullable=True)
    results_weight_after = Column(Float, nullable=True)
    results_weight_before_date = Column(DateTime, nullable=True)
    results_weight_after_date = Column(DateTime, nullable=True)
    results_comment = Column(Text, nullable=True)
    
    # Статус
    status = Column(String, default="pending")  # pending/in_progress/resolved
    admin_response = Column(Text, nullable=True)
    
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    # Связи
    user = relationship("User", back_populates="admin_requests")


class MonthlyMeasurement(Base):
    """Модель ежемесячных замеров (вес и обхваты)"""
    __tablename__ = "monthly_measurements"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Дата замера (месяц и год)
    measurement_date = Column(DateTime, nullable=False, index=True)  # Первый день месяца
    
    # Вес и замеры
    weight = Column(Float, nullable=True)  # кг
    waist_circumference = Column(Float, nullable=True)  # обхват талии (см)
    hips_circumference = Column(Float, nullable=True)  # обхват бедер (см)
    chest_circumference = Column(Float, nullable=True)  # обхват груди (см)
    
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    # Связи
    user = relationship("User", back_populates="monthly_measurements")
