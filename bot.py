import os
import asyncio
import subprocess
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# --- ТОКЕН ---
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
    await m.answer(
        "Привет! 👋\n\n"
        "Сначала **отправь мне баннер** (гифку, картинку или короткое видео)."
    )

@dp.message(Command("cancel"))
async def cmd_cancel(m: Message):
    user_states[m.from_user.id] = {"step": "wait_banner", "banner_path": None, "video_path": None}
    await m.answer("Сбросил. Начинаем заново! Отправь мне баннер.")

# --- ШАГ 1: БАННЕР ---
@dp.message(F.animation | F.photo | F.document)
async def handle_banner(m: Message):
    uid = m.from_user.id
    state = user_states.get(uid)
    
    if not state:
        user_states[uid] = {"step": "wait_banner", "banner_path": None, "video_path": None}
        state = user_states[uid]

    if state["step"] != "wait_banner":
        await m.answer("Я сейчас жду от тебя видео или ссылку! Если хочешь начать заново, напиши /start")
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
        if ext not in [".mp4", ".gif", ".png", ".jpg", ".jpeg"]:
            await m.answer("Нужен формат .gif, .mp4 или картинка.")
            return
        file_id = m.document.file_id

    banner_path = f"banners/banner_{uid}{ext}"
    f = await bot.get_file(file_id)
    await bot.download_file(f.file_path, banner_path)

    state["banner_path"] = banner_path
    state["step"] = "wait_video"
    await m.answer("Баннер принят! ✅\n\nТеперь **отправь мне видео** (файлом) или **кинь ссылку** (YouTube, TikTok, Instagram).")

# --- ШАГ 2: ВИДЕО (файлом) ---
@dp.message(F.video)
async def handle_video(m: Message):
    uid = m.from_user.id
    state = user_states.get(uid)
    
    if not state or state.get("step") != "wait_video" or not state.get("banner_path"):
        await m.answer("Сначала нажми /start и отправь мне баннер, а потом видео!")
        return

    await m.answer("Скачиваю видео из Telegram...")
    video_path = f"temp/input_{uid}_{m.message_id}.mp4"
    f = await bot.get_file(m.video.file_id)
    await bot.download_file(f.file_path, video_path)

    state["video_path"] = video_path
    state["step"] = "wait_mode"
    await m.answer("Видео загружено! Выбери, как показать баннер:", reply_markup=get_mode_kb())

# --- ШАГ 2.5: ВИДЕО (ссылкой) ---
@dp.message(F.text.startswith("http"))
async def handle_link(m: Message):
    uid = m.from_user.id
    state = user_states.get(uid)
    
    if not state or state.get("step") != "wait_video" or not state.get("banner_path"):
        await m.answer("Сначала нажми /start и отправь мне баннер, а потом ссылку!")
        return

    msg = await m.answer("Скачиваю видео по ссылке... Это может занять пару минут.")
    video_path = f"temp/input_{uid}_{m.message_id}.mp4"
    
    # Скачиваем через yt-dlp
    ydl_cmd = ["yt-dlp", "-f", "bestvideo[height<=1080]+bestaudio/best", "--merge-output-format", "mp4", "-o", video_path, m.text]
    try:
        await asyncio.to_thread(subprocess.run, ydl_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        await msg.edit_text("Не удалось скачать видео по ссылке. Возможно, оно приватное или ссылка неверная.")
        return

    state["video_path"] = video_path
    state["step"] = "wait_mode"
    await msg.edit_text("Видео скачано! Выбери, как показать баннер:", reply_markup=get_mode_kb())

# --- ШАГ 3: ВЫБОР РЕЖИМА ---
@dp.callback_query(F.data.startswith("mode_"))
async def handle_mode(cb: CallbackQuery):
    uid = cb.from_user.id
    state = user_states.get(uid)
    if not state: return

    await cb.answer()
    state["mode"] = cb.data.replace("mode_", "")
    state["step"] = "wait_pos"
    await cb.message.edit_text("Где разместить баннер?", reply_markup=get_pos_kb())

# --- ШАГ 4: ВЫБОР ПОЗИЦИИ ---
@dp.callback_query(F.data.startswith("pos_"))
async def handle_pos(cb: CallbackQuery):
    uid = cb.from_user.id
    state = user_states.get(uid)
    if not state: return

    await cb.answer()
    state["pos"] = cb.data
    state["step"] = "wait_timing"
    
    await cb.message.edit_text(
        "Отлично! Теперь напиши мне два числа через пробел:\n"
        "**Секунда появления** и **Длительность**.\n\n"
        "Пример: `20 6` (баннер появится на 20 секунде и продержится 6 секунд)."
    )

# --- ШАГ 5: ВРЕМЯ И ДЛИТЕЛЬНОСТЬ ---
@dp.message(F.text)
async def handle_timing(m: Message):
    uid = m.from_user.id
    state = user_states.get(uid)
    
    if not state or state.get("step") != "wait_timing":
        return
    
    try:
        parts = m.text.replace(",", ".").split()
        start_sec = float(parts[0])
        duration = float(parts[1])
        if start_sec < 0 or duration <= 0:
            raise ValueError
    except:
        await m.answer("Пожалуйста, напиши два числа через пробел. Например: `20 6`")
        return
        
    state["step"] = "processing"
    state["start_sec"] = start_sec
    state["duration"] = duration
    
    await m.answer(f"Монтирую (с {start_sec} сек., длительность {duration} сек.)...")
    await run_montage(m, uid)

# --- ГЛАВНАЯ ФУНКЦИЯ СБОРКИ ---
async def run_montage(msg: Message, uid: int):
    state = user_states.get(uid)
    if not state: return
        
    inp = state["video_path"]
    bn = state["banner_path"]
    mode = state["mode"]
    pos = state["pos"]
    start = state["start_sec"]
    dur = state["duration"]
    
    end = start + dur
    fpath = f"temp/final_{uid}_{msg.message_id}.mp4"
    
    coords_map = {"pos_top": "0:150", "pos_center": "0:(H-h)/2", "pos_bottom": "0:1050"}
    coords = coords_map.get(pos, "0:(H-h)/2")
    
    largs = ["-ignore_loop", "0"] if bn.lower().endswith((".gif", ".png", ".jpg", ".jpeg")) else ["-stream_loop", "-1"]
    
    try:
        if mode == "overlay":
            cmd = ["ffmpeg", "-y", "-threads", "2", "-i", inp, *largs, "-i", bn, 
                   "-filter_complex", f"[1:v]scale=1080:-1[bn];[0:v][bn]overlay={coords}:enable='between(t,{start},{end})'[v]", 
                   "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "24", "-c:a", "copy", fpath]
            await asyncio.to_thread(subprocess.run, cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
        else:
            p1 = f"temp/p1_{uid}.mp4"
            p2 = f"temp/p2_{uid}.mp4"
            pause_vid = f"temp/pause_vid_{uid}.mp4"
            
            c1 = ["ffmpeg", "-y", "-threads", "2", "-i", inp, "-t", str(start), "-c", "copy", p1]
            c2 = ["ffmpeg", "-y", "-threads", "2", "-ss", str(start), "-i", inp, "-c", "copy", p2]
            
            c3 = ["ffmpeg", "-y", "-threads", "2", "-ss", str(start), "-i", inp, "-vframes", "1", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", *largs, "-i", bn, 
                  "-filter_complex", f"[0:v]loop=loop=-1:size=1,setpts=N/(30*TB)[bg];[2:v]scale=1080:-1[bn];[bg][bn]overlay={coords}:shortest=1[v]", 
                  "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "24", "-c:a", "aac", "-t", str(dur), pause_vid]
            
            c4 = ["ffmpeg", "-y", "-threads", "2", "-i", p1, "-i", pause_vid, "-i", p2, "-filter_complex", "[0:v][0:a][1:v][1:a][2:v][2:a]concat=n=3:v=1:a=1[v][a]", "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "24", "-c:a", "aac", fpath]
            
            for sc in (c1, c2, c3, c4):
                await asyncio.to_thread(subprocess.run, sc, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                
            for tf in (p1, p2, pause_vid):
                if os.path.exists(tf): os.remove(tf)
                    
        await msg.answer_video(FSInputFile(fpath))
        await msg.answer("Готово! Видео обработано.")
        
    except Exception as e:
        await msg.edit_text(f"Ошибка: {e}")
    finally:
        if os.path.exists(inp): os.remove(inp)
        if os.path.exists(fpath): os.remove(fpath)
        user_states[uid] = {"step": "wait_banner", "banner_path": None, "video_path": None}

async def handle(request):
    return web.Response(text="Bot is running!")

async def main():
    print("Бот запущен!")
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
