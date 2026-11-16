from __future__ import annotations

import logging
import math
import os
import re
import sys
import warnings
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import Forbidden, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from telegram.warnings import PTBUserWarning

import storage

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

warnings.filterwarnings("ignore", category=PTBUserWarning, message=".*per_message=False.*")

load_dotenv()

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("task-bot")

TICK_SECONDS = 20

TITLE, DELAY, CUSTOM_DELAY, REPEAT, CUSTOM_REPEAT, INTERVAL, CUSTOM_INTERVAL, CONFIRM = range(8)

DELAY_CHOICES = [("۳۰ دقیقه", 30), ("۱ ساعت", 60), ("۳ ساعت", 180), ("۸ ساعت", 480)]
REPEAT_CHOICES = [("۱ بار", 1), ("۳ بار", 3), ("۵ بار", 5), ("۱۰ بار", 10)]
INTERVAL_CHOICES = [("۵ دقیقه", 5), ("۱۵ دقیقه", 15), ("۳۰ دقیقه", 30), ("۱ ساعت", 60)]
SNOOZE_MINUTES = 10

WELCOME = (
    "سلام 👋 من ربات مدیریت تسکم.\n\n"
    "تسک‌هات رو بفرست، بگو چند وقت بعد یادت بندازم و چند بار پشت سر هم تکرار کنم؛\n"
    "من سر وقت پیام می‌دم تا کارت از دستت نره.\n\n"
    "از دکمه‌های زیر شروع کن یا /new رو بزن."
)

HELP_TEXT = (
    "🤖 راهنمای ربات\n\n"
    "/new — ساخت تسک جدید\n"
    "/list — دیدن تسک‌ها\n"
    "/done ۳ — انجام‌شده کردن تسک شمارهٔ ۳\n"
    "/del ۳ — حذف تسک شمارهٔ ۳\n"
    "/cancel — لغو ساخت تسک\n\n"
    "مثال: تسک «تماس با دکتر» → ۸ ساعت بعد → ۳ بار، هر ۱۵ دقیقه.\n"
    "یعنی ۸ ساعت بعد یادت می‌ندازم و بعد هر ۱۵ دقیقه دو بار دیگه تکرار می‌کنم."
)

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

UNIT_MINUTES = {
    "s": 1 / 60,
    "sec": 1 / 60,
    "second": 1 / 60,
    "seconds": 1 / 60,
    "ثانیه": 1 / 60,
    "m": 1,
    "min": 1,
    "mins": 1,
    "minute": 1,
    "minutes": 1,
    "دقیقه": 1,
    "h": 60,
    "hr": 60,
    "hour": 60,
    "hours": 60,
    "ساعت": 60,
    "d": 1440,
    "day": 1440,
    "days": 1440,
    "روز": 1440,
    "week": 10080,
    "هفته": 10080,
}

_DURATION_RE = re.compile(
    r"^\s*(?:(?P<n1>\d+(?:[.,]\d+)?)\s*(?P<u1>[^\d\s]*)|(?P<u2>[^\d\s]+)\s*(?P<n2>\d+(?:[.,]\d+)?))\s*$"
)

try:
    TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Tehran"))
except Exception:
    logger.warning("منطقهٔ زمانی پیدا نشد؛ از UTC استفاده می‌کنم.")
    TZ = timezone.utc


def fa(value: object) -> str:
    return str(value).translate(_FA_DIGITS)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def fmt_when(value: str) -> str:
    return parse_iso(value).astimezone(TZ).strftime("%Y-%m-%d %H:%M")


def minutes_until(value: str) -> int:
    seconds = (parse_iso(value) - utcnow()).total_seconds()
    return max(math.ceil(seconds / 60), 0)


def format_minutes(total: int) -> str:
    total = max(int(total), 0)
    days, rest = divmod(total, 1440)
    hours, minutes = divmod(rest, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{fa(days)} روز")
    if hours:
        parts.append(f"{fa(hours)} ساعت")
    if minutes:
        parts.append(f"{fa(minutes)} دقیقه")
    return " و ".join(parts) or "۰ دقیقه"


def parse_duration(text: str) -> int | None:
    clean = text.translate(_DIGITS).strip().lower().replace("‌", " ")
    match = _DURATION_RE.match(clean)
    if not match:
        return None
    if match.group("n1"):
        number, unit = match.group("n1"), match.group("u1") or "m"
    else:
        number, unit = match.group("n2"), match.group("u2") or "m"
    unit = unit.strip().rstrip(".")
    minutes = UNIT_MINUTES.get(unit)
    if minutes is None:
        return None
    exact = float(number.replace(",", ".")) * minutes
    if exact <= 0:
        return None
    total = max(1, int(round(exact)))
    if total > 525600:
        return None
    return total


def parse_count(text: str, low: int = 1, high: int = 50) -> int | None:
    clean = text.translate(_DIGITS).strip()
    if not clean.isdigit():
        return None
    value = int(clean)
    return value if low <= value <= high else None


def parse_int_arg(text: str) -> int | None:
    clean = text.translate(_DIGITS).strip().lstrip("#")
    return int(clean) if clean.isdigit() else None


def next_reminder_at(task: storage.Task, now: datetime) -> str | None:
    sent = task.sent_count + 1
    if sent >= task.repeat_count:
        return None
    return (now + timedelta(minutes=task.repeat_interval)).isoformat()


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ تسک جدید", callback_data="newtask")],
            [
                InlineKeyboardButton("📋 تسک‌های من", callback_data="list"),
                InlineKeyboardButton("❓ راهنما", callback_data="help"),
            ],
        ]
    )


def _pairs(choices: list[tuple[str, int]], prefix: str) -> list[list[InlineKeyboardButton]]:
    buttons = [InlineKeyboardButton(label, callback_data=f"{prefix}:{value}") for label, value in choices]
    return [buttons[i : i + 2] for i in range(0, len(buttons), 2)]


def delay_kb() -> InlineKeyboardMarkup:
    rows = _pairs(DELAY_CHOICES, "delay")
    rows.append([InlineKeyboardButton("⏱ زمان دلخواه", callback_data="delay:custom")])
    return InlineKeyboardMarkup(rows)


def repeat_kb() -> InlineKeyboardMarkup:
    rows = _pairs(REPEAT_CHOICES, "rep")
    rows.append([InlineKeyboardButton("✍️ تعداد دلخواه", callback_data="rep:custom")])
    return InlineKeyboardMarkup(rows)


def interval_kb() -> InlineKeyboardMarkup:
    rows = _pairs(INTERVAL_CHOICES, "ri")
    rows.append([InlineKeyboardButton("⏱ فاصلهٔ دلخواه", callback_data="ri:custom")])
    return InlineKeyboardMarkup(rows)


def confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ ثبت کن", callback_data="confirm:yes")],
            [InlineKeyboardButton("✖️ انصراف", callback_data="confirm:no")],
        ]
    )


def reminder_kb(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ انجام شد", callback_data=f"r:done:{task_id}"),
                InlineKeyboardButton(
                    f"💤 {fa(SNOOZE_MINUTES)} دقیقه دیگه", callback_data=f"r:snooze:{task_id}"
                ),
            ],
            [InlineKeyboardButton("⛔️ توقف یادآوری", callback_data=f"r:stop:{task_id}")],
        ]
    )


def task_card(task: storage.Task) -> str:
    lines = [f"📌 {task.title}"]
    if task.next_at:
        lines.append(
            f"⏰ یادآوری بعدی: {fmt_when(task.next_at)} ({format_minutes(minutes_until(task.next_at))} دیگه)"
        )
    else:
        lines.append("🔕 یادآوری‌ها تموم شده")
    lines.append(
        f"🔁 {fa(task.sent_count)} از {fa(task.repeat_count)} یادآوری، هر {format_minutes(task.repeat_interval)}"
    )
    return "\n".join(lines)


def render_list(tasks: list[storage.Task]) -> str:
    if not tasks:
        return "📋 هنوز تسکی نداری.\n\nبا /new یا دکمهٔ «➕ تسک جدید» شروع کن."
    lines = ["📋 تسک‌های تو:", ""]
    for index, task in enumerate(tasks, start=1):
        icon = "✅" if task.status == storage.DONE else "📌"
        lines.append(f"{icon} {fa(index)}. {task.title}")
        if task.status == storage.DONE:
            lines.append("   انجام شد")
        elif task.next_at:
            lines.append(
                f"   ⏰ {fmt_when(task.next_at)} — {format_minutes(minutes_until(task.next_at))} دیگه"
            )
        else:
            lines.append("   🔕 یادآوری‌ها تموم شده")
        if task.status != storage.DONE:
            lines.append(
                f"   🔁 {fa(task.sent_count)} از {fa(task.repeat_count)} یادآوری، "
                f"هر {format_minutes(task.repeat_interval)}"
            )
        lines.append("")
    return "\n".join(lines).strip()


def list_kb(tasks: list[storage.Task]) -> InlineKeyboardMarkup | None:
    rows = []
    for index, task in enumerate(tasks, start=1):
        if task.status == storage.DONE:
            continue
        rows.append(
            [
                InlineKeyboardButton(f"✅ {fa(index)}", callback_data=f"t:done:{task.id}"),
                InlineKeyboardButton(f"🗑 {fa(index)}", callback_data=f"t:del:{task.id}"),
            ]
        )
    rows.append([InlineKeyboardButton("➕ تسک جدید", callback_data="newtask")])
    return InlineKeyboardMarkup(rows)


async def say(update: Update, text: str, **kwargs) -> None:
    query = update.callback_query
    if query:
        await query.answer()
        await query.message.reply_text(text, **kwargs)
    else:
        await update.effective_message.reply_text(text, **kwargs)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(WELCOME, reply_markup=main_menu_kb())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await say(update, HELP_TEXT, reply_markup=main_menu_kb())


async def show_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    tasks = storage.list_tasks(chat_id)
    text = render_list(tasks)
    keyboard = list_kb(tasks)
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(text, reply_markup=keyboard)
    else:
        await update.effective_message.reply_text(text, reply_markup=keyboard)


async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not context.args:
        await update.effective_message.reply_text(
            "شمارهٔ تسک رو بگو، مثلاً: /done ۳\nبرای دیدن شماره‌ها /list رو بزن.",
        )
        return
    task_id = parse_int_arg(context.args[0])
    task = storage.get_task(task_id) if task_id is not None else None
    if task is None or task.chat_id != chat_id:
        await update.effective_message.reply_text("تسکی با این شماره پیدا نشد. با /list شماره‌ها رو ببین.")
        return
    storage.set_status(task.id, storage.DONE)
    await update.effective_message.reply_text(f"✅ «{task.title}» انجام‌شده ثبت شد. آفرین!")


async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not context.args:
        await update.effective_message.reply_text(
            "شمارهٔ تسک رو بگو، مثلاً: /del ۳\nبرای دیدن شماره‌ها /list رو بزن.",
        )
        return
    task_id = parse_int_arg(context.args[0])
    task = storage.get_task(task_id) if task_id is not None else None
    if task is None or task.chat_id != chat_id:
        await update.effective_message.reply_text("تسکی با این شماره پیدا نشد. با /list شماره‌ها رو ببین.")
        return
    storage.delete_task(task.id)
    await update.effective_message.reply_text(f"🗑 «{task.title}» حذف شد.")


async def new_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await say(update, "📝 عنوان تسک رو بفرست (مثلاً «تماس با دکتر»):")
    return TITLE


async def got_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    title = " ".join((update.message.text or "").split())
    if len(title) < 2:
        await update.message.reply_text("عنوان خیلی کوتاهه 🤏 یه بار دیگه بفرست:")
        return TITLE
    context.user_data["title"] = title[:200]
    await update.message.reply_text(
        f"✅ تسک: «{context.user_data['title']}»\n\n⏰ چند وقت بعد یادت بندازم؟",
        reply_markup=delay_kb(),
    )
    return DELAY


async def got_delay(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = update.callback_query.data.split(":", 1)[1]
    if value == "custom":
        await say(
            update,
            "⏱ چند وقت بعد یادت بندازم؟\nمثلاً: 45m یا 8h یا 2d یا «۲ روز».",
        )
        return CUSTOM_DELAY
    context.user_data["delay"] = int(value)
    await say(
        update,
        f"⏰ {format_minutes(int(value))} بعد، اولین یادآوری.\n\n🔁 چند بار پشت سر هم یادت بندازم؟",
        reply_markup=repeat_kb(),
    )
    return REPEAT


async def got_custom_delay(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    minutes = parse_duration(update.message.text or "")
    if minutes is None:
        await update.message.reply_text("متوجه نشدم 🤔 مثلاً بنویس: 45m یا 8h یا 2 روز.")
        return CUSTOM_DELAY
    context.user_data["delay"] = minutes
    await update.message.reply_text(
        f"⏰ {format_minutes(minutes)} بعد، اولین یادآوری.\n\n🔁 چند بار پشت سر هم یادت بندازم؟",
        reply_markup=repeat_kb(),
    )
    return REPEAT


async def got_repeat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = update.callback_query.data.split(":", 1)[1]
    if value == "custom":
        await say(update, "🔁 چند بار یادت بندازم؟ یک عدد بین ۱ تا ۵۰ بنویس.")
        return CUSTOM_REPEAT
    context.user_data["repeat"] = int(value)
    await say(
        update,
        f"🔁 {fa(value)} بار.\n\n⏱ فاصلهٔ بین یادآوری‌ها چقدر باشه؟",
        reply_markup=interval_kb(),
    )
    return INTERVAL


async def got_custom_repeat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    count = parse_count(update.message.text or "")
    if count is None:
        await update.message.reply_text("یک عدد بین ۱ تا ۵۰ بفرست (مثلاً ۶).")
        return CUSTOM_REPEAT
    context.user_data["repeat"] = count
    await update.message.reply_text(
        f"🔁 {fa(count)} بار.\n\n⏱ فاصلهٔ بین یادآوری‌ها چقدر باشه؟",
        reply_markup=interval_kb(),
    )
    return INTERVAL


async def got_interval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = update.callback_query.data.split(":", 1)[1]
    if value == "custom":
        await say(update, "⏱ فاصله رو بنویس، مثلاً 20m یا 2h یا «۹۰ دقیقه».")
        return CUSTOM_INTERVAL
    context.user_data["interval"] = int(value)
    await show_confirmation(update, context)
    return CONFIRM


async def got_custom_interval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    minutes = parse_duration(update.message.text or "")
    if minutes is None:
        await update.message.reply_text("متوجه نشدم 🤔 مثلاً بنویس: 20m یا 2h یا «۹۰ دقیقه».")
        return CUSTOM_INTERVAL
    context.user_data["interval"] = minutes
    await show_confirmation(update, context)
    return CONFIRM


async def show_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.user_data
    first = utcnow() + timedelta(minutes=data["delay"])
    last = first + timedelta(minutes=data["interval"] * (data["repeat"] - 1))
    text = (
        "🧾 خلاصهٔ تسک\n\n"
        f"📌 {data['title']}\n"
        f"⏰ اولین یادآوری: {first.astimezone(TZ).strftime('%Y-%m-%d %H:%M')}\n"
        f"🔁 {fa(data['repeat'])} بار، هر {format_minutes(data['interval'])}\n"
        f"🔚 آخرین یادآوری: {last.astimezone(TZ).strftime('%Y-%m-%d %H:%M')}\n\n"
        "ثبتش کنم؟"
    )
    await say(update, text, reply_markup=confirm_kb())


async def confirm_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query.data == "confirm:no":
        context.user_data.clear()
        await say(update, "باشه، چیزی ثبت نشد. هر وقت خواستی /new رو بزن.", reply_markup=main_menu_kb())
        return ConversationHandler.END

    data = context.user_data
    now = utcnow()
    task = storage.add_task(
        chat_id=update.effective_chat.id,
        user_id=update.effective_user.id,
        title=data.get("title", "بدون عنوان"),
        next_at=(now + timedelta(minutes=data["delay"])).isoformat(),
        repeat_count=data["repeat"],
        repeat_interval=data["interval"],
        created_at=now.isoformat(),
    )
    context.user_data.clear()
    await say(
        update,
        f"✅ تسک ثبت شد!\n\n{task_card(task)}\n\n🔔 شمارهٔ تسک: {fa(task.id)}",
        reply_markup=main_menu_kb(),
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.effective_message.reply_text(
        "باشه، لغو شد. هر وقت خواستی /new رو بزن.", reply_markup=main_menu_kb()
    )
    return ConversationHandler.END


async def conversation_hint(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "الان داریم تسک می‌سازیم 🙂\nبرای لغو /cancel رو بزن.",
    )


async def on_task_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    _, action, raw_id = query.data.split(":")
    chat_id = query.message.chat_id
    task = storage.get_task(int(raw_id))
    if task is None or task.chat_id != chat_id:
        await query.answer("این تسک پیدا نشد.", show_alert=True)
        return

    if action == "done":
        storage.set_status(task.id, storage.DONE)
        await query.answer("انجام‌شده ثبت شد ✅")
    else:
        storage.delete_task(task.id)
        await query.answer("حذف شد 🗑")

    tasks = storage.list_tasks(chat_id)
    await query.edit_message_text(render_list(tasks), reply_markup=list_kb(tasks))


async def on_reminder_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    _, action, raw_id = query.data.split(":")
    task = storage.get_task(int(raw_id))
    if task is None or task.chat_id != query.message.chat_id:
        await query.answer("این تسک پیدا نشد.", show_alert=True)
        return

    if action == "done":
        storage.set_status(task.id, storage.DONE)
        suffix = "\n\n✅ انجام شد. آفرین!"
    elif action == "snooze":
        storage.snooze(task.id, (utcnow() + timedelta(minutes=SNOOZE_MINUTES)).isoformat())
        suffix = f"\n\n💤 باشه، {fa(SNOOZE_MINUTES)} دقیقهٔ دیگه دوباره یادت می‌ندازم."
    else:
        storage.stop_reminders(task.id)
        suffix = "\n\n⛔️ یادآوری این تسک متوقف شد."

    await query.answer()
    try:
        await query.edit_message_text(f"{query.message.text or ''}{suffix}", reply_markup=None)
    except TelegramError:
        logger.debug("ویرایش پیام یادآوری ممکن نشد", exc_info=True)


async def send_reminder(bot, task: storage.Task) -> None:
    number = task.sent_count + 1
    lines = [
        f"⏰ یادآوری {fa(number)} از {fa(task.repeat_count)}",
        "",
        f"📌 {task.title}",
        "",
    ]
    if number >= task.repeat_count:
        lines.append("🔔 این آخرین یادآوریه. اگر انجامش دادی، دکمهٔ «انجام شد» رو بزن.")
    else:
        lines.append(f"⏱ یادآوری بعدی: {format_minutes(task.repeat_interval)} دیگه.")
    await bot.send_message(
        chat_id=task.chat_id,
        text="\n".join(lines),
        reply_markup=reminder_kb(task.id),
    )


async def tick(context: ContextTypes.DEFAULT_TYPE) -> None:
    now = utcnow()
    for task in storage.due_tasks(now.isoformat()):
        try:
            await send_reminder(context.bot, task)
        except Forbidden:
            logger.warning("کاربر %s ربات را بلاک کرده است؛ تسک %s متوقف شد", task.chat_id, task.id)
            storage.stop_reminders(task.id)
            continue
        except TelegramError:
            logger.exception("ارسال یادآوری تسک %s نشد", task.id)
            continue

        next_at = next_reminder_at(task, now)
        storage.record_reminder(task.id, next_at, task.sent_count + 1)
        logger.info(
            "یادآوری %s/%s تسک %s فرستاده شد",
            task.sent_count + 1,
            task.repeat_count,
            task.id,
        )


def build_application(token: str) -> Application:
    application = Application.builder().token(token).build()

    conversation = ConversationHandler(
        entry_points=[
            CommandHandler("new", new_task),
            CallbackQueryHandler(new_task, pattern=r"^newtask$"),
        ],
        states={
            TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_title)],
            DELAY: [CallbackQueryHandler(got_delay, pattern=r"^delay:")],
            CUSTOM_DELAY: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_custom_delay)],
            REPEAT: [CallbackQueryHandler(got_repeat, pattern=r"^rep:")],
            CUSTOM_REPEAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_custom_repeat)],
            INTERVAL: [CallbackQueryHandler(got_interval, pattern=r"^ri:")],
            CUSTOM_INTERVAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_custom_interval)],
            CONFIRM: [CallbackQueryHandler(confirm_task, pattern=r"^confirm:")],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.COMMAND, conversation_hint),
        ],
    )

    application.add_handler(conversation)
    application.add_handler(CommandHandler(["start", "menu"], start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("list", show_list))
    application.add_handler(CommandHandler("done", done_command))
    application.add_handler(CommandHandler("del", delete_command))
    application.add_handler(CallbackQueryHandler(show_list, pattern=r"^list$"))
    application.add_handler(CallbackQueryHandler(help_command, pattern=r"^help$"))
    application.add_handler(CallbackQueryHandler(on_task_action, pattern=r"^t:"))
    application.add_handler(CallbackQueryHandler(on_reminder_action, pattern=r"^r:"))

    application.job_queue.run_repeating(tick, interval=TICK_SECONDS, first=5)
    return application


def main() -> None:
    token = (os.getenv("BOT_TOKEN") or "").strip()
    if not token:
        raise SystemExit(
            "توکن ربات پیدا نشد.\n"
            "یک فایل .env بساز (از .env.example کپی کن) و BOT_TOKEN را از @BotFather پر کن."
        )

    storage.init_db()
    application = build_application(token)
    logger.info("ربات آماده است؛ در حال دریافت پیام‌ها…")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
