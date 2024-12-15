import logging
import json
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from telethon import TelegramClient
from telethon.tl.functions.messages import ReportRequest
from telethon.tl.types import InputReportReasonSpam, InputReportReasonViolence, InputReportReasonPornography, InputReportReasonChildAbuse, InputReportReasonOther
from urllib.parse import urlparse

API_TOKEN = '7501860705:AAEPuThmAoVhCFnqkBPGKJ9EENi70vnbszs'
API_ID = '28234677'
API_HASH = 'e7c47bee153e7c54524d4086c650027d'
SESSION_FOLDER = 'sessions'
USERS_DB = 'users.json'
COOLDOWN_MINUTES = 5
LOG_CHAT_ID = '-1002455827700'
admin_id = '721151979'

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()

class ReportStates(StatesGroup):
    waiting_for_link = State()
    waiting_for_confirmation = State()

clients = []
stop_reports = False

reasons = {
    "spam": InputReportReasonSpam(),
    "violence": InputReportReasonViolence(),
    "porn": InputReportReasonPornography(),
    "child": InputReportReasonChildAbuse(),
    "other": InputReportReasonOther()
}

def load_users():
    try:
        with open(USERS_DB, 'r') as file:
            return json.load(file)
    except FileNotFoundError:
        return {}

def save_users(users):
    with open(USERS_DB, 'w') as file:
        json.dump(users, file, indent=4)

async def check_cooldown(user_id):
    users = load_users()
    user = users.get(str(user_id), {})
    last_report_time = user.get('last_report_time')
    
    if last_report_time:
        last_report = datetime.fromisoformat(last_report_time)
        time_since_last_report = datetime.now() - last_report
        if time_since_last_report < timedelta(minutes=COOLDOWN_MINUTES):
            remaining_minutes = COOLDOWN_MINUTES - int(time_since_last_report.total_seconds() / 60)
            return False, remaining_minutes
    
    return True, 0

async def update_last_report_time(user_id):
    users = load_users()
    users[str(user_id)] = users.get(str(user_id), {})
    users[str(user_id)]['last_report_time'] = datetime.now().isoformat()
    save_users(users)

async def subscription_required(message):
    users = load_users()
    user = users.get(str(message.from_user.id), {})
    if not user.get('subscription'):
        await message.answer("У вас нет активной подписки. Пожалуйста, приобретите подписку для использования этой функции.")
        return False
    return True

async def analyze_account(user_id, message_text):
    return 75  

async def send_log(log_message):
    print(f"Log: {log_message}")

async def load_clients():
    global clients
    if not clients:
        for session_file in os.listdir(SESSION_FOLDER):
            if session_file.endswith('.session'):
                client = TelegramClient(os.path.join(SESSION_FOLDER, session_file), API_ID, API_HASH)
                await client.start()
                clients.append(client)
    return clients

@router.callback_query(F.data == "botnet")
async def botnet_handler(call: CallbackQuery):
    if not await subscription_required(call.message):
        return
    
    instruction_text = "Пропиши /rp для отправки жалобы. /rp {ссылка на сообщение} [причина]"
    await call.message.edit_text(instruction_text)
    await ReportStates.waiting_for_link.set()

@router.message(Command("rp"))
async def send_mass_reports(message: Message, state: FSMContext):
    user_id = message.from_user.id

    is_allowed, remaining_minutes = await check_cooldown(user_id)
    if not is_allowed:
        await message.reply(f"⏳ Подождите {remaining_minutes} минут перед отправкой следующей жалобы.")
        return

    if not await subscription_required(message):
        return

    command = message.text.split()
    if len(command) < 2:
        await message.reply("❌ Неправильный формат! Используйте `/rp {ссылка на сообщение} [причина]`.")
        return

    message_url = command[1]
    reason = ' '.join(command[2:]) if len(command) > 2 else 'spam'

    removal_chance = await analyze_account(user_id, message.text)

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, продолжить", callback_data='confirm_report')],
        [InlineKeyboardButton(text="❌ Нет, отменить", callback_data='cancel_report')]
    ])

    await message.reply(
        f"🔍 Вероятность сноса аккаунта: {removal_chance}%\n"
        f"Причина жалобы: {reason}\n"
        f"Вы точно хотите продолжить?",
        reply_markup=markup
    )

    await state.update_data(message_url=message_url, reason=reason)
    await ReportStates.waiting_for_confirmation.set()

@router.callback_query(ReportStates.waiting_for_confirmation)
async def confirm_report_handler(call: CallbackQuery, state: FSMContext):
    global stop_reports
    if call.data == "confirm_report":
        stop_reports = False
        await call.message.edit_text("🚀 Отправка жалоб началась...")
        data = await state.get_data()
        await start_reporting_process(call.message, data['message_url'], data['reason'])
    elif call.data == "cancel_report":
        await call.message.edit_text("❌ Вы прекратили снос.")
    await state.clear()

async def start_reporting_process(message, message_url, reason):
    global stop_reports, clients

    if not clients:
        clients = await load_clients()

    parts = message_url.split('/')
    if len(parts) < 3:
        await message.reply("❌ Неверный формат ссылки.")
        return

    chat_username = parts[-2]
    message_id = int(parts[-1])

    total_reports = 0
    total_failed = 0

    stop_button = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Остановить", callback_data='stop_reports')]
    ])
    progress_message = await message.reply("🚀 Прогресс отправки жалоб...", reply_markup=stop_button)

    logging.info(f"Начало отправки жалоб на сообщение {message_id} в чате {chat_username}")

    for client in clients:
        if stop_reports:
            logging.info("Отправка жалоб остановлена пользователем.")
            await progress_message.edit_text("🚫 Отправка жалоб остановлена.")
            return

        success, victim_username, victim_id = await report_message(client, chat_username, message_id, reason)

        if success:
            total_reports += 1
        else:
            total_failed += 1

        await progress_message.edit_text(
            f"🚀 Отправка жалоб...\n"
            f"✅ Успешно отправлено: {total_reports}\n"
            f"❌ Ошибок: {total_failed}",
            reply_markup=stop_button
        )

    await progress_message.delete()

    log_message = (
        f"👤 Жалоба от пользователя: {message.from_user.username} (ID: {message.from_user.id})\n"
        f"💬 На сообщение с ID: {message_id}\n"
        f"📌 Чат: {chat_username}\n"
        f"🔗 Ссылка: {message_url}\n"
        f"📊 Статус жалоб:\n"
        f"✅ Успешно отправлено: {total_reports}\n"
        f"❌ Ошибок: {total_failed}"
    )
    logging.info(log_message)
    await send_log(log_message)

    await message.answer_photo(
        photo="path/to/Flopi.png",
        caption=f"🎉 Все жалобы успешно отправлены!\n"
                f"✅ Успешно: {total_reports}\n"
                f"❌ Ошибок: {total_failed}"
    )

    await update_last_report_time(message.from_user.id)

@router.callback_query(F.data == "stop_reports")
async def stop_reports_handler(call: CallbackQuery):
    global stop_reports
    stop_reports = True
    await call.message.edit_text("⏸️ Отправка жалоб приостановлена.")

async def report_message(client, chat_username, message_id, reason):
    try:
        peer = await client.get_entity(chat_username)
        message = await client.get_messages(peer, ids=message_id)

        report_reason = reasons.get(reason.lower(), InputReportReasonSpam())
        result = await client(ReportRequest(
            peer=peer,
            id=[message_id],
            reason=report_reason,
            message='Отправка жалобы'
        ))

        victim_username = message.sender.username if message.sender else "Неизвестно"
        victim_id = message.sender_id if message.sender_id else "Неизвестно"

        return result, victim_username, victim_id

    except Exception as e:
        logging.error(f"Ошибка при отправке жалобы: {e}")
        return False, None, None

dp.include_router(router)

if __name__ == '__main__':
    from aiogram import executor
    if not os.path.exists(SESSION_FOLDER):
        os.makedirs(SESSION_FOLDER)
    executor.start_polling(dp, skip_updates=True)