#!/usr/bin/env python3
"""
TikTok-эдит «ГИПЕРГАМИЯ» (1080x1920, 30 fps, ~24 с).

Всё генерируется кодом: картинка (PIL + numpy) и бит (синтез 808 + bass boost).
Песню «Worldstar Money» я не могу скачать/положить в видео (авторские права),
поэтому монтаж сделан в сетке 80 BPM, а свой mp3 можно подложить флагом --audio:

    python3 make_edit.py                                   # со встроенным битом
    python3 make_edit.py --audio song.mp3 --offset 12.5    # со своей песней (+ bass boost)
    python3 make_edit.py --bpm 84                          # подогнать сетку под трек
"""
import argparse
import math
import os
import subprocess
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS = 1080, 1920, 30
SR = 44100
FONT = "/usr/share/fonts/opentype/inter/Inter-Black.otf"
FONT_IT = "/usr/share/fonts/opentype/inter/Inter-BlackItalic.otf"
FONT_MED = "/usr/share/fonts/opentype/inter/Inter-Bold.otf"

ap = argparse.ArgumentParser()
ap.add_argument("--bpm", type=float, default=80.0)
ap.add_argument("--audio", help="свой аудиофайл вместо встроенного бита")
ap.add_argument("--offset", type=float, default=0.0, help="с какой секунды трека начинать")
ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "hypergamy_edit.mp4"))
args = ap.parse_args()

BEAT = 60.0 / args.bpm
TOTAL_BEATS = 32
DUR = TOTAL_BEATS * BEAT + 0.6
DROP = 8          # бит, на котором дроп
GAP = (19.5, 20)  # стоп перед «НО»

rng = np.random.default_rng(7)

# ----------------------------------------------------------------------------- паттерн
# Один источник правды для звука и картинки.
kicks, claps, hats, bass = [], [], [], []
ROOTS = [65.41, 51.91, 43.65, 49.00]  # C2, Ab1, F1, G1
for bar in range(TOTAL_BEATS // 4):
    b0 = bar * 4
    if b0 >= DROP:
        root = ROOTS[bar % 4]
        for off, mul in ((0, 1), (1.5, 1), (2.75, 1.5 if bar % 2 else 1)):
            kicks.append(b0 + off)
            bass.append((b0 + off, root * mul))
        claps += [b0 + 1, b0 + 3]
        for i in range(8):
            hats.append((b0 + i * 0.5, 1.0 if i % 2 == 0 else 0.6))
        if bar % 2 == 1:  # триольный ролл в конце такта
            hats += [(b0 + 3 + k / 6, 0.5 + k * 0.08) for k in range(6)]
    elif b0 >= 4:
        hats += [(b0 + i * 0.5, 0.35) for i in range(8)]


def in_gap(b):
    return GAP[0] <= b < GAP[1]


kicks = [b for b in kicks if not in_gap(b)] + [GAP[1]]
bass = [x for x in bass if not in_gap(x[0])] + [(GAP[1], 65.41)]
claps = [b for b in claps if not in_gap(b)]
hats = [h for h in hats if not in_gap(h[0])]

# ----------------------------------------------------------------------------- звук
def fft_filter(x, lo=None, hi=None):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    g = np.ones_like(f)
    if hi:
        g *= 1 / np.sqrt(1 + (f / hi) ** 4)
    if lo:
        g *= 1 / np.sqrt(1 + (lo / np.maximum(f, 1e-3)) ** 4)
    return np.fft.irfft(X * g, len(x))


def place(buf, start_s, sig):
    i = int(start_s * SR)
    if i >= len(buf):
        return
    n = min(len(sig), len(buf) - i)
    buf[i:i + n] += sig[:n]


def synth_808(freq, dur=1.1):
    t = np.arange(int(dur * SR)) / SR
    f = freq * (1 + 2.5 * np.exp(-t / 0.025))
    ph = 2 * np.pi * np.cumsum(f) / SR
    s = np.sin(ph) * np.exp(-t / 0.55)
    s = np.tanh(s * 3.2) / np.tanh(3.2)        # дисторшн = «bassboosted»
    return s * np.minimum(1, t / 0.002)


def synth_kick():
    t = np.arange(int(0.25 * SR)) / SR
    f = 55 * (1 + 4 * np.exp(-t / 0.012))
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.07)


def synth_clap():
    n = int(0.35 * SR)
    t = np.arange(n) / SR
    env = np.exp(-t / 0.09)
    for d in (0.0, 0.011, 0.022):
        env += 0.8 * np.exp(-np.maximum(t - d, 0) / 0.006) * (t >= d)
    return fft_filter(rng.standard_normal(n), lo=900, hi=6000) * env * 0.5


def synth_hat():
    n = int(0.06 * SR)
    t = np.arange(n) / SR
    return fft_filter(rng.standard_normal(n), lo=7000) * np.exp(-t / 0.015)


def build_audio():
    N = int(DUR * SR)
    low, mid = np.zeros(N), np.zeros(N)
    for b, fr in bass:
        place(low, b * BEAT, synth_808(fr) * (1.25 if b == GAP[1] else 1))
    k = synth_kick()
    for b in kicks:
        place(low, b * BEAT, k * 0.8)
    c = synth_clap()
    for b in claps:
        place(mid, b * BEAT, c)
    h = synth_hat()
    for b, v in hats:
        place(mid, b * BEAT, h * 0.25 * v)

    # пэд + колокольчик (тёмный до-минор)
    chords = [[60, 63, 67], [56, 60, 63], [53, 56, 60], [55, 59, 62]]
    arp = [0, 1, 2, 1, 2, 0, 1, 2]
    pad, bell = np.zeros(N), np.zeros(N)
    for bar in range(TOTAL_BEATS // 4):
        ch = chords[bar % 4]
        t = np.arange(int(4 * BEAT * SR)) / SR
        for m in ch:
            fr = 440 * 2 ** ((m - 12 - 69) / 12)
            for det in (-0.12, 0.12):
                ph = (t * fr * (1 + det / 100)) % 1
                place(pad, bar * 4 * BEAT, (2 * ph - 1) * 0.05)
        for i, idx in enumerate(arp):
            fr = 440 * 2 ** ((ch[idx] + 12 - 69) / 12)
            tt = np.arange(int(1.2 * SR)) / SR
            s = (np.sin(2 * np.pi * fr * tt) + 0.3 * np.sin(2 * np.pi * fr * 2.01 * tt)) * np.exp(-tt / 0.35)
            place(bell, (bar * 4 + i * 0.5) * BEAT, s * 0.12)
    pad = fft_filter(pad, hi=1400)
    music = pad + bell

    tt = np.arange(N) / SR
    drop_s = DROP * BEAT
    intro = tt < drop_s
    music = np.where(intro, fft_filter(music, hi=700) * 1.4, music)  # «из-под воды» до дропа
    riser = fft_filter(rng.standard_normal(N), lo=2500) * np.clip((tt - 6 * BEAT) / (2 * BEAT), 0, 1) ** 2 * intro * 0.35
    g0, g1 = GAP[0] * BEAT, GAP[1] * BEAT
    music *= ~((tt >= g0) & (tt < g1))

    # сайдчейн от бочки
    duck = np.ones(N)
    for b in kicks:
        i = int(b * BEAT * SR)
        n = min(int(0.3 * SR), N - i)
        if n > 0:
            duck[i:i + n] = np.minimum(duck[i:i + n], 1 - 0.7 * np.exp(-np.arange(n) / SR / 0.09))

    low = np.tanh(fft_filter(low, hi=180) * 2.2 + low * 0.3)  # bass boost
    mix = low * 0.95 + mid * 0.6 + music * duck + riser
    mix = np.tanh(mix * 1.3)
    mix *= np.minimum(1, (N - np.arange(N)) / (0.5 * SR))
    mix /= np.abs(mix).max() / 0.95
    return mix


# ----------------------------------------------------------------------------- графика
def font(size, path=FONT):
    return ImageFont.truetype(path, size)


_cache = {}


def text_sprite(text, size, fill=(255, 255, 255), glow=(255, 30, 60), path=FONT, maxw=860):
    key = (text, size, fill, glow, path)
    if key in _cache:
        return _cache[key]
    while True:
        f = font(size, path)
        x0, y0, x1, y1 = f.getbbox(text, stroke_width=6)
        if x1 - x0 <= maxw or size < 30:
            break
        size = int(size * 0.92)
    pad = size // 2
    w, h = x1 - x0 + 2 * pad, y1 - y0 + 2 * pad
    glow_l = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(glow_l).text((pad - x0, pad - y0), text, font=f, fill=glow + (255,), stroke_width=10, stroke_fill=glow + (255,))
    glow_l = glow_l.filter(ImageFilter.GaussianBlur(size / 7))
    top = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(top).text((pad - x0, pad - y0), text, font=f, fill=fill + (255,), stroke_width=6, stroke_fill=(0, 0, 0, 255))
    out = Image.alpha_composite(glow_l, top)
    _cache[key] = out
    return out


def paste_center(img, spr, cx, cy, scale=1.0, alpha=1.0, rot=0.0):
    if scale != 1.0:
        spr = spr.resize((max(1, int(spr.width * scale)), max(1, int(spr.height * scale))), Image.BILINEAR)
    if rot:
        spr = spr.rotate(rot, resample=Image.BILINEAR, expand=True)
    if alpha < 1:
        a = spr.getchannel("A").point(lambda v: int(v * alpha))
        spr = spr.copy()
        spr.putalpha(a)
    img.alpha_composite(spr, (int(cx - spr.width / 2), int(cy - spr.height / 2)))


def pop(dt, k=0.35, tau=0.09):
    """масштаб «влёта» текста по биту"""
    return 1 + k * math.exp(-max(dt, 0) / tau)


# фон и маски (считаем один раз)
yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
rad = np.sqrt(((xx - W / 2) / W) ** 2 + ((yy - H * 0.45) / H) ** 2)
vignette = np.clip(1.25 - rad * 1.6, 0.15, 1)[..., None]
scan = (1 - 0.10 * (np.arange(H) % 4 < 2)).astype(np.float32)[:, None, None]
grain = [rng.normal(0, 5, (H // 2, W // 2, 1)).astype(np.float32).repeat(2, 0).repeat(2, 1) for _ in range(6)]
glow_bg = np.exp(-rad * 3.2)[..., None]

PALETTE = {
    "intro": ((10, 4, 18), (90, 10, 70)),
    "drop": ((12, 0, 6), (170, 10, 40)),
    "money": ((2, 10, 4), (20, 140, 60)),
    "science": ((2, 6, 20), (20, 70, 180)),
    "no": ((0, 0, 0), (200, 0, 0)),
    "outro": ((14, 8, 0), (200, 140, 10)),
}

# долларовый дождь
dollar = text_sprite("$", 90, fill=(120, 255, 140), glow=(0, 200, 80))
coins = [(rng.uniform(0, W), rng.uniform(0, 1), rng.uniform(0.6, 1.4), rng.uniform(-40, 40), rng.uniform(0.4, 1.2)) for _ in range(28)]
dollar_rot = {}


def money_rain(img, t, strength):
    for x, ph, sp, rot, sc in coins:
        y = ((ph + t * 0.35 * sp) % 1.25 - 0.15) * H
        r = int(rot + t * 60 * sp) % 360 // 15 * 15
        key = (r, round(sc, 1))
        if key not in dollar_rot:
            s = dollar.resize((int(dollar.width * sc), int(dollar.height * sc)), Image.BILINEAR)
            dollar_rot[key] = s.rotate(r, resample=Image.BILINEAR, expand=True)
        s = dollar_rot[key]
        if strength < 1:
            s = s.copy()
            s.putalpha(s.getchannel("A").point(lambda v: int(v * strength)))
        img.alpha_composite(s, (int(x - s.width / 2), int(y)))


def up_arrow(img, cx, cy, size, progress, color=(255, 210, 60)):
    d = ImageDraw.Draw(img)
    h = max(size * progress, size * 0.36)
    w = size * 0.28
    d.rectangle([cx - w / 2, cy - h + size * 0.35, cx + w / 2, cy], fill=color + (255,))
    d.polygon([(cx - size * 0.42, cy - h + size * 0.4), (cx + size * 0.42, cy - h + size * 0.4), (cx, cy - h - size * 0.1)], fill=color + (255,))


def bars_chart(img, n_on, t_in, y_base=1500):
    d = ImageDraw.Draw(img)
    heights = [260, 380, 500, 640]
    for i in range(4):
        x = 170 + i * 250
        if i < n_on:
            grow = min(1, (t_in[i]) / 0.18)
            hh = heights[i] * (1 - (1 - grow) ** 3)
            col = (255, 210, 60) if i == n_on - 1 else (120, 255, 140)
            d.rectangle([x - 80, y_base - hh, x + 80, y_base], fill=col + (255,))
        d.rectangle([x - 80, y_base - 4, x + 80, y_base + 4], fill=(255, 255, 255, 160))


def caption(img, text, y, size=44, alpha=1.0):
    spr = text_sprite(text, size, fill=(235, 235, 235), glow=(0, 0, 0), path=FONT_MED)
    paste_center(img, spr, W / 2, y, alpha=alpha)


# ----------------------------------------------------------------------------- сцены
def scene(b):
    """возвращает (палитра, список элементов) для бита b"""
    if b < 4:
        return "intro"
    if b < DROP:
        return "intro"
    if b < 12:
        return "drop"
    if b < 16:
        return "money"
    if b < GAP[0]:
        return "science"
    if b < GAP[1]:
        return "gap"
    if b < 21:
        return "no"
    if b < 24:
        return "science"
    if b < 28:
        return "drop"
    return "outro"


def draw_scene(img, b, t):
    lb = lambda start: (b - start) * BEAT  # секунд с начала элемента
    cy = H * 0.45
    if b < 4:
        word = "ГИПЕРГАМИЯ"
        n = min(len(word), int(b / 0.35) + 1)
        flick = 1.0 if rng.random() > 0.08 else 0.3
        spr = text_sprite(word[:n], 150)
        paste_center(img, spr, W / 2, cy, alpha=flick)
        caption(img, "социология за 24 секунды", cy + 170, alpha=min(1, b / 2))
    elif b < 6:
        paste_center(img, text_sprite("ЧТО ЭТО", 190), W / 2, cy, pop(lb(4)))
    elif b < DROP:
        jitter = (b - 6) / 2
        paste_center(img, text_sprite("ТАКОЕ?", 210), W / 2 + rng.normal(0, 14 * jitter), cy + rng.normal(0, 14 * jitter), pop(lb(6)) + 0.15 * jitter)
    elif b < 10:
        paste_center(img, text_sprite("ВЫБОР", 220), W / 2, cy - 120, pop(lb(8), 0.6))
        paste_center(img, text_sprite("ПАРТНЁРА", 180), W / 2, cy + 110, pop(lb(9), 0.6) if b >= 9 else 0.0001)
    elif b < 12:
        up_arrow(img, W / 2, cy + 520, 300, min(1, lb(10) / 0.35))
        paste_center(img, text_sprite("ВЫШЕ", 230, fill=(255, 220, 80)), W / 2, cy - 160, pop(lb(10), 0.5))
        paste_center(img, text_sprite("ПО СТАТУСУ", 150), W / 2, cy + 60, pop(lb(11), 0.5) if b >= 11 else 0.0001)
    elif b < 16:
        words = ["ДЕНЬГИ", "СТАТУС", "ВЛАСТЬ", "ОБРАЗОВАНИЕ"]
        i = int(b - 12)
        bars_chart(img, i + 1, [lb(12 + k) for k in range(4)])
        paste_center(img, text_sprite(words[i], 190, fill=(255, 220, 80), glow=(0, 160, 60)), W / 2, cy - 280, pop(lb(12 + i), 0.5), rot=rng.normal(0, 1.5))
    elif b < 18:
        paste_center(img, text_sprite("ТЕРМИН ИЗ", 150), W / 2, cy - 100, pop(lb(16)))
        paste_center(img, text_sprite("СОЦИОЛОГИИ", 150, fill=(140, 200, 255), glow=(30, 90, 255)), W / 2, cy + 80, pop(lb(17)) if b >= 17 else 0.0001)
    elif b < GAP[0]:
        paste_center(img, text_sprite("«БРАК ВВЕРХ»", 160, glow=(30, 90, 255)), W / 2, cy, pop(lb(18)))
        caption(img, "hyper (выше) + gamos (брак)", cy + 160)
    elif b < GAP[1]:
        pass
    elif b < 21:
        paste_center(img, text_sprite("НО", 520, fill=(255, 40, 40), glow=(255, 0, 0)), W / 2, cy, pop(lb(20), 0.9, 0.12))
    elif b < 24:
        lines = ["СЕГОДНЯ ПАРЫ", "ВСЁ ЧАЩЕ", "РАВНЫ"]
        for i, line in enumerate(lines):
            if b >= 21 + i:
                fill = (140, 255, 170) if i == 2 else (255, 255, 255)
                paste_center(img, text_sprite(line, 230 if i == 2 else 130, fill=fill, glow=(30, 90, 255)), W / 2, cy - 230 + i * 210, pop(lb(21 + i)))
        if b >= 23:
            caption(img, "по образованию и доходу", cy + 420)
    elif b < 26:
        paste_center(img, text_sprite("ВЫВОД:", 200), W / 2, cy, pop(lb(24 + int(b - 24)), 0.3))
    elif b < 28:
        paste_center(img, text_sprite("НЕ ИЩИ", 200), W / 2, cy - 110, pop(lb(26)))
        if b >= 27:
            paste_center(img, text_sprite("ВИНОВАТЫХ", 160), W / 2, cy + 90, pop(lb(27)))
    else:
        if b < 29:
            paste_center(img, text_sprite("КАЧАЙ", 260, fill=(255, 220, 80), glow=(255, 120, 0)), W / 2, cy, pop(lb(28), 0.6))
        elif b < 30:
            paste_center(img, text_sprite("СЕБЯ", 300, fill=(255, 220, 80), glow=(255, 120, 0)), W / 2, cy, pop(lb(29), 0.6))
        else:
            paste_center(img, text_sprite("КАЧАЙ", 230, fill=(255, 220, 80), glow=(255, 120, 0), path=FONT_IT), W / 2, cy - 120, pop(lb(30), 0.4))
            paste_center(img, text_sprite("СЕБЯ", 230, fill=(255, 255, 255), glow=(255, 120, 0), path=FONT_IT), W / 2, cy + 90, pop(lb(31), 0.4) if b >= 31 else 0.0001)
            caption(img, "#гипергамия #эдит #саморазвитие", cy + 330)


# ----------------------------------------------------------------------------- рендер
def last_hit(b, hits):
    past = [h for h in hits if h <= b]
    return (b - max(past)) * BEAT if past else 99


def render(audio_path):
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-"]
    if args.audio:
        cmd += ["-ss", str(args.offset), "-i", args.audio,
                "-af", "bass=g=14:f=90,alimiter=limit=0.9,afade=t=out:st=%.2f:d=0.5" % (DUR - 0.5)]
    else:
        cmd += ["-i", audio_path]
    cmd += ["-map", "0:v", "-map", "1:a", "-shortest",
            "-c:v", "libx264", "-preset", "slow", "-crf", "25", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", args.out]
    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    nframes = int(DUR * FPS)
    for fi in range(nframes):
        t = fi / FPS
        b = t / BEAT
        sc = scene(b)
        dk = last_hit(b, kicks)
        dc = last_hit(b, claps)
        kick_e = math.exp(-dk / 0.12) if b >= DROP else 0
        clap_e = math.exp(-dc / 0.08) if b >= DROP else 0

        if sc == "gap":
            frame = np.zeros((H, W, 3), np.float32)
        else:
            c0, c1 = (np.array(c, np.float32) for c in PALETTE[sc])
            pulse = 0.55 + 0.45 * kick_e + 0.1 * math.sin(t * 2)
            frame = c0 + (c1 - c0) * glow_bg * pulse
            img = Image.fromarray(np.clip(frame, 0, 255).astype(np.uint8)).convert("RGBA")
            if sc in ("drop", "money", "outro"):
                money_rain(img, t, 0.35 if sc == "drop" else 0.8)
            draw_scene(img, b, t)
            frame = np.asarray(img.convert("RGB"), np.float32)

        # zoom punch
        z = 1 + 0.08 * kick_e + (0.12 if 20 <= b < 20.3 else 0) * math.exp(-(b - 20) * BEAT / 0.1)
        if z > 1.002:
            cw, ch = int(W / z), int(H / z)
            x0, y0 = (W - cw) // 2, (H - ch) // 2
            frame = np.asarray(Image.fromarray(frame[y0:y0 + ch, x0:x0 + cw].astype(np.uint8)).resize((W, H), Image.BILINEAR), np.float32)
        # тряска
        sh = int(26 * kick_e + 10 * clap_e + (8 if 6 <= b < DROP else 0))
        if sh:
            frame = np.roll(frame, (int(rng.integers(-sh, sh + 1)), int(rng.integers(-sh, sh + 1))), (0, 1))
        # RGB-сдвиг
        ca = int(4 + 22 * kick_e + 14 * clap_e)
        frame[..., 0] = np.roll(frame[..., 0], ca, 1)
        frame[..., 2] = np.roll(frame[..., 2], -ca, 1)
        # вспышки на дропе / «НО» / финале
        for fb, k in ((DROP, 1.0), (20, 0.9), (28, 0.8)):
            if 0 <= b - fb < 0.5:
                frame += (255 - frame) * k * math.exp(-(b - fb) * BEAT / 0.07)
        if 6 <= b < DROP and int(b * 8) % 2:  # стробы перед дропом
            frame *= 0.55
        frame = frame * vignette * scan + grain[fi % len(grain)]
        # фейд в начале
        if t < 0.25:
            frame *= t / 0.25
        ff.stdin.write(np.clip(frame, 0, 255).astype(np.uint8).tobytes())
        if fi % 60 == 0:
            print(f"кадр {fi}/{nframes}", flush=True)
    ff.stdin.close()
    ff.wait()


if __name__ == "__main__":
    tmp_wav = os.path.splitext(args.out)[0] + "_beat.wav"
    if not args.audio:
        mix = build_audio()
        with wave.open(tmp_wav, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SR)
            wf.writeframes((mix * 32767).astype(np.int16).tobytes())
    render(tmp_wav)
    print("готово:", args.out)
