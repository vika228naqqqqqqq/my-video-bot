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

def get_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1. Сверху видео (всегда)", callback_data="pos_top")],
        [InlineKeyboardButton(text="2. В середине видео (всегда)", callback_data="pos_center")],
        [InlineKeyboardButton(text="3. Внизу видео (всегда)", callback_data="pos_bottom")],
        [InlineKeyboardButton(text="4. Остановить видео (пауза)", callback_data="pos_pause")],
    ])

def get_pause_pos_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Сверху", callback_data="p_pos_top")],
        [InlineKeyboardButton(text="В середине", callback_data="p_pos_center")],
        [InlineKeyboardButton(text="Внизу", callback_data="p_pos_bottom")],
    ])

@dp.message(Command("start"))
async def cmd_start(m: Message):
    user_states[m.from_user.id] = {"step": "wait_banner", "banner_path": None, "video_path": None}
    await m.answer(
        "Привет! 👋\n\n"
        "Сначала **отправь мне баннер** (гифку, картинку или короткое видео).\n"
        "Потом я попрошу видео, и мы сделаем магию!"
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
        await m.answer("Я сейчас жду от тебя видео! Если хочешь начать заново, напиши /start")
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
    await m.answer("Баннер принят! ✅\n\nТеперь **отправь мне видео**, на которое я наложу этот баннер.")

# --- ШАГ 2: ВИДЕО ---
@dp.message(F.video)
async def handle_video(m: Message):
    uid = m.from_user.id
    state = user_states.get(uid)
    
    if not state or state.get("step") != "wait_video" or not state.get("banner_path"):
        await m.answer("Сначала нажми /start и отправь мне баннер, а потом видео!")
        return

    await m.answer("Скачиваю видео...")
    video_path = f"temp/input_{uid}_{m.message_id}.mp4"
    f = await bot.get_file(m.video.file_id)
    await bot.download_file(f.file_path, video_path)

    state["video_path"] = video_path
    state["step"] = "wait_action"
    await m.answer("Видео загружено! Выбери, что сделать с баннером:", reply_markup=get_kb())

# --- ШАГ 3: ВЫБОР ДЕЙСТВИЯ ---
@dp.callback_query(F.data.startswith("pos_"))
async def handle_cb(cb: CallbackQuery):
    uid = cb.from_user.id
    state = user_states.get(uid)
    
    if not state or state.get("step") != "wait_action":
        await cb.message.edit_text("Видео устарело. Нажми /start и отправь заново.")
        await cb.answer()
        return
    
    await cb.answer()
    
    if cb.data == "pos_pause":
        state["step"] = "wait_pause_sec"
        await cb.message.edit_text("На сколько секунд остановить видео? Напиши число (например: 3):")
        return
        
    pmap = {"pos_top": ("0:150", "сверху"), "pos_center": ("0:(H-h)/2", "в середине"), "pos_bottom": ("0:1050", "внизу")}
    coords, lbl = pmap[cb.data]
    state["step"] = "processing"
    await cb.message.edit_text(f"Монтирую (баннер {lbl} на всё видео)...")
    await run_montage(cb.message, uid, "overlay", coords)

# --- ШАГ 4: ВРЕМЯ ПАУЗЫ ---
@dp.message(F.text)
async def handle_sec(m: Message):
    uid = m.from_user.id
    state = user_states.get(uid)
    
    if not state or state.get("step") != "wait_pause_sec":
        return
    
    try:
        sec = float(m.text.replace(",", ".").strip())
        if sec <= 0 or sec > 30:
            raise ValueError
    except ValueError:
        await m.answer("Введи число от 1 до 30 (например: 4).")
        return
        
    state["pause_sec"] = sec
    state["step"] = "wait_pause_pos"
    await m.answer("Отлично! Теперь выбери, где будет баннер во время паузы:", reply_markup=get_pause_pos_kb())

# --- ШАГ 5: ВЫБОР ПОЗИЦИИ ДЛЯ ПАУЗЫ ---
@dp.callback_query(F.data.startswith("p_pos_"))
async def handle_pause_pos(cb: CallbackQuery):
    uid = cb.from_user.id
    state = user_states.get(uid)
    
    if not state or state.get("step") != "wait_pause_pos":
        await cb.message.edit_text("Что-то пошло не так. Начни заново с /start")
        await cb.answer()
        return

    await cb.answer()
    state["step"] = "processing"
    
    pos_map = {"p_pos_top": "0:150", "p_pos_center": "0:(H-h)/2", "p_pos_bottom": "0:1050"}
    coords = pos_map[cb.data]
    sec = state["pause_sec"]
    
    await cb.message.edit_text(f"Делаю паузу на {sec} сек. и вставляю баннер...")
    await run_montage(cb.message, uid, "pause", coords=coords, pause_sec=sec)


# --- ГЛАВНАЯ ФУНКЦИЯ СБОРКИ ВИДЕО (БЕЗ НАРЕЗКИ НА КУСКИ) ---
async def run_montage(msg: Message, uid: int, mode: str, coords: str = "0:1050", pause_sec: float = 3.0):
    state = user_states.get(uid)
    if not state:
        return
        
    inp = state["video_path"]
    bn = state["banner_path"]
    mid_id = msg.message_id
    fpath = f"temp/final_{uid}_{mid_id}.mp4"
    
    # Для GIF и картинок - один цикл, для видео - зацикливаем, если нужно
    largs = ["-ignore_loop", "0"] if bn.lower().endswith((".gif", ".png", ".jpg", ".jpeg")) else ["-stream_loop", "-1"]
    
    try:
        if mode == "overlay":
            # Наложение на всё видео
            cmd = ["ffmpeg", "-y", "-threads", "2", "-i", inp, *largs, "-i", bn, "-filter_complex", f"[1:v]scale=1080:-1[bn];[0:v][bn]overlay={coords}:shortest=1[v]", "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "24", "-c:a", "copy", fpath]
            await asyncio.to_thread(subprocess.run, cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
        else:
            # Пауза (4-й пункт). Берем середину видео и замораживаем.
            # Узнаем длительность видео
            dur_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", inp]
            dur_res = await asyncio.to_thread(subprocess.run, dur_cmd, capture_output=True, text=True)
            total_dur = float(dur_res.stdout.strip()) if dur_res.stdout.strip() else 10.0
            h = total_dur / 2
            
            p1 = f"temp/p1_{uid}_{mid_id}.mp4"
            p2 = f"temp/p2_{uid}_{mid_id}.mp4"
            pause_vid = f"temp/pause_vid_{uid}_{mid_id}.mp4"
            
            # 1. Режем на 2 части
            c1 = ["ffmpeg", "-y", "-threads", "2", "-i", inp, "-t", str(h), "-c", "copy", p1]
            c2 = ["ffmpeg", "-y", "-threads", "2", "-ss", str(h), "-i", inp, "-c", "copy", p2]
            
            # 2. Кусок с паузой (1 кадр зацикливаем)
            c3 = ["ffmpeg", "-y", "-threads", "2", "-ss", str(h), "-i", inp, "-vframes", "1", "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo", *largs, "-i", bn, "-filter_complex", f"[0:v]loop=loop=-1:size=1:start=0,setpts=N/(30*TB)[bg];[2:v]scale=1080:-1[bn];[bg][bn]overlay={coords}:shortest=1[v]", "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "24", "-c:a", "aac", "-t", str(pause_sec), pause_vid]
            
            # 3. Склеиваем
            c4 = ["ffmpeg", "-y", "-threads", "2", "-i", p1, "-i", pause_vid, "-i", p2, "-filter_complex", "[0:v][0:a][1:v][1:a][2:v][2:a]concat=n=3:v=1:a=1[v][a]", "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "24", "-c:a", "aac", fpath]
            
            for sc in (c1, c2, c3, c4):
                await asyncio.to_thread(subprocess.run, sc, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                
            for tf in (p1, p2, pause_vid):
                if os.path.exists(tf):
                    os.remove(tf)
                    
        await msg.answer_video(FSInputFile(fpath))
        await msg.answer("Готово! Видео обработано.")
        
    except Exception as e:
        await msg.edit_text(f"Ошибка: {e}")
    finally:
        if os.path.exists(inp):
            os.remove(inp)
        if os.path.exists(fpath):
            os.remove(fpath)
        user_states[uid] = {"step": "wait_banner", "banner_path": None, "video_path": None}

async def handle(request):
    return web.Response(text="Bot is running!")

async def main():
    print("Новый бот с кнопками успешно запущен!")
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
