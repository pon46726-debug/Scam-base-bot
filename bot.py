import logging
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)

# Логирование
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния
USERNAME, DESCRIPTION, EVIDENCE = range(3)

# Настройки
ADMIN_CHAT_ID = 12345678  # ← ЗАМЕНИТЕ НА СВОЙ ID
DB_NAME = "scam_reports.db"

# Инициализация базы
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            description TEXT NOT NULL,
            evidence_type TEXT NOT NULL,
            evidence_data TEXT,
            evidence_caption TEXT,
            status TEXT DEFAULT 'pending',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

# Сохранение заявки в БД
def save_report(user_id, username, description, evidence_type, evidence_data, evidence_caption=""):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO reports (user_id, username, description, evidence_type, evidence_data, evidence_caption)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, username, description, evidence_type, evidence_data, evidence_caption))
    report_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return report_id

# Получить последнюю заявку пользователя
def get_last_report(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, username, status FROM reports
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 1
    """, (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row  # (id, username, status)

# Получить все pending заявки
def get_pending_reports():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, user_id, username, description FROM reports WHERE status = 'pending'")
    rows = cursor.fetchall()
    conn.close()
    return rows  # [(id, user_id, username, description), ...]

# Получить все подтверждённые скамеры
def get_approved_scammer_usernames():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT username FROM reports WHERE status = 'approved'")
    rows = cursor.fetchall()
    conn.close()
    return [row[0] for row in rows]

# Обновить статус заявки
def update_report_status(report_id, status):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE reports SET status = ? WHERE id = ?", (status, report_id))
    conn.commit()
    conn.close()

# Получить полную заявку по ID
def get_report_by_id(report_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM reports WHERE id = ?", (report_id,))
    row = cursor.fetchone()
    conn.close()
    return row

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🛡️ Бот-анти-скам\n\n"
        "Подавайте заявки на мошенников и проверяйте, не в чёрном ли списке кто-то.\n\n"
        "Команды:\n"
        "/start — это сообщение\n"
        "/add — подать заявку\n"
        "/status — проверить статус вашей последней заявки"
    )
    await update.message.reply_text(text)

# Начало подачи заявки
async def add_scammer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Введите юзернейм (или ID) мошенника:")
    return USERNAME

async def receive_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['username'] = update.message.text.strip()
    await update.message.reply_text("Опишите ситуацию подробно:")
    return DESCRIPTION

async def receive_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['description'] = update.message.text
    await update.message.reply_text("Пришлите доказательства (текст или фото):")
    return EVIDENCE

async def receive_evidence(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = context.user_data['username']
    description = context.user_data['description']

    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        caption = update.message.caption or ""
        report_id = save_report(user_id, username, description, 'photo', file_id, caption)
        # Отправляем админу
        try:
            await context.bot.send_photo(
                chat_id=ADMIN_CHAT_ID,
                photo=file_id,
                caption=(
                    f"🆕 Новая заявка #{report_id}\n"
                    f"От: @{update.effective_user.username or user_id}\n"
                    f"Мошенник: @{username}\n"
                    f"Описание: {description}\n"
                    f"Статус: pending"
                )
            )
        except Exception as e:
            logger.error(f"Не удалось отправить фото админу: {e}")
    else:
        text_evidence = update.message.text
        report_id = save_report(user_id, username, description, 'text', text_evidence)
        try:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=(
                    f"🆕 Новая заявка #{report_id}\n"
                    f"От: @{update.effective_user.username or user_id}\n"
                    f"Мошенник: @{username}\n"
                    f"Описание: {description}\n"
                    f"Доказательство: {text_evidence}\n"
                    f"Статус: pending"
                )
            )
        except Exception as e:
            logger.error(f"Не удалось отправить текст админу: {e}")

    await update.message.reply_text(
        f"✅ Заявка #{report_id} отправлена! Используйте /status для проверки статуса."
    )
    return ConversationHandler.END

# Команда /status
async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    report = get_last_report(user_id)
    if report:
        report_id, scammer, status = report
        status_text = {
            'pending': '⏳ Ожидает проверки',
            'approved': '✅ Подтверждена',
            'rejected': '❌ Отклонена'
        }.get(status, status)
        await update.message.reply_text(
            f"Ваша последняя заявка:\n"
            f"ID: #{report_id}\n"
            f"Мошенник: @{scammer}\n"
            f"Статус: {status_text}"
        )
    else:
        await update.message.reply_text("У вас пока нет поданных заявок.")

# АДМИНКА

# Проверка, является ли пользователь админом
def is_admin(user_id):
    return user_id == ADMIN_CHAT_ID

# /pending — список нерассмотренных
async def pending_reports(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 Эта команда только для администратора.")
        return

    reports = get_pending_reports()
    if not reports:
        await update.message.reply_text("Нет заявок на рассмотрении.")
        return

    text = "📄 Заявки на рассмотрении:\n\n"
    for r_id, u_id, scammer, desc in reports[:10]:  # максимум 10
        text += f"ID: #{r_id} | Мошенник: @{scammer}\n"
    text += "\nИспользуйте /approve <ID> или /reject <ID>"
    await update.message.reply_text(text)

# /approve <id>
async def approve_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Использование: /approve <ID>")
        return
    try:
        report_id = int(context.args[0])
        update_report_status(report_id, 'approved')
        report = get_report_by_id(report_id)
        if report:
            _, user_id, username, *_ = report
            await context.bot.send_message(
                chat_id=user_id,
                text=f"✅ Ваша заявка #{report_id} (мошенник @{username}) подтверждена!"
            )
        await update.message.reply_text(f"✅ Заявка #{report_id} подтверждена.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

# /reject <id>
async def reject_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Использование: /reject <ID>")
        return
    try:
        report_id = int(context.args[0])
        update_report_status(report_id, 'rejected')
        report = get_report_by_id(report_id)
        if report:
            _, user_id, username, *_ = report
            await context.bot.send_message(
                chat_id=user_id,
                text=f"❌ Ваша заявка #{report_id} (мошенник @{username}) отклонена."
            )
        await update.message.reply_text(f"❌ Заявка #{report_id} отклонена.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

# /scammers — список всех подтверждённых
async def list_scammers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    scammers = get_approved_scammer_usernames()
    if not scammers:
        await update.message.reply_text("Нет подтверждённых мошенников.")
        return
    text = "⚠️ Подтверждённые мошенники:\n\n" + "\n".join(f"@{s}" for s in scammers)
    await update.message.reply_text(text)

# Отмена
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Отменено.")
    return ConversationHandler.END

# Основная функция
def main():
    init_db()
    TOKEN = "xxxxxxxx"  # ← ЗАМЕНИТЕ!
    application = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("add", add_scammer)],
        states={
            USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_username)],
            DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_description)],
            EVIDENCE: [MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, receive_evidence)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", check_status))
    # Админ команды
    application.add_handler(CommandHandler("pending", pending_reports))
    application.add_handler(CommandHandler("approve", approve_report))
    application.add_handler(CommandHandler("reject", reject_report))
    application.add_handler(CommandHandler("scammers", list_scammers))

    application.add_handler(conv_handler)

    application.run_polling()

if __name__ == "__main__":
    main()
