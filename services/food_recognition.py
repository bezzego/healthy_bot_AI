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
    Распознать еду на фото и получить КБЖУ через GPT-4 Vision с разбивкой по ингредиентам
    
    Args:
        image_bytes: Байты изображения
    
    Returns:
        Dict с ключами:
            - food_name: название блюда
            - ingredients: список ингредиентов, каждый с полями:
                - name: название ингредиента
                - calories: калории
                - protein: белки (г)
                - fats: жиры (г)
                - carbs: углеводы (г)
                - amount: примерное количество (опционально)
            - total_calories: общая калорийность (сумма всех ингредиентов)
            - total_protein: общие белки (г)
            - total_fats: общие жиры (г)
            - total_carbs: общие углеводы (г)
            - description: описание блюда (опционально)
            - calories, protein, fats, carbs: для обратной совместимости (дублируют total_*)
    
    Raises:
        Exception: если API недоступен или произошла ошибка
    """
    if not client:
        raise Exception("OpenAI API ключ не настроен. Добавьте OPENAI_API_KEY в .env файл")
    
    # Кодируем изображение в base64
    base64_image = encode_image_to_base64(image_bytes)
    
    # Формируем промпт для GPT-4 Vision
    prompt = """Проанализируй фото еды и определи КБЖУ максимально точно.

Требования:
1. Определи все основные ингредиенты (компоненты) блюда
2. Для КАЖДОГО ингредиента укажи КБЖУ (калории, белки, жиры, углеводы в граммах)
3. Укажи общее КБЖУ всего блюда (сумма всех ингредиентов)
4. Будь максимально точным в расчетах

Ответ дай строго в формате JSON:
{
  "food_name": "название блюда на русском",
  "ingredients": [
    {
      "name": "название ингредиента на русском",
      "calories": число (ккал),
      "protein": число (граммы),
      "fats": число (граммы),
      "carbs": число (граммы),
      "amount": "примерное количество (опционально, например: '150г', '1 шт')"
    }
  ],
  "total_calories": число (общая калорийность всего блюда),
  "total_protein": число (общие белки в граммах),
  "total_fats": число (общие жиры в граммах),
  "total_carbs": число (общие углеводы в граммах),
  "description": "краткое описание блюда (опционально)"
}

Важно:
- Определи ВСЕ основные ингредиенты, которые видны на фото
- Для каждого ингредиента укажи максимально точное КБЖУ
- total_calories, total_protein, total_fats, total_carbs должны быть суммой всех ингредиентов
- Все числа должны быть целыми или с одной десятичной точкой
- Если точно определить нельзя, используй профессиональные базы данных КБЖУ продуктов"""
    
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
            max_tokens=1500,  # Увеличено для детальной разбивки по ингредиентам
            temperature=0.2  # Очень низкая температура для максимальной точности
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
        Dict с данными о еде (старая структура для обратной совместимости)
    """
    result = {
        "food_name": "Неизвестное блюдо",
        "calories": 0,
        "protein": 0,
        "fats": 0,
        "carbs": 0,
        "description": "",
        "ingredients": [],
        "total_calories": 0,
        "total_protein": 0,
        "total_fats": 0,
        "total_carbs": 0
    }
    
    # Пытаемся извлечь название
    name_match = re.search(r'"food_name":\s*"([^"]+)"', text)
    if name_match:
        result["food_name"] = name_match.group(1)
    
    # Пытаемся извлечь общее КБЖУ (приоритет)
    total_calories_match = re.search(r'"total_calories":\s*(\d+\.?\d*)', text)
    if total_calories_match:
        result["total_calories"] = float(total_calories_match.group(1))
        result["calories"] = result["total_calories"]  # Для обратной совместимости
    
    total_protein_match = re.search(r'"total_protein":\s*(\d+\.?\d*)', text)
    if total_protein_match:
        result["total_protein"] = float(total_protein_match.group(1))
        result["protein"] = result["total_protein"]
    
    total_fats_match = re.search(r'"total_fats":\s*(\d+\.?\d*)', text)
    if total_fats_match:
        result["total_fats"] = float(total_fats_match.group(1))
        result["fats"] = result["total_fats"]
    
    total_carbs_match = re.search(r'"total_carbs":\s*(\d+\.?\d*)', text)
    if total_carbs_match:
        result["total_carbs"] = float(total_carbs_match.group(1))
        result["carbs"] = result["total_carbs"]
    
    # Если общее КБЖУ не найдено, пытаемся извлечь старое (обратная совместимость)
    if result["total_calories"] == 0:
        calories_match = re.search(r'"calories":\s*(\d+\.?\d*)', text)
        if calories_match:
            result["calories"] = float(calories_match.group(1))
            result["total_calories"] = result["calories"]
        
        protein_match = re.search(r'"protein":\s*(\d+\.?\d*)', text)
        if protein_match:
            result["protein"] = float(protein_match.group(1))
            result["total_protein"] = result["protein"]
        
        fats_match = re.search(r'"fats":\s*(\d+\.?\d*)', text)
        if fats_match:
            result["fats"] = float(fats_match.group(1))
            result["total_fats"] = result["fats"]
        
        carbs_match = re.search(r'"carbs":\s*(\d+\.?\d*)', text)
        if carbs_match:
            result["carbs"] = float(carbs_match.group(1))
            result["total_carbs"] = result["carbs"]
    
    return result


def validate_and_normalize_result(result: Dict) -> Dict[str, any]:
    """
    Валидация и нормализация результата
    
    Args:
        result: Результат от API
    
    Returns:
        Валидированный и нормализованный результат с ингредиентами
    """
    # Нормализуем ингредиенты
    ingredients = result.get("ingredients", [])
    normalized_ingredients = []
    
    if isinstance(ingredients, list):
        for ing in ingredients:
            if isinstance(ing, dict):
                normalized_ing = {
                    "name": str(ing.get("name", "")).strip(),
                    "calories": max(0, float(ing.get("calories", 0))),
                    "protein": max(0, float(ing.get("protein", 0))),
                    "fats": max(0, float(ing.get("fats", 0))),
                    "carbs": max(0, float(ing.get("carbs", 0))),
                    "amount": str(ing.get("amount", "")).strip() if ing.get("amount") else ""
                }
                if normalized_ing["name"]:  # Только если название не пустое
                    normalized_ingredients.append(normalized_ing)
    
    # Получаем общее КБЖУ (приоритет на total_*, потом на старые поля для обратной совместимости)
    total_calories = float(result.get("total_calories", result.get("calories", 0)))
    total_protein = float(result.get("total_protein", result.get("protein", 0)))
    total_fats = float(result.get("total_fats", result.get("fats", 0)))
    total_carbs = float(result.get("total_carbs", result.get("carbs", 0)))
    
    # Если общее КБЖУ = 0, но есть ингредиенты, суммируем их
    if total_calories == 0 and normalized_ingredients:
        total_calories = sum(ing["calories"] for ing in normalized_ingredients)
        total_protein = sum(ing["protein"] for ing in normalized_ingredients)
        total_fats = sum(ing["fats"] for ing in normalized_ingredients)
        total_carbs = sum(ing["carbs"] for ing in normalized_ingredients)
    
    normalized = {
        "food_name": str(result.get("food_name", "Неизвестное блюдо")).strip(),
        "ingredients": normalized_ingredients,
        "total_calories": max(0, total_calories),
        "total_protein": max(0, total_protein),
        "total_fats": max(0, total_fats),
        "total_carbs": max(0, total_carbs),
        "description": str(result.get("description", "")).strip(),
        # Для обратной совместимости (старые поля)
        "calories": max(0, total_calories),
        "protein": max(0, total_protein),
        "fats": max(0, total_fats),
        "carbs": max(0, total_carbs)
    }
    
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
