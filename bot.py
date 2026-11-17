import os
import asyncio
import subprocess
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pytubefix import YouTube

TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    try:
        with open("token.txt", "r", encoding="utf-8") as f:
            TOKEN = f.read().strip()
    except FileNotFoundError:
        raise RuntimeError("Токен не найден! Задай переменную BOT_TOKEN")

bot = Bot(token=TOKEN)
dp = Dispatcher()
os.makedirs("temp", exist_ok=True)
os.makedirs("banners", exist_ok=True)
user_states = {}

# --- НАСТРОЙКА ПРОКСИ (при необходимости) ---
# Если у тебя есть прокси, раскомментируй и укажи его здесь:
# PROXY = "http://username:password@proxy_host:proxy_port"
PROXY = None # Пока не используется

def get_mode_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1. Наложить поверх (видео идет)", callback_data="mode_overlay")],
        [InlineKeyboardButton(text="2. Поставить на паузу (видео замирает)", callback_data="mode_pause")],
    ])

def get_pos_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Сверху", callback_data="pos_top")],
        [InlineKeyboardButton(text="В середине", callback_data="pos_center")],
        [InlineKeyboardButton(text="Внизу", callback_data="pos_bottom")],
    ])

@dp.message(Command("start"))
async def cmd_start(m: Message):
    user_states[m.from_user.id] = {"step": "wait_banner", "banner_path": None, "video_path": None}
    await m.answer("Привет! 👋\n\nСначала **отправь мне баннер** (гифку, картинку или короткое видео).")

@dp.message(Command("cancel"))
async def cmd_cancel(m: Message):
    user_states[m.from_user.id] = {"step": "wait_banner", "banner_path": None, "video_path": None}
    await m.answer("Сбросил. Начинаем заново! Отправь мне баннер.")

@dp.message(F.animation | F.photo | F.document)
async def handle_banner(m: Message):
    uid = m.from_user.id
    state = user_states.get(uid)
    if not state:
        user_states[uid] = {"step": "wait_banner", "banner_path": None, "video_path": None}
        state = user_states[uid]
    if state["step"] != "wait_banner":
        return
    await m.answer("Сохраняю баннер...")
    if m.animation:
        ext = ".mp4"
        file_id = m.animation.file_id
    elif m.photo:
        ext = ".jpg"
        file_id = m.photo[-1].file_id
    else:
        ext = os.path.splitext(m.document.file_name)[-1].lower()
        file_id = m.document.file_id
    banner_path = f"banners/banner_{uid}{ext}"
    f = await bot.get_file(file_id)
    await bot.download_file(f.file_path, banner_path)
    state["banner_path"] = banner_path
    state["step"] = "wait_video"
    await m.answer("Баннер принят! ✅\n\nТеперь **отправь мне ссылку** на YouTube.")

@dp.message(F.text.startswith("http"))
async def handle_link(m: Message):
    uid = m.from_user.id
    state = user_states.get(uid)
    if not state or state.get("step") != "wait_video" or not state.get("banner_path"):
        await m.answer("Сначала нажми /start и отправь мне баннер, а потом ссылку!")
        return
    msg = await m.answer("Скачиваю видео... Это займет около минуты.")
    video_path = f"temp/input_{uid}_{m.message_id}.mp4"

    try:
        # --- ИСПОЛЬЗУЕМ ПРОКСИ И КУКИ (если настроены) ---
        proxies = None
        if PROXY:
            proxies = {"http": PROXY, "https": PROXY}

        # Создаем объект YouTube с прокси (если есть)
        yt = YouTube(
            m.text,
            proxies=proxies,  # Использование прокси для обхода блокировки по IP[reference:5]
            use_oauth=True,   # Включаем OAuth для авторизации
            allow_oauth_cache=True # Кэшируем токены, чтобы не запрашивать каждый раз[reference:6]
        )

        # Выбираем лучшее качество, но не тяжелее 720p
        stream = yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc().first()
        
        if not stream:
            stream = yt.streams.filter(file_extension='mp4').first()

        if not stream:
            await msg.edit_text("Не удалось найти подходящий видео-поток.")
            return

        # Скачиваем в отдельном потоке, чтобы не блокировать бота
        await asyncio.to_thread(stream.download, output_path="temp", filename=os.path.basename(video_path))
        
        if not os.path.exists(video_path):
            await msg.edit_text("Ошибка: файл не был скачан.")
            return

    except Exception as e:
        await msg.edit_text(f"Ошибка при скачивании: {str(e)[:300]}")
        return

    state["video_path"] = video_path
    state["step"] = "wait_mode"
    await msg.edit_text("Видео скачано! Выбери, как показать баннер:", reply_markup=get_mode_kb())

# ... (остальной код для монтажа и обработки кнопок остается без изменений) ...
