# 1. Базовый слой: берем официальный ультра-легкий образ Python на базе Alpine Linux
FROM python:3.11-alpine

# 2. Настраиваем рабочую папку внутри контейнера, где будет жить наш код
WORKDIR /code

# 3. Устанавливаем системные зависимости для сборки драйвера PostgreSQL (psycopg)
RUN apk add --no-cache gcc musl-dev postgresql-dev libffi-dev

# 4. Копируем список библиотек с вашего компьютера внутрь контейнера
COPY ./requirements.txt /code/requirements.txt

# 5. Обновляем установщик пакетов (pip) и скачиваем наши библиотеки без сохранения кэша (для экономии места)
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /code/requirements.txt

# 6. Копируем всю нашу папку с кодом 'app' внутрь контейнера
COPY ./app /code/app

# 7. Финальная команда: запускаем веб-сервер uvicorn на порту 80, который слушает весь мир (0.0.0.0)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "80"]