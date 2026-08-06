from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import os
import time
import psycopg

app = FastAPI(title="Pets Voting API")
templates = Jinja2Templates(directory="app/templates")

# 1. Считываем доступы, которые Kubernetes прокинул нам в переменные окружения
DB_HOST = os.getenv("DB_HOST", "db-service")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "postgres")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

# Формируем строку подключения к PostgreSQL
DB_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

def init_db():
    """Функция подключения к базе и создания таблицы голосования"""
    # Делаем несколько попыток, так как базе нужно время на старт
    for _ in range(5):
        try:
            with psycopg.connect(DB_URL) as conn:
                with conn.cursor() as cur:
                    # Создаем таблицу, если проект запускается впервые
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS votes (
                            id SERIAL PRIMARY KEY,
                            candidate TEXT NOT NULL,
                            user_ip TEXT NOT NULL DEFAULT 'unknown',
                            voted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                    """)
                    conn.commit()
            print("База данных успешно инициализирована!")
            return
        except Exception as e:
            print(f"Ожидание базы данных... Ошибка: {e}")
            time.sleep(3)
    raise RuntimeError("Не удалось подключиться к PostgreSQL")

# Инициализируем БД при старте приложения
@app.on_event("startup")
def startup_event():
    init_db()

@app.get("/", response_class=HTMLResponse)
def read_root(request: Request):
    # Теперь request передается вторым аргументом напрямую!
    return templates.TemplateResponse(request=request, name="index.html")

# ЭНДПОИНТ ДЛЯ ГОЛОСОВАНИЯ (С ЗАЩИТОЙ ОТ НАКРУТКИ)
@app.post("/vote/{candidate}")
def voice_vote(candidate: str, request: Request):
    if candidate not in ["cats", "dogs"]:
        raise HTTPException(status_code=400, detail="Голосовать можно только за 'cats' или 'dogs'")
    
    # 1. Определяем IP-адрес пользователя (учитываем, что мы за Ingress/Traefik)
    user_ip = request.headers.get("X-Forwarded-For")
    if not user_ip:
        user_ip = request.client.host if request.client else "unknown"
    # Если прокси передал цепочку IP, берем первый (реальный адрес клиента)
    user_ip = user_ip.split(",")[0].strip()

    try:
        with psycopg.connect(DB_URL) as conn:
            with conn.cursor() as cur:
                # 2. Проверяем, голосовал ли этот IP за последние 10 секунд
                cur.execute("""
                    SELECT voted_at 
                    FROM votes 
                    WHERE user_ip = %s 
                    ORDER BY voted_at DESC 
                    LIMIT 1;
                """, (user_ip,))
                
                last_vote = cur.fetchone()
                
                if last_vote:
                    # База данных сама считает разницу во времени. 
                    # Посмотрим, сколько секунд прошло с момента последнего голоса
                    cur.execute("""
                        SELECT EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - %s));
                    """, (last_vote[0],))
                    seconds_passed = cur.fetchone()[0]
                    
                    # Если прошло меньше 10 секунд — блокируем!
                    if seconds_passed and seconds_passed < 10:
                        time_left = int(10 - seconds_passed)
                        raise HTTPException(
                            status_code=429, 
                            detail=f"Подождите {time_left} сек. перед следующим голосованием!"
                        )

                # 3. Если проверки пройдены — записываем голос вместе с IP-адресом
                cur.execute("""
                    INSERT INTO votes (candidate, user_ip) VALUES (%s, %s);
                """, (candidate, user_ip))
                conn.commit()
                
        return {"status": "success", "message": f"Ваш голос за {candidate} учтен!"}
        
    except HTTPException as he:
        # Перенаправляем нашу ошибку 429 наружу без изменений
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка базы данных: {e}")

# 3. Эндпоинт для вывода результатов (GET-запрос)
@app.get("/results")
def get_results():
    try:
        with psycopg.connect(DB_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT candidate, COUNT(*) 
                    FROM votes 
                    GROUP BY candidate;
                """)
                results = dict(cur.fetchall())
                
        # Гарантируем, что в ответе всегда будут оба кандидата, даже если за них еще не голосовали
        return {
            "cats": results.get("cats", 0),
            "dogs": results.get("dogs", 0)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка базы данных: {e}")