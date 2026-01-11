"""Главное меню бота"""
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from services.admin import is_admin


def get_main_menu_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    """
    Получить постоянную клавиатуру главного меню
    Кнопка админ-панели показывается только администраторам
    """
    keyboard = [
        [
            KeyboardButton(text="📊 Статистика"),
            KeyboardButton(text="🍽️ Питание сегодня"),
        ],
        [
            KeyboardButton(text="📸 Добавить еду"),
            KeyboardButton(text="🔄 Повторное тестирование"),
        ],
        [
            KeyboardButton(text="👨‍💼 Связаться с админом"),
        ],
    ]
    
    # Добавляем кнопку админ-панели только для администраторов
    if is_admin(user_id):
        keyboard.append([
            KeyboardButton(text="⚙️ Админ-панель"),
        ])
    
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        input_field_placeholder="Выберите действие из меню"
    )


def get_main_menu_inline(user_id: int) -> InlineKeyboardMarkup:
    """
    Получить inline клавиатуру главного меню (для callback-обработки)
    Используется, когда нужна inline-клавиатура вместо постоянной
    """
    keyboard = [
        [InlineKeyboardButton(text="📊 Статистика", callback_data="statistics")],
        [InlineKeyboardButton(text="🍽️ Питание сегодня", callback_data="nutrition_today")],
        [InlineKeyboardButton(text="📸 Добавить фото еды", callback_data="add_food_photo")],
        [InlineKeyboardButton(text="🔄 Повторное тестирование", callback_data="retest")],
        [InlineKeyboardButton(text="👨‍💼 Связаться с администратором", callback_data="contact_admin")],
    ]
    
    # Добавляем кнопку админ-панели только для администраторов
    if is_admin(user_id):
        keyboard.append([InlineKeyboardButton(text="⚙️ Админ-панель", callback_data="admin_panel")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
