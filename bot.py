"""
Бот напоминаний о днях рождения
Многопользовательская система с индивидуальными списками в отдельных файлах
+ AI-поздравления через GigaChat
"""

import json
import os
import random
import aiohttp
import uuid
import ssl
from io import BytesIO
from datetime import datetime
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    filters, ContextTypes, ConversationHandler
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# === КОНФИГУРАЦИЯ ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
GIGACHAT_AUTH = os.getenv("GIGACHAT_AUTH")  # Authorization key от Сбера

USERS_DIR = "users"
SESSIONS_FILE = "sessions.json"

# GigaChat API URLs
GIGACHAT_OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
GIGACHAT_API_URL = "https://gigachat.devices.sberbank.ru/api/v1"

# Состояния диалога
WAITING_CODE = 0

# === ПОЛЬЗОВАТЕЛИ (код -> имя) ===
USERS = {
    "2": "Надежда",
    "14": "Нася",
    "7": "Сережа",
    "11": "Юра",
    "9": "Марина Кирилловна",
    "18": "Николай Николаевич",
    "28": "Елена Викторовна",
    "25": "Сергей Евгеньевич",
    "21": "Александра"
}

# Кэш для access token
gigachat_token_cache = {
    "token": None,
    "expires": None
}


# === РАБОТА С ФАЙЛАМИ ===

def get_user_file(code):
    """Путь к файлу списка ДР пользователя"""
    return os.path.join(USERS_DIR, f"user_{code}.json")


def load_birthdays(code):
    """Загрузить список ДР пользователя"""
    filepath = get_user_file(code)
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


def save_birthdays(code, birthdays):
    """Сохранить список ДР пользователя"""
    filepath = get_user_file(code)
    os.makedirs(USERS_DIR, exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(birthdays, f, ensure_ascii=False, indent=2)


def load_sessions():
    """Загрузить сессии (связь chat_id -> code)"""
    if os.path.exists(SESSIONS_FILE):
        with open(SESSIONS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_sessions(sessions):
    """Сохранить сессии"""
    with open(SESSIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump(sessions, f, ensure_ascii=False, indent=2)


# Глобальные сессии: {"chat_id": "code"}
sessions = load_sessions()


def get_code_by_chat_id(chat_id):
    """Найти код пользователя по chat_id"""
    return sessions.get(str(chat_id))


def get_birthdays_this_month(birthdays):
    """ДР в текущем месяце"""
    current_month = datetime.now().month
    return [b for b in birthdays if b["month"] == current_month]


def get_birthdays_today(birthdays):
    """ДР сегодня"""
    today = datetime.now()
    return [b for b in birthdays if b["day"] == today.day and b["month"] == today.month]


# === GIGACHAT API ===

async def get_gigachat_token():
    """Получить access token для GigaChat (кэшируется на 30 минут)"""
    global gigachat_token_cache
    
    # Проверяем кэш
    if gigachat_token_cache["token"] and gigachat_token_cache["expires"]:
        if datetime.now().timestamp() < gigachat_token_cache["expires"] - 60:
            return gigachat_token_cache["token"]
    
    if not GIGACHAT_AUTH:
        return None
    
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                GIGACHAT_OAUTH_URL,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                    "RqUID": str(uuid.uuid4()),
                    "Authorization": f"Basic {GIGACHAT_AUTH}"
                },
                data="scope=GIGACHAT_API_PERS",
                ssl=ssl_context
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    gigachat_token_cache["token"] = data["access_token"]
                    gigachat_token_cache["expires"] = data["expires_at"] / 1000
                    return data["access_token"]
                else:
                    print(f"GigaChat OAuth error: {resp.status}")
                    return None
    except Exception as e:
        print(f"GigaChat OAuth exception: {e}")
        return None


async def gigachat_request(messages, max_retries=2):
    """Отправить запрос к GigaChat"""
    for attempt in range(max_retries):
        token = await get_gigachat_token()
        if not token:
            continue
        
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{GIGACHAT_API_URL}/chat/completions",
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "Authorization": f"Bearer {token}"
                    },
                    json={
                        "model": "GigaChat",
                        "messages": messages,
                        "temperature": 0.9
                    },
                    ssl=ssl_context
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"GigaChat request error (attempt {attempt + 1}): {e}")
    
    return None


async def gigachat_generate_image(prompt, max_retries=2):
    """Сгенерировать изображение через GigaChat (Kandinsky)"""
    for attempt in range(max_retries):
        token = await get_gigachat_token()
        if not token:
            continue
        
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{GIGACHAT_API_URL}/chat/completions",
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "Authorization": f"Bearer {token}"
                    },
                    json={
                        "model": "GigaChat",
                        "messages": [{"role": "user", "content": prompt}],
                        "function_call": "auto"
                    },
                    ssl=ssl_context
                ) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                    content = data["choices"][0]["message"]["content"]
                    
                    if "<img src=\"" in content:
                        start = content.find("<img src=\"") + 10
                        end = content.find("\"", start)
                        file_id = content[start:end]
                        
                        async with session.get(
                            f"{GIGACHAT_API_URL}/files/{file_id}/content",
                            headers={"Authorization": f"Bearer {token}"},
                            ssl=ssl_context
                        ) as img_resp:
                            if img_resp.status == 200:
                                return await img_resp.read()
        except Exception as e:
            print(f"GigaChat image error (attempt {attempt + 1}): {e}")
    
    return None


async def detect_gender(name):
    """Определить пол по имени через GigaChat"""
    prompt = f"""Определи пол человека по имени: "{name}"
Ответь только одной буквой: М или Ж"""
    
    response = await gigachat_request([{"role": "user", "content": prompt}])
    
    if response:
        response = response.strip().upper()
        if "М" in response:
            return "m"
        elif "Ж" in response:
            return "f"
    
    return "f"


async def generate_greeting(name):
    """Сгенерировать поздравление (стих + проза)"""
    prompt = f"""Напиши поздравление с днём рождения для {name}.

Требования:
1. Сначала короткий стих (4-6 строк) с хорошей рифмой
2. Затем 2-3 предложения тёплой прозы
3. Используй имя в поздравлении
4. Без банальностей
5. Искренне и душевно

Только текст поздравления, без пояснений."""

    return await gigachat_request([{"role": "user", "content": prompt}])


async def generate_birthday_card(name, gender):
    """Сгенерировать открытку"""
    if gender == "f":
        style = "красивые цветы, нежные тона, праздничная атмосфера"
    else:
        style = "стильная мужская открытка, сдержанные тона, элегантный дизайн"
    
    prompt = f"""Нарисуй праздничную открытку с днём рождения.
Стиль: {style}
На открытке крупно напиши: "{name}, с днём рождения!"
Открытка должна быть яркой и праздничной."""

    return await gigachat_generate_image(prompt)


async def generate_ai_greeting(name):
    """Полная генерация: пол + поздравление + 2 открытки"""
    gender = await detect_gender(name)
    greeting = await generate_greeting(name)
    
    card1 = await generate_birthday_card(name, gender)
    card2 = await generate_birthday_card(name, gender)
    
    return {
        "greeting": greeting,
        "cards": [card1, card2],
        "gender": gender
    }


# === ОБРАБОТЧИКИ КОМАНД ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало — запрос кода"""
    await update.message.reply_text(
        "🎂 Привет! Это бот напоминаний о днях рождения.\n\n"
        "Введи свой секретный код для авторизации:"
    )
    return WAITING_CODE


async def check_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка кода"""
    code = update.message.text.strip()
    chat_id = str(update.effective_chat.id)
    
    if code in USERS:
        sessions[chat_id] = code
        save_sessions(sessions)
        
        user_name = USERS[code]
        birthdays = load_birthdays(code)
        
        await update.message.reply_text(
            f"✅ Привет, {user_name}!\n\n"
            f"Ты авторизован. В списке {len(birthdays)} дней рождения.\n\n"
            f"Команды:\n"
            f"/month — ДР в этом месяце\n"
            f"/list — весь список\n"
            f"/add — добавить ДР\n"
            f"/del — удалить ДР\n"
            f"/help — помощь",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END
    else:
        await update.message.reply_text("❌ Неверный код. Попробуй ещё раз:")
        return WAITING_CODE


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена"""
    await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


async def show_month(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ДР в этом месяце"""
    chat_id = str(update.effective_chat.id)
    code = get_code_by_chat_id(chat_id)
    
    if not code:
        await update.message.reply_text("⚠️ Сначала авторизуйся: /start")
        return
    
    birthdays = load_birthdays(code)
    month_names = [
        "", "январе", "феврале", "марте", "апреле", "мае", "июне",
        "июле", "августе", "сентябре", "октябре", "ноябре", "декабре"
    ]
    current_month = datetime.now().month
    month_bdays = get_birthdays_this_month(birthdays)
    
    if month_bdays:
        month_bdays.sort(key=lambda x: x["day"])
        lines = [f"🎂 Дни рождения в {month_names[current_month]}:\n"]
        for b in month_bdays:
            lines.append(f"  • {b['day']} — {b['name']}")
        await update.message.reply_text("\n".join(lines))
    else:
        await update.message.reply_text(
            f"📭 В {month_names[current_month]} нет дней рождения."
        )


async def show_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Весь список ДР"""
    chat_id = str(update.effective_chat.id)
    code = get_code_by_chat_id(chat_id)
    
    if not code:
        await update.message.reply_text("⚠️ Сначала авторизуйся: /start")
        return
    
    birthdays = load_birthdays(code)
    
    if birthdays:
        sorted_bdays = sorted(birthdays, key=lambda x: (x["month"], x["day"]))
        lines = ["📋 Список дней рождения:\n"]
        current_month = 0
        month_names = [
            "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
            "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"
        ]
        for b in sorted_bdays:
            if b["month"] != current_month:
                current_month = b["month"]
                lines.append(f"\n{month_names[current_month]}:")
            lines.append(f"  {b['day']:2d} — {b['name']}")
        await update.message.reply_text("\n".join(lines))
    else:
        await update.message.reply_text("📭 Список пуст. Добавь ДР: /add Имя ДД.ММ")


async def add_birthday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавить ДР"""
    chat_id = str(update.effective_chat.id)
    code = get_code_by_chat_id(chat_id)
    
    if not code:
        await update.message.reply_text("⚠️ Сначала авторизуйся: /start")
        return
    
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "📝 Формат: /add Имя ДД.ММ\n"
            "Пример: /add Мама 15.03"
        )
        return
    
    name = " ".join(args[:-1])
    date_str = args[-1]
    
    try:
        day, month = map(int, date_str.split('.'))
        if not (1 <= day <= 31 and 1 <= month <= 12):
            raise ValueError()
    except:
        await update.message.reply_text("❌ Неверный формат даты. Используй ДД.ММ")
        return
    
    birthdays = load_birthdays(code)
    birthdays.append({"day": day, "month": month, "name": name})
    save_birthdays(code, birthdays)
    
    await update.message.reply_text(f"✅ Добавлено: {name} — {day:02d}.{month:02d}")


async def del_birthday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удалить ДР"""
    chat_id = str(update.effective_chat.id)
    code = get_code_by_chat_id(chat_id)
    
    if not code:
        await update.message.reply_text("⚠️ Сначала авторизуйся: /start")
        return
    
    args = context.args
    if not args:
        await update.message.reply_text(
            "📝 Формат: /del Имя\n"
            "Пример: /del Мама"
        )
        return
    
    name = " ".join(args).lower()
    birthdays = load_birthdays(code)
    
    found = None
    for i, b in enumerate(birthdays):
        if name in b["name"].lower():
            found = i
            break
    
    if found is not None:
        removed = birthdays.pop(found)
        save_birthdays(code, birthdays)
        await update.message.reply_text(
            f"✅ Удалено: {removed['name']} — {removed['day']:02d}.{removed['month']:02d}"
        )
    else:
        await update.message.reply_text(f"❌ Не найдено: {name}")


async def test_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Тест AI-поздравления (только для кода 7)"""
    chat_id = str(update.effective_chat.id)
    code = get_code_by_chat_id(chat_id)
    
    if code != "7":
        await update.message.reply_text("⚠️ Эта команда доступна только администратору.")
        return
    
    birthdays = load_birthdays(code)
    if not birthdays:
        await update.message.reply_text("📭 Список именинников пуст.")
        return
    
    birthday = random.choice(birthdays)
    name = birthday["name"]
    
    await update.message.reply_text(f"🔄 Генерирую поздравление для: {name}\nПодожди немного...")
    
    result = await generate_ai_greeting(name)
    
    if result["greeting"]:
        gender_text = "👩 Женщина" if result["gender"] == "f" else "👨 Мужчина"
        await update.message.reply_text(
            f"🎂 *Поздравление для {name}*\n"
            f"({gender_text})\n\n"
            f"{result['greeting']}",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            f"⚠️ Не удалось сгенерировать текст.\n"
            f"Простое поздравление:\n\n"
            f"🎉 {name}, с днём рождения! Счастья, здоровья и всех благ! 🎂"
        )
    
    cards_sent = 0
    for i, card_data in enumerate(result["cards"]):
        if card_data:
            try:
                await update.message.reply_photo(
                    photo=BytesIO(card_data),
                    caption=f"Открытка {i + 1}"
                )
                cards_sent += 1
            except Exception as e:
                print(f"Ошибка отправки открытки: {e}")
    
    if cards_sent == 0:
        await update.message.reply_text("⚠️ Не удалось сгенерировать открытки.")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Справка"""
    chat_id = str(update.effective_chat.id)
    code = get_code_by_chat_id(chat_id)
    
    help_text = (
        "🎂 *Бот напоминаний о ДР*\n\n"
        "*Команды:*\n"
        "/start — авторизация\n"
        "/month — ДР в этом месяце\n"
        "/list — весь список\n"
        "/add Имя ДД.ММ — добавить\n"
        "/del Имя — удалить\n"
        "/help — справка\n\n"
        "*Автонапоминания:*\n"
        "• 1 числа — обзор месяца (8:00)\n"
        "• В день ДР — поздравление с AI (8:00)"
    )
    
    if code == "7":
        help_text += "\n\n*Админ-команды:*\n/test — тест AI-поздравления"
    
    await update.message.reply_text(help_text, parse_mode="Markdown")


# === АВТОМАТИЧЕСКИЕ НАПОМИНАНИЯ ===

async def daily_birthday_check(app):
    """Проверка ДР каждый день в 8:00 с AI-поздравлениями"""
    for chat_id, code in sessions.items():
        birthdays = load_birthdays(code)
        today_bdays = get_birthdays_today(birthdays)
        
        if today_bdays:
            for birthday in today_bdays:
                name = birthday["name"]
                
                result = await generate_ai_greeting(name)
                
                if result["greeting"]:
                    try:
                        await app.bot.send_message(
                            chat_id=int(chat_id),
                            text=f"🎂 *Сегодня день рождения: {name}*\n\n{result['greeting']}",
                            parse_mode="Markdown"
                        )
                    except Exception as e:
                        print(f"Ошибка отправки текста {chat_id}: {e}")
                    
                    for i, card_data in enumerate(result["cards"]):
                        if card_data:
                            try:
                                await app.bot.send_photo(
                                    chat_id=int(chat_id),
                                    photo=BytesIO(card_data),
                                    caption=f"Открытка {i + 1} для {name}"
                                )
                            except Exception as e:
                                print(f"Ошибка отправки открытки {chat_id}: {e}")
                else:
                    try:
                        await app.bot.send_message(
                            chat_id=int(chat_id),
                            text=f"🎉 Сегодня день рождения:\n{name}\n\nНе забудь поздравить! 🎂"
                        )
                    except Exception as e:
                        print(f"Ошибка отправки {chat_id}: {e}")


async def monthly_reminder(app):
    """Напоминание 1 числа в 8:00"""
    month_names = [
        "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
        "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"
    ]
    current_month = datetime.now().month
    
    for chat_id, code in sessions.items():
        birthdays = load_birthdays(code)
        month_bdays = get_birthdays_this_month(birthdays)
        
        if month_bdays:
            month_bdays.sort(key=lambda x: x["day"])
            lines = [f"📅 {month_names[current_month]} — дни рождения:\n"]
            for b in month_bdays:
                lines.append(f"  • {b['day']} — {b['name']}")
            text = "\n".join(lines)
        else:
            text = f"📅 В {month_names[current_month].lower()}е нет дней рождения."
        
        try:
            await app.bot.send_message(chat_id=int(chat_id), text=text)
        except Exception as e:
            print(f"Ошибка отправки {chat_id}: {e}")


def setup_scheduler(app):
    """Планировщик задач"""
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    
    # Ежедневно в 8:00
    scheduler.add_job(
        daily_birthday_check, 
        'cron', 
        hour=8, minute=0,
        args=[app]
    )
    
    # 1 числа в 8:00
    scheduler.add_job(
        monthly_reminder, 
        'cron', 
        day=1, hour=8, minute=0,
        args=[app]
    )
    
    scheduler.start()
    return scheduler


# === ЗАПУСК ===

def main():
    """Главная функция"""
    app = Application.builder().token(BOT_TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAITING_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, check_code)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("month", show_month))
    app.add_handler(CommandHandler("list", show_list))
    app.add_handler(CommandHandler("add", add_birthday))
    app.add_handler(CommandHandler("del", del_birthday))
    app.add_handler(CommandHandler("test", test_ai))
    app.add_handler(CommandHandler("help", help_command))
    
    setup_scheduler(app)
    
    print("🎂 Бот запущен!")
    print(f"Пользователей: {len(USERS)}")
    print(f"Активных сессий: {len(sessions)}")
    print(f"GigaChat: {'✓ настроен' if GIGACHAT_AUTH else '✗ не настроен'}")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
