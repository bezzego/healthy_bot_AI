"""Единый клиент OpenAI с антибан-защитой"""
import asyncio
import time
from typing import Optional
from openai import AsyncOpenAI
from openai import RateLimitError, APITimeoutError
import httpx
from utils.logger import setup_logger
from config import settings

logger = setup_logger(__name__, settings.LOG_LEVEL, settings.DEBUG)

# Глобальный семафор для ограничения параллелизма (максимум 3 одновременных запроса)
_openai_semaphore = asyncio.Semaphore(3)

# Глобальный rate limiter (не чаще 1 раза в 10 секунд)
_last_request_time: float = 0
_rate_limit_interval = 10.0  # секунд


class OpenAIClient:
    """Единый клиент OpenAI с защитой от бана"""
    
    def __init__(self):
        self._client: Optional[AsyncOpenAI] = None
        self._init_client()
    
    def _init_client(self):
        """Инициализация клиента OpenAI с прокси"""
        api_key = settings.OPENAI_API_KEY
        
        # Детальное логирование для отладки
        if api_key:
            logger.info(f"OPENAI_API_KEY найден: длина={len(api_key)}, начало={api_key[:10]}...")
        else:
            logger.warning("OPENAI_API_KEY не найден в settings")
            # Дополнительная проверка через os.getenv напрямую
            import os
            direct_key = os.getenv("OPENAI_API_KEY", "")
            if direct_key:
                logger.warning(f"Но OPENAI_API_KEY найден через os.getenv: длина={len(direct_key)}, начало={direct_key[:10]}...")
                logger.warning("Возможно, проблема в загрузке через pydantic-settings")
            self._client = None
            return
        
        if not api_key.strip():
            logger.warning(f"OPENAI_API_KEY пустой после strip()")
            self._client = None
            return
        
        # Проверка минимальной длины ключа (обычно OpenAI ключи длиннее 20 символов)
        if len(api_key.strip()) < 20:
            logger.warning(f"OPENAI_API_KEY слишком короткий (длина={len(api_key.strip())}). Возможно, это не полный ключ.")
            # Не блокируем, но предупреждаем
        
        try:
            # Создаем httpx клиент с прокси
            http_client = None
            if settings.OPENAI_PROXY:
                http_client = httpx.AsyncClient(
                    proxy=settings.OPENAI_PROXY,
                    timeout=httpx.Timeout(60.0, connect=10.0),
                    limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
                )
                logger.info("OpenAI клиент создан с прокси")
            else:
                http_client = httpx.AsyncClient(
                    timeout=httpx.Timeout(60.0, connect=10.0),
                    limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
                )
                logger.info("OpenAI клиент создан без прокси")
            
            self._client = AsyncOpenAI(
                api_key=settings.OPENAI_API_KEY,
                http_client=http_client
            )
        except Exception as e:
            logger.error(f"Ошибка инициализации OpenAI клиента: {e}", exc_info=True)
            self._client = None
    
    @property
    def client(self) -> Optional[AsyncOpenAI]:
        """Получить клиент OpenAI"""
        return self._client
    
    async def _wait_for_rate_limit(self):
        """Ожидание перед запросом (не чаще 1 раза в 10 секунд)"""
        global _last_request_time
        current_time = time.time()
        time_since_last = current_time - _last_request_time
        
        if time_since_last < _rate_limit_interval:
            wait_time = _rate_limit_interval - time_since_last
            logger.debug(f"Rate limit: ожидание {wait_time:.2f} сек")
            await asyncio.sleep(wait_time)
        
        _last_request_time = time.time()
    
    async def _call_with_retry(self, func, *args, max_retries=3, **kwargs):
        """Вызов функции с exponential backoff при ошибках"""
        last_exception = None
        
        for attempt in range(max_retries):
            try:
                # Ожидание rate limit
                await self._wait_for_rate_limit()
                
                # Ожидание семафора (лимит параллелизма)
                async with _openai_semaphore:
                    return await func(*args, **kwargs)
            
            except RateLimitError as e:
                last_exception = e
                wait_time = (2 ** attempt) + (attempt * 0.5)  # Exponential backoff: 1s, 2.5s, 5s
                logger.warning(
                    f"RateLimitError (попытка {attempt + 1}/{max_retries}): "
                    f"ожидание {wait_time:.2f} сек"
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"RateLimitError после {max_retries} попыток: {e}")
                    raise
            
            except APITimeoutError as e:
                last_exception = e
                wait_time = (2 ** attempt) + (attempt * 0.5)
                logger.warning(
                    f"APITimeoutError (попытка {attempt + 1}/{max_retries}): "
                    f"ожидание {wait_time:.2f} сек"
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"APITimeoutError после {max_retries} попыток: {e}")
                    raise
            
            except Exception as e:
                # Для других ошибок логируем и пробрасываем сразу
                logger.error(f"Ошибка OpenAI API: {e}", exc_info=True)
                raise
        
        # Если все попытки исчерпаны
        if last_exception:
            raise last_exception
    
    async def chat_completions_create(self, *args, **kwargs):
        """Создание chat completion с retry логикой"""
        if not self._client:
            raise Exception("OpenAI API ключ не настроен")
        
        return await self._call_with_retry(
            self._client.chat.completions.create,
            *args,
            **kwargs
        )
    
    async def audio_transcriptions_create(self, *args, **kwargs):
        """Создание transcription с retry логикой"""
        if not self._client:
            raise Exception("OpenAI API ключ не настроен")
        
        return await self._call_with_retry(
            self._client.audio.transcriptions.create,
            *args,
            **kwargs
        )
    
    async def close(self):
        """Закрыть клиент"""
        if self._client and hasattr(self._client, '_client'):
            http_client = getattr(self._client, '_client', None)
            if http_client and hasattr(http_client, 'aclose'):
                await http_client.aclose()


# Глобальный экземпляр клиента
_openai_client_instance: Optional[OpenAIClient] = None


def get_openai_client() -> OpenAIClient:
    """Получить глобальный экземпляр клиента OpenAI"""
    global _openai_client_instance
    if _openai_client_instance is None:
        _openai_client_instance = OpenAIClient()
    return _openai_client_instance
