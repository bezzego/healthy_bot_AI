"""Модуль для работы с клавиатурами бота"""
from keyboards.main_menu import get_main_menu_keyboard, get_main_menu_inline
from keyboards.admin_menu import get_admin_menu_keyboard, get_admin_panel_inline

__all__ = [
    "get_main_menu_keyboard",
    "get_main_menu_inline",
    "get_admin_menu_keyboard",
    "get_admin_panel_inline",
]
