# Настройка прокси для OpenAI API

Для работы OpenAI API из России необходимо настроить прокси-сервер.

## Настройка

1. Добавьте в файл `.env` переменную `OPENAI_PROXY`:

```env
OPENAI_PROXY=http://user:password@proxy-server.com:port
```

Или без аутентификации:
```env
OPENAI_PROXY=http://proxy-server.com:port
```

2. Установите зависимость httpx (если еще не установлена):
```bash
pip install httpx>=0.24.0
```

## Важно

- Прокси должен поддерживать HTTPS соединения
- Прокси должен иметь доступ к `api.openai.com`
- Если прокси не указан, бот будет работать без прокси (как раньше)

## Примеры прокси

- HTTP прокси: `http://proxy.example.com:8080`
- HTTPS прокси: `https://proxy.example.com:8080`
- С аутентификацией: `http://username:password@proxy.example.com:8080`
