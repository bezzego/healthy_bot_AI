"""Сервис для распознавания еды по фото через OpenAI GPT-4 Vision"""
import base64
import json
import re
from typing import Dict, Optional, Tuple
from io import BytesIO

try:
    from openai import AsyncOpenAI
except ImportError:
    AsyncOpenAI = None

from config import settings

# Инициализация клиента OpenAI
client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY) if settings.OPENAI_API_KEY else None


async def download_photo_from_telegram(bot, file_id: str) -> bytes:
    """
    Скачать фото из Telegram и получить байты
    
    Args:
        bot: Экземпляр бота aiogram
        file_id: ID файла из Telegram
    
    Returns:
        bytes: Байты изображения
    """
    try:
        file = await bot.get_file(file_id)
        photo_bytes = BytesIO()
        await bot.download_file(file.file_path, destination=photo_bytes)
        photo_bytes.seek(0)
        return photo_bytes.read()
    except Exception as e:
        raise Exception(f"Ошибка при загрузке фото из Telegram: {e}")


def encode_image_to_base64(image_bytes: bytes) -> str:
    """
    Кодировать изображение в base64 для OpenAI API
    
    Args:
        image_bytes: Байты изображения
    
    Returns:
        str: Base64 строка
    """
    return base64.b64encode(image_bytes).decode('utf-8')


async def recognize_food_from_image(image_bytes: bytes) -> Dict[str, any]:
    """
    Распознать еду на фото и получить КБЖУ через GPT-4 Vision
    
    Args:
        image_bytes: Байты изображения
    
    Returns:
        Dict с ключами:
            - food_name: название блюда
            - calories: калории
            - protein: белки (г)
            - fats: жиры (г)
            - carbs: углеводы (г)
            - description: описание блюда (опционально)
    
    Raises:
        Exception: если API недоступен или произошла ошибка
    """
    if not client:
        raise Exception("OpenAI API ключ не настроен. Добавьте OPENAI_API_KEY в .env файл")
    
    # Кодируем изображение в base64
    base64_image = encode_image_to_base64(image_bytes)
    
    # Формируем промпт для GPT-4 Vision
    prompt = """Проанализируй фото еды и определи:
1. Название блюда (на русском языке)
2. Приблизительное количество калорий (ккал)
3. Белки (граммы)
4. Жиры (граммы)
5. Углеводы (граммы)

Ответ дай строго в формате JSON:
{
  "food_name": "название блюда",
  "calories": число,
  "protein": число,
  "fats": число,
  "carbs": число,
  "description": "краткое описание блюда (опционально)"
}

Важно: если точно определить нельзя, дай приблизительную оценку на основе похожих блюд.
Все числа должны быть целыми или с одной десятичной точкой."""
    
    try:
        # Вызываем GPT-4 Vision API
        response = await client.chat.completions.create(
            model="gpt-4o-mini",  # Используем более дешевую модель
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=500,
            temperature=0.3  # Низкая температура для более точных результатов
        )
        
        # Извлекаем ответ
        content = response.choices[0].message.content
        if not content:
            raise Exception("Пустой ответ от OpenAI API")
        
        # Парсим JSON из ответа
        # GPT может добавить markdown форматирование, убираем его
        content_clean = content.strip()
        if content_clean.startswith("```json"):
            content_clean = content_clean[7:]
        if content_clean.startswith("```"):
            content_clean = content_clean[3:]
        if content_clean.endswith("```"):
            content_clean = content_clean[:-3]
        content_clean = content_clean.strip()
        
        # Парсим JSON
        try:
            result = json.loads(content_clean)
        except json.JSONDecodeError:
            # Если JSON не распарсился, пытаемся извлечь данные через regex
            result = parse_food_data_from_text(content)
        
        # Валидация и нормализация результата
        return validate_and_normalize_result(result)
        
    except Exception as e:
        raise Exception(f"Ошибка при распознавании еды через OpenAI: {e}")


def parse_food_data_from_text(text: str) -> Dict[str, any]:
    """
    Парсить данные о еде из текстового ответа (fallback метод)
    
    Args:
        text: Текст ответа от GPT
    
    Returns:
        Dict с данными о еде
    """
    result = {
        "food_name": "Неизвестное блюдо",
        "calories": 0,
        "protein": 0,
        "fats": 0,
        "carbs": 0,
        "description": ""
    }
    
    # Пытаемся извлечь название
    name_match = re.search(r'"food_name":\s*"([^"]+)"', text)
    if name_match:
        result["food_name"] = name_match.group(1)
    
    # Пытаемся извлечь калории
    calories_match = re.search(r'"calories":\s*(\d+\.?\d*)', text)
    if calories_match:
        result["calories"] = float(calories_match.group(1))
    
    # Пытаемся извлечь белки
    protein_match = re.search(r'"protein":\s*(\d+\.?\d*)', text)
    if protein_match:
        result["protein"] = float(protein_match.group(1))
    
    # Пытаемся извлечь жиры
    fats_match = re.search(r'"fats":\s*(\d+\.?\d*)', text)
    if fats_match:
        result["fats"] = float(fats_match.group(1))
    
    # Пытаемся извлечь углеводы
    carbs_match = re.search(r'"carbs":\s*(\d+\.?\d*)', text)
    if carbs_match:
        result["carbs"] = float(carbs_match.group(1))
    
    return result


def validate_and_normalize_result(result: Dict) -> Dict[str, any]:
    """
    Валидация и нормализация результата
    
    Args:
        result: Результат от API
    
    Returns:
        Валидированный и нормализованный результат
    """
    normalized = {
        "food_name": str(result.get("food_name", "Неизвестное блюдо")).strip(),
        "calories": float(result.get("calories", 0)),
        "protein": float(result.get("protein", 0)),
        "fats": float(result.get("fats", 0)),
        "carbs": float(result.get("carbs", 0)),
        "description": str(result.get("description", "")).strip()
    }
    
    # Проверяем, что все значения валидны
    if normalized["calories"] < 0:
        normalized["calories"] = 0
    if normalized["protein"] < 0:
        normalized["protein"] = 0
    if normalized["fats"] < 0:
        normalized["fats"] = 0
    if normalized["carbs"] < 0:
        normalized["carbs"] = 0
    
    # Если название пустое, используем дефолтное
    if not normalized["food_name"]:
        normalized["food_name"] = "Неизвестное блюдо"
    
    return normalized


async def recognize_food_from_telegram_photo(bot, file_id: str) -> Dict[str, any]:
    """
    Распознать еду по фото из Telegram (полная цепочка)
    
    Args:
        bot: Экземпляр бота aiogram
        file_id: ID файла из Telegram
    
    Returns:
        Dict с данными о еде (food_name, calories, protein, fats, carbs)
    """
    # Скачиваем фото
    image_bytes = await download_photo_from_telegram(bot, file_id)
    
    # Распознаем еду
    result = await recognize_food_from_image(image_bytes)
    
    return result
