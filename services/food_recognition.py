"""Сервис для распознавания еды по фото через OpenAI GPT-4 Vision"""
import base64
import json
import re
from typing import Dict, Optional
from io import BytesIO

try:
    from PIL import Image
except ImportError:
    Image = None

from openai import RateLimitError, APITimeoutError
from services.openai_client import get_openai_client
from utils.logger import setup_logger
from config import settings

logger = setup_logger(__name__, settings.LOG_LEVEL, settings.DEBUG)


def compress_image(image_bytes: bytes, max_size: int = 512, quality: int = 70) -> bytes:
    """
    Сжать изображение до указанного размера (JPEG, quality=70)
    
    Args:
        image_bytes: Байты исходного изображения
        max_size: Максимальный размер по большей стороне (по умолчанию 512)
        quality: Качество JPEG (по умолчанию 70)
    
    Returns:
        bytes: Сжатые байты изображения
    """
    if not Image:
        logger.warning("PIL/Pillow не установлен, пропускаем сжатие")
        return image_bytes
    
    try:
        # Открываем изображение
        img = Image.open(BytesIO(image_bytes))
        
        # Конвертируем в RGB если нужно (для JPEG)
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Вычисляем новые размеры с сохранением пропорций
        width, height = img.size
        if width > height:
            if width > max_size:
                new_width = max_size
                new_height = int(height * (max_size / width))
            else:
                new_width, new_height = width, height
        else:
            if height > max_size:
                new_height = max_size
                new_width = int(width * (max_size / height))
            else:
                new_width, new_height = width, height
        
        # Изменяем размер
        if (new_width, new_height) != (width, height):
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            logger.debug(f"Изображение сжато: {width}x{height} -> {new_width}x{new_height}")
        
        # Сохраняем в JPEG с указанным качеством
        output = BytesIO()
        img.save(output, format='JPEG', quality=quality, optimize=True)
        output.seek(0)
        
        compressed_bytes = output.read()
        logger.debug(f"Изображение сжато: {len(image_bytes)} -> {len(compressed_bytes)} байт")
        
        return compressed_bytes
    
    except Exception as e:
        logger.error(f"Ошибка при сжатии изображения: {e}", exc_info=True)
        # В случае ошибки возвращаем исходные байты
        return image_bytes


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
        logger.error(f"Ошибка при загрузке фото из Telegram: {e}", exc_info=True)
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
            - ingredients: список ингредиентов
            - total_calories: общая калорийность
            - total_protein: общие белки (г)
            - total_fats: общие жиры (г)
            - total_carbs: общие углеводы (г)
    
    Raises:
        RateLimitError: при превышении лимита запросов (429)
        Exception: при других ошибках
    """
    client = get_openai_client()
    if not client.client:
        raise Exception("OpenAI API ключ не настроен")
    
    # Сжимаем изображение до 512x512
    compressed_bytes = compress_image(image_bytes, max_size=512, quality=70)
    
    # Кодируем изображение в base64
    base64_image = encode_image_to_base64(compressed_bytes)
    
    # Минимальный prompt, возвращающий только JSON
    prompt = """Определи КБЖУ блюда. Ответ только JSON:
{"food_name":"название","ingredients":[{"name":"ингредиент","calories":число,"protein":число,"fats":число,"carbs":число}],"total_calories":число,"total_protein":число,"total_fats":число,"total_carbs":число}"""
    
    try:
        # Вызываем GPT-4 Vision API через единый клиент
        response = await client.chat_completions_create(
            model="gpt-4o-mini",
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
            max_tokens=300,
            temperature=0.2
        )
        
        # Извлекаем ответ
        content = response.choices[0].message.content
        if not content:
            raise Exception("Пустой ответ от OpenAI API")
        
        # Парсим JSON из ответа
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
            logger.warning(f"Не удалось распарсить JSON, используем fallback: {content_clean[:100]}")
            result = parse_food_data_from_text(content)
        
        # Валидация и нормализация результата
        return validate_and_normalize_result(result)
        
    except RateLimitError as e:
        logger.error(f"RateLimitError при распознавании еды: {e}")
        raise
    except APITimeoutError as e:
        logger.error(f"APITimeoutError при распознавании еды: {e}")
        raise
    except Exception as e:
        logger.error(f"Ошибка при распознавании еды через OpenAI: {e}", exc_info=True)
        raise Exception(f"Ошибка при распознавании еды: {e}")


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
    
    # Пытаемся извлечь общее КБЖУ
    total_calories_match = re.search(r'"total_calories":\s*(\d+\.?\d*)', text)
    if total_calories_match:
        result["total_calories"] = float(total_calories_match.group(1))
        result["calories"] = result["total_calories"]
    
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
        Валидированный и нормализованный результат
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
                if normalized_ing["name"]:
                    normalized_ingredients.append(normalized_ing)
    
    # Получаем общее КБЖУ
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
        # Для обратной совместимости
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
        Dict с данными о еде
    """
    # Скачиваем фото
    image_bytes = await download_photo_from_telegram(bot, file_id)
    
    # Распознаем еду
    result = await recognize_food_from_image(image_bytes)
    
    return result


async def download_voice_from_telegram(bot, file_id: str) -> bytes:
    """
    Скачать голосовое сообщение из Telegram и получить байты
    
    Args:
        bot: Экземпляр бота aiogram
        file_id: ID файла из Telegram
    
    Returns:
        bytes: Байты аудио файла
    """
    try:
        file = await bot.get_file(file_id)
        voice_bytes = BytesIO()
        await bot.download_file(file.file_path, destination=voice_bytes)
        voice_bytes.seek(0)
        return voice_bytes.read()
    except Exception as e:
        logger.error(f"Ошибка при загрузке голосового сообщения из Telegram: {e}", exc_info=True)
        raise Exception(f"Ошибка при загрузке голосового сообщения из Telegram: {e}")


async def transcribe_voice_to_text(bot, file_id: str) -> str:
    """
    Расшифровать голосовое сообщение в текст через OpenAI Whisper
    
    Args:
        bot: Экземпляр бота aiogram
        file_id: ID файла из Telegram
    
    Returns:
        str: Расшифрованный текст
    
    Raises:
        RateLimitError: при превышении лимита запросов (429)
        Exception: при других ошибках
    """
    client = get_openai_client()
    if not client.client:
        raise Exception("OpenAI API ключ не настроен")
    
    try:
        # Скачиваем голосовое сообщение
        voice_bytes = await download_voice_from_telegram(bot, file_id)
        
        # Создаем BytesIO buffer с установленным именем для определения формата
        buffer = BytesIO(voice_bytes)
        buffer.name = "voice.ogg"
        buffer.seek(0)
        
        # Отправляем в Whisper API через единый клиент
        transcript = await client.audio_transcriptions_create(
            model="whisper-1",
            file=buffer,
            language="ru"
        )
        
        return transcript.text.strip()
    except RateLimitError as e:
        logger.error(f"RateLimitError при расшифровке голоса: {e}")
        raise
    except APITimeoutError as e:
        logger.error(f"APITimeoutError при расшифровке голоса: {e}")
        raise
    except Exception as e:
        logger.error(f"Ошибка при расшифровке голосового сообщения через Whisper: {e}", exc_info=True)
        raise Exception(f"Ошибка при расшифровке голосового сообщения: {e}")


async def process_food_correction(
    current_food_data: Dict[str, any],
    correction_text: str
) -> Dict[str, any]:
    """
    Обработать коррекцию информации о еде через OpenAI и обновить данные
    
    Args:
        current_food_data: Текущие данные о еде
        correction_text: Текст коррекции от пользователя
    
    Returns:
        Dict с обновленными данными о еде
    
    Raises:
        RateLimitError: при превышении лимита запросов (429)
        Exception: при других ошибках
    """
    client = get_openai_client()
    if not client.client:
        raise Exception("OpenAI API ключ не настроен")
    
    # Минимальный prompt для коррекции
    current_name = current_food_data.get("food_name", "Неизвестное блюдо")
    current_calories = current_food_data.get("total_calories", 0)
    current_protein = current_food_data.get("total_protein", 0)
    current_fats = current_food_data.get("total_fats", 0)
    current_carbs = current_food_data.get("total_carbs", 0)
    
    prompt = f"""Обнови КБЖУ. Текущее: {current_name}, {current_calories:.0f} ккал, Б:{current_protein:.0f}г, Ж:{current_fats:.0f}г, У:{current_carbs:.0f}г. Коррекция: "{correction_text}". Ответ только JSON:
{{"food_name":"название","ingredients":[{{"name":"ингредиент","calories":число,"protein":число,"fats":число,"carbs":число}}],"total_calories":число,"total_protein":число,"total_fats":число,"total_carbs":число}}"""
    
    try:
        # Вызываем GPT API через единый клиент
        response = await client.chat_completions_create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            max_tokens=300,
            temperature=0.2
        )
        
        # Извлекаем ответ
        content = response.choices[0].message.content
        if not content:
            raise Exception("Пустой ответ от OpenAI API")
        
        # Парсим JSON из ответа
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
            logger.warning(f"Не удалось распарсить JSON при коррекции, используем fallback: {content_clean[:100]}")
            result = parse_food_data_from_text(content)
        
        # Валидация и нормализация результата
        return validate_and_normalize_result(result)
        
    except RateLimitError as e:
        logger.error(f"RateLimitError при обработке коррекции: {e}")
        raise
    except APITimeoutError as e:
        logger.error(f"APITimeoutError при обработке коррекции: {e}")
        raise
    except Exception as e:
        logger.error(f"Ошибка при обработке коррекции через OpenAI: {e}", exc_info=True)
        raise Exception(f"Ошибка при обработке коррекции: {e}")


async def process_food_description_from_text(description_text: str) -> Dict[str, any]:
    """
    Обработать текстовое/голосовое описание еды через OpenAI и определить КБЖУ
    
    Args:
        description_text: Текст описания еды
    
    Returns:
        Dict с данными о еде
    
    Raises:
        RateLimitError: при превышении лимита запросов (429)
        Exception: при других ошибках
    """
    client = get_openai_client()
    if not client.client:
        raise Exception("OpenAI API ключ не настроен")
    
    # Минимальный prompt для текстового описания
    prompt = f"""Определи КБЖУ по описанию: "{description_text}". Ответ только JSON:
{{"food_name":"название","ingredients":[{{"name":"ингредиент","calories":число,"protein":число,"fats":число,"carbs":число}}],"total_calories":число,"total_protein":число,"total_fats":число,"total_carbs":число}}"""
    
    try:
        # Вызываем GPT API через единый клиент
        response = await client.chat_completions_create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            max_tokens=300,
            temperature=0.2
        )
        
        # Извлекаем ответ
        content = response.choices[0].message.content
        if not content:
            raise Exception("Пустой ответ от OpenAI API")
        
        # Парсим JSON из ответа
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
            logger.warning(f"Не удалось распарсить JSON при обработке описания, используем fallback: {content_clean[:100]}")
            result = parse_food_data_from_text(content)
        
        # Валидация и нормализация результата
        return validate_and_normalize_result(result)
        
    except RateLimitError as e:
        logger.error(f"RateLimitError при обработке описания: {e}")
        raise
    except APITimeoutError as e:
        logger.error(f"APITimeoutError при обработке описания: {e}")
        raise
    except Exception as e:
        logger.error(f"Ошибка при обработке описания еды через OpenAI: {e}", exc_info=True)
        raise Exception(f"Ошибка при обработке описания: {e}")
