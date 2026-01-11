"""Админ-панель бота"""
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton


def get_admin_menu_keyboard() -> ReplyKeyboardMarkup:
    """Получить постоянную клавиатуру админ-панели"""
    keyboard = [
        [
            KeyboardButton(text="📊 Статистика пользователей"),
            KeyboardButton(text="📝 Заявки"),
        ],
        [
            KeyboardButton(text="◀️ Назад в меню"),
        ],
    ]
    
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        input_field_placeholder="Выберите действие админ-панели"
    )


def get_admin_panel_inline() -> InlineKeyboardMarkup:
    """Получить inline клавиатуру админ-панели"""
    keyboard = [
        [InlineKeyboardButton(text="📊 Статистика пользователей", callback_data="admin_statistics")],
        [InlineKeyboardButton(text="📝 Заявки пользователей", callback_data="admin_requests")],
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="menu_back")],
    ]
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
