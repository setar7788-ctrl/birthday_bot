"""
Бот напоминаний о днях рождения
Многопользовательская система с индивидуальными списками в отдельных файлах
"""

import json
import os
from datetime import datetime
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    filters, ContextTypes, ConversationHandler
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# === КОНФИГУРАЦИЯ ===
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"  # Замени на свой токен
USERS_DIR = "users"  # Папка со списками ДР
SESSIONS_FILE = "sessions.json"  # Файл сессий (chat_id пользователей)

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
        # Сохраняем сессию
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
    
    # Ищем совпадение
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


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Справка"""
    await update.message.reply_text(
        "🎂 *Бот напоминаний о ДР*\n\n"
        "*Команды:*\n"
        "/start — авторизация\n"
        "/month — ДР в этом месяце\n"
        "/list — весь список\n"
        "/add Имя ДД.ММ — добавить\n"
        "/del Имя — удалить\n"
        "/help — справка\n\n"
        "*Автонапоминания:*\n"
        "• 1 числа — обзор месяца (10:00)\n"
        "• В день ДР — напоминание (9:00)",
        parse_mode="Markdown"
    )


# === АВТОМАТИЧЕСКИЕ НАПОМИНАНИЯ ===

async def daily_birthday_check(app):
    """Проверка ДР каждый день в 9:00"""
    for chat_id, code in sessions.items():
        birthdays = load_birthdays(code)
        today_bdays = get_birthdays_today(birthdays)
        
        if today_bdays:
            names = ", ".join([b["name"] for b in today_bdays])
            try:
                await app.bot.send_message(
                    chat_id=int(chat_id),
                    text=f"🎉 Сегодня день рождения:\n{names}\n\nНе забудь поздравить! 🎂"
                )
            except Exception as e:
                print(f"Ошибка отправки {chat_id}: {e}")


async def monthly_reminder(app):
    """Напоминание 1 числа в 10:00"""
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
    
    # Ежедневно в 9:00
    scheduler.add_job(
        daily_birthday_check, 
        'cron', 
        hour=9, minute=0,
        args=[app]
    )
    
    # 1 числа в 10:00
    scheduler.add_job(
        monthly_reminder, 
        'cron', 
        day=1, hour=10, minute=0,
        args=[app]
    )
    
    scheduler.start()
    return scheduler


# === ЗАПУСК ===

def main():
    """Главная функция"""
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Диалог авторизации
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
    app.add_handler(CommandHandler("help", help_command))
    
    setup_scheduler(app)
    
    print("🎂 Бот запущен!")
    print(f"Пользователей: {len(USERS)}")
    print(f"Активных сессий: {len(sessions)}")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
