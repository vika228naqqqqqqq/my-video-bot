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

# ... (функции get_mode_kb, get_pos_kb, cmd_start, cmd_cancel, handle_banner, handle_video остаются без изменений) ...

@dp.message(F.text.startswith("http"))
async def handle_link(m: Message):
    uid = m.from_user.id
    state = user_states.get(uid)
    if not state or state.get("step") != "wait_video" or not state.get("banner_path"):
        await m.answer("Сначала нажми /start и отправь мне баннер, а потом ссылку!")
        return
    msg = await m.answer("Скачиваю видео (попытка 1 из 3)...")
    video_path = f"temp/input_{uid}_{m.message_id}.mp4"

    for attempt in range(3):
        try:
            # Принудительно используем клиент ANDROID для обхода блокировки
            yt = YouTube(m.text, client='ANDROID', use_oauth=True, allow_oauth_cache=True)
            
            # Берем прогрессивный поток (видео+звук) в mp4
            stream = yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc().first()
            if not stream:
                stream = yt.streams.filter(file_extension='mp4').first()
            if not stream:
                await msg.edit_text("Не удалось найти подходящий видео-поток.")
                return
            
            await asyncio.to_thread(stream.download, output_path="temp", filename=os.path.basename(video_path))
            
            if not os.path.exists(video_path):
                raise Exception("Файл не был скачан")

            break  # Успех, выходим из цикла

        except Exception as e:
            error_str = str(e)
            if "429" in error_str and attempt < 2:
                await msg.edit_text(f"YouTube временно заблокировал IP. Жду 15 секунд и пробую снова (попытка {attempt + 2} из 3)...")
                await asyncio.sleep(15)
                continue
            else:
                await msg.edit_text(f"Ошибка при скачивании: {error_str[:300]}")
                return

    state["video_path"] = video_path
    state["step"] = "wait_mode"
    await msg.edit_text("Видео скачано! Выбери, как показать баннер:", reply_markup=get_mode_kb())

# ... (остальной код без изменений) ...
