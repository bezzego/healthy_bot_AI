"""Утилита для подробного логирования"""
import logging
import sys
from datetime import datetime
from pathlib import Path


class ColoredFormatter(logging.Formatter):
    """Цветной форматтер для логов с подробной информацией"""
    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Green
        'WARNING': '\033[33m',    # Yellow
        'ERROR': '\033[31m',      # Red
        'CRITICAL': '\033[35m',   # Magenta
    }
    RESET = '\033[0m'
    BOLD = '\033[1m'
    
    def format(self, record):
        # Делаем копию record, чтобы не менять оригинал для других handlers
        record_copy = logging.makeLogRecord(record.__dict__)
        
        # Цвет для уровня
        log_color = self.COLORS.get(record_copy.levelname, self.RESET)
        record_copy.levelname = f"{log_color}{self.BOLD}{record_copy.levelname:8}{self.RESET}"
        
        # Цвет для имени модуля
        record_copy.name = f"\033[34m{record_copy.name}{self.RESET}"  # Blue
        
        # Цвет для функции и строки
        if hasattr(record_copy, 'funcName') and hasattr(record_copy, 'lineno'):
            record_copy.location = f"\033[37m{record_copy.funcName}:{record_copy.lineno}{self.RESET}"  # White
        else:
            record_copy.location = ""
        
        # Детальный формат
        format_str = (
            f'%(asctime)s | '
            f'%(name)-20s | '
            f'%(levelname)s | '
            f'%(location)-25s | '
            f'%(message)s'
        )
        
        formatter = logging.Formatter(format_str, datefmt='%Y-%m-%d %H:%M:%S')
        return formatter.format(record_copy)


class PlainFormatter(logging.Formatter):
    """Простой форматтер для файлов без цветов"""
    def __init__(self):
        super().__init__(
            '%(asctime)s | %(name)-20s | %(levelname)-8s | %(funcName)s:%(lineno)-5d | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )


def setup_logger(name: str = None, level: str = "INFO", debug: bool = False) -> logging.Logger:
    """Настроить подробный логгер с цветным выводом в консоль и простым в файл"""
    logger = logging.getLogger(name or __name__)
    
    # Убираем дублирование
    logger.handlers.clear()
    logger.propagate = False
    
    # Устанавливаем уровень
    log_level = logging.DEBUG if debug else getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(logging.DEBUG)  # Всегда DEBUG для корневого логгера, фильтрация на handlers
    
    # Консольный handler с цветным форматированием
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(ColoredFormatter())
    console_handler.setLevel(log_level)  # Фильтруем по уровню
    logger.addHandler(console_handler)
    
    # Файловый handler для сохранения логов (без цветных кодов)
    try:
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        
        file_handler = logging.FileHandler(
            log_dir / f"bot_{datetime.now().strftime('%Y%m%d')}.log",
            encoding='utf-8'
        )
        file_handler.setFormatter(PlainFormatter())
        file_handler.setLevel(logging.DEBUG)  # Все логи в файл
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"Warning: Could not setup file logging: {e}")
    
    return logger
