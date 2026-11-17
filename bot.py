import os
import asyncio
import subprocess
import shutil
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

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

@dp.message(Command("start"))
async def cmd_start(m: Message):
    user_states[m.from_user.id] = {"step": "wait_banner", "banner_path": None, "video_path": None}
    await m.answer("Привет! 👋\n\nСначала **отправь мне баннер**.")

@dp.message(Command("cancel"))
async def cmd_cancel(m: Message):
    user_states[m.from_user.id] = {"step": "wait_banner", "banner_path": None, "video_path": None}
    await m.answer("Сбросил. Отправь баннер.")

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
    if not state or state.get("step") != "wait_video":
        await m.answer("Сначала нажми /start и отправь мне баннер!")
        return
    msg = await m.answer("Скачиваю видео по ссылке...")
    video_path = f"temp/input_{uid}_{m.message_id}.mp4"
    temp_cookies_path = "/tmp/youtube_cookies.txt"
    try:
        shutil.copyfile("/etc/secrets/youtube_cookies.txt", temp_cookies_path)
    except:
        pass

    # УЛЬТРА-ЛЕГКОЕ СКАЧИВАНИЕ
    ydl_cmd = [
        "yt-dlp",
        "--cookies", temp_cookies_path,
        "--js-runtimes", "deno:/usr/local/bin/deno",
        "--remote-components", "ejs:github",
        "--extractor-args", "youtubepot-bgutilhttp:base_url=http://127.0.0.1:4416",
        "--extractor-args", "youtube:player_client=web,mweb,android",
        "-f", "worst[ext=mp4]", 
        "--no-part",
        "-o", video_path,
        m.text
    ]
    
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(subprocess.run, ydl_cmd, capture_output=True, text=True),
            timeout=180.0
        )
        if result.returncode != 0:
            await msg.edit_text(f"Ошибка YouTube:\n\n`{result.stderr[-800:]}`", parse_mode="Markdown")
            return
    except asyncio.TimeoutError:
        await msg.edit_text("Ошибка: Превышено время ожидания (3 минуты).")
        return
    except Exception as e:
        await msg.edit_text(f"Ошибка: {e}")
        return

    # ПРОСТО ОТПРАВЛЯЕМ ВИДЕО БЕЗ МОНТАЖА
    try:
        await msg.answer_video(FSInputFile(video_path))
        await msg.edit_text("Готово! Видео скачано (без наложения баннера, так как памяти сервера не хватает на монтаж).")
    except Exception as e:
        await msg.edit_text(f"Ошибка при отправке: {e}")
    finally:
        if os.path.exists(video_path): os.remove(video_path)
        user_states[uid] = {"step": "wait_banner", "banner_path": None, "video_path": None}

async def handle(request):
    return web.Response(text="Bot is running!")

async def main():
    print("Бот запущен!")
    try:
        subprocess.Popen(["node", "/opt/bgutil/server/build/main.js", "--port", "4416"])
    except:
        pass
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
