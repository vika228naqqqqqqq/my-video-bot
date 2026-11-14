import os
import random
import asyncio
import subprocess
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    try:
        with open("token.txt", "r", encoding="utf-8") as f:
            TOKEN = f.read().strip()
    except FileNotFoundError:
        raise RuntimeError("Токен не найден!")
    
CLIP_DURATION = 12
bot = Bot(token=TOKEN)
dp = Dispatcher()
os.makedirs("temp", exist_ok=True)
os.makedirs("banners", exist_ok=True)
user_state = {}

def get_banners():
    return [os.path.join("banners", f) for f in os.listdir("banners") if f.lower().endswith((".gif", ".png", ".jpg", ".jpeg", ".mp4"))]

def get_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1. Сверху видео", callback_data="pos_top")],
        [InlineKeyboardButton(text="2. В середине видео", callback_data="pos_center")],
        [InlineKeyboardButton(text="3. Внизу видео", callback_data="pos_bottom")],
        [InlineKeyboardButton(text="4. Остановить видео и вставить баннер", callback_data="pos_pause")],
    ])

@dp.message(Command("start"))
async def cmd_start(m: Message):
    await m.answer(f"Привет! Баннеров: {len(get_banners())} шт.\n1. Кидай гифки-баннеры.\n2. Отправь видео (до 20 МБ).\n3. Выбери позицию кнопкой.\n\n/count — количество\n/clear — очистить")

@dp.message(Command("count"))
async def cmd_count(m: Message):
    await m.answer(f"Загружено баннеров: {len(get_banners())} шт.")

@dp.message(Command("clear"))
async def cmd_clear(m: Message):
    for f in get_banners():
        os.remove(f)
    await m.answer("Старые баннеры удалены!")

@dp.message(F.animation)
async def handle_anim(m: Message):
    p = os.path.join("banners", f"{m.message_id}_anim.mp4")
    f = await bot.get_file(m.animation.file_id)
    await bot.download_file(f.file_path, p)
    await m.answer(f"Гифка добавлена! Всего: {len(get_banners())} шт.")

@dp.message(F.document)
async def handle_doc(m: Message):
    fn = m.document.file_name or ""
    if not fn.lower().endswith((".gif", ".png", ".jpg", ".jpeg", ".mp4")):
        await m.answer("Нужен формат .gif, .mp4 или .png.")
        return
    p = os.path.join("banners", f"{m.message_id}_{fn}")
    f = await bot.get_file(m.document.file_id)
    await bot.download_file(f.file_path, p)
    await m.answer(f"Баннер добавлен! Всего: {len(get_banners())} шт.")

@dp.message(F.photo)
async def handle_photo(m: Message):
    p = os.path.join("banners", f"{m.message_id}_photo.jpg")
    f = await bot.get_file(m.photo[-1].file_id)
    await bot.download_file(f.file_path, p)
    await m.answer(f"Картинка добавлена! Всего: {len(get_banners())} шт.")

@dp.message(F.video)
async def handle_video(m: Message):
    if not get_banners():
        await m.answer("Сначала отправь хотя бы одну гифку-баннер!")
        return
    uid = m.from_user.id
    old = user_state.get(uid)
    if old and os.path.exists(old.get("input_path", "")):
        os.remove(old["input_path"])
    st = await m.answer("Скачиваю видео...")
    inp = f"temp/input_{uid}_{m.message_id}.mp4"
    f = await bot.get_file(m.video.file_id)
    await bot.download_file(f.file_path, inp)
    user_state[uid] = {"input_path": inp, "msg_id": m.message_id, "wait": False}
    await st.edit_text("Выберите где будет находиться баннер:", reply_markup=get_kb())

@dp.callback_query(F.data.startswith("pos_"))
async def handle_cb(cb: CallbackQuery):
    uid = cb.from_user.id
    st = user_state.get(uid)
    if not st or not os.path.exists(st.get("input_path", "")):
        await cb.message.edit_text("Видео устарело. Отправь заново.")
        await cb.answer()
        return
    await cb.answer()
    if cb.data == "pos_pause":
        st["wait"] = True
        await cb.message.edit_text("На сколько секунд остановить видео? Напиши число (например: 3):")
        return
    pmap = {"pos_top": ("0:150", "сверху"), "pos_center": ("0:(H-h)/2", "в середине"), "pos_bottom": ("0:1050", "внизу")}
    coords, lbl = pmap[cb.data]
    await cb.message.edit_text(f"Монтирую (баннер {lbl})...")
    await run_montage(cb.message, uid, "overlay", coords)

@dp.message(F.text)
async def handle_sec(m: Message):
    uid = m.from_user.id
    st = user_state.get(uid)
    if not st or not st.get("wait"):
        return
    try:
        sec = float(m.text.replace(",", ".").strip())
        if sec <= 0 or sec > 30:
            raise ValueError
    except ValueError:
        await m.answer("Введи число от 1 до 30 (например: 4).")
        return
    st["wait"] = False
    msg = await m.answer(f"Делаю вставку на {sec} сек. в середину каждого клипа...")
    await run_montage(msg, uid, "pause", pause_sec=sec)

async def run_montage(msg: Message, uid: int, mode: str, coords: str = "0:1050", pause_sec: float = 3.0):
    st = user_state.get(uid)
    if not st:
        return
    inp, mid_id = st["input_path"], st["msg_id"]
    banners = get_banners()
    raw_pat = f"temp/raw_{uid}_{mid_id}_%03d.mp4"
    split_cmd = ["ffmpeg", "-y", "-threads", "2", "-i", inp, "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "24", "-c:a", "aac", "-ar", "44100", "-ac", "2", "-f", "segment", "-segment_time", str(CLIP_DURATION), "-reset_timestamps", "1", raw_pat]
    try:
        await asyncio.to_thread(subprocess.run, split_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        clips = sorted([f for f in os.listdir("temp") if f.startswith(f"raw_{uid}_{mid_id}_") and f.endswith(".mp4")])
        await msg.edit_text(f"Кусков: {len(clips)}. Собираю ролики...")
        for i, rname in enumerate(clips, 1):
            rpath = os.path.join("temp", rname)
            fpath = os.path.join("temp", f"final_{uid}_{mid_id}_{i:03d}.mp4")
            bn = random.choice(banners)
            largs = ["-ignore_loop", "0"] if bn.lower().endswith(".gif") else ["-stream_loop", "-1"]
            if mode == "overlay":
                cmd = ["ffmpeg", "-y", "-threads", "2", "-i", rpath, *largs, "-i", bn, "-filter_complex", f"[1:v]scale=1080:-1[bn];[0:v][bn]overlay={coords}:shortest=1[v]", "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "24", "-c:a", "copy", fpath]
                await asyncio.to_thread(subprocess.run, cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                h = CLIP_DURATION / 2
                p1, p2, md = f"temp/p1_{uid}_{mid_id}_{i}.mp4", f"temp/p2_{uid}_{mid_id}_{i}.mp4", f"temp/md_{uid}_{mid_id}_{i}.mp4"
                c1 = ["ffmpeg", "-y", "-threads", "2", "-i", rpath, "-t", str(h), "-c", "copy", p1]
                c2 = ["ffmpeg", "-y", "-threads", "2", "-ss", str(h), "-i", rpath, "-c", "copy", p2]
                c3 = ["ffmpeg", "-y", "-threads", "2", "-f", "lavfi", "-i", f"color=c=black:s=1080x1920:r=30:d={pause_sec}", "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={pause_sec}", *largs, "-i", bn, "-filter_complex", "[2:v]scale=1080:-1[bn];[0:v][bn]overlay=0:(H-h)/2:shortest=1[v]", "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "24", "-c:a", "aac", "-ar", "44100", "-ac", "2", "-t", str(pause_sec), md]
                c4 = ["ffmpeg", "-y", "-threads", "2", "-i", p1, "-i", md, "-i", p2, "-filter_complex", "[0:v][0:a][1:v][1:a][2:v][2:a]concat=n=3:v=1:a=1[v][a]", "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "24", "-c:a", "aac", fpath]
                for sc in (c1, c2, c3, c4):
                    await asyncio.to_thread(subprocess.run, sc, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                for tf in (p1, p2, md):
                    if os.path.exists(tf):
                        os.remove(tf)
            await msg.answer_video(FSInputFile(fpath))
            os.remove(rpath)
            os.remove(fpath)
            await asyncio.sleep(1.5)
        await msg.answer(f"Готово! Создано роликов: {len(clips)}")
    except Exception as e:
        await msg.edit_text(f"Ошибка: {e}")
    finally:
        if os.path.exists(inp):
            os.remove(inp)
        user_state.pop(uid, None)

async def main():
    print("Новый бот с кнопками успешно запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

