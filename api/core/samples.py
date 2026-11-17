"""Sample files for demo and test data: photos and documents that look like the real thing.

Every file is clearly marked SAMPLE. Organisations, people and figures are fictional; amounts printed on a
sample are whatever the seed passes in (working assumptions, never verified data).

Output is deterministic: the same arguments always give the same bytes (seeded randomness, fixed PDF dates),
so seeds stay idempotent and hashes stay stable. Photos are small JPEGs (under 150 KB); documents are PDFs made
with fpdf2's built-in fonts.

    from core import samples
    data = samples.photo("foundation", "bld-A-foundation-1", caption="Foundation trench, Kasoa")
    data = samples.pdf("receipt", "receipt-KATH-0120", issuer="Riverside Teaching Hospital", amount="450.00")
    data, content_type, name = samples.file_for("site-plan-east-legon.pdf")

Use only in seeds and tests. Real files come from people and from Tenmina Field.
"""
import hashlib
import io
import math
import random
import re
from datetime import date, datetime, timezone as dt_tz
from functools import lru_cache

W, H = 720, 540
BANNER = 46
FIXED_DATE = datetime(2026, 10, 1, 9, 0, tzinfo=dt_tz.utc)

LIME = (200, 241, 53)
INK = (17, 17, 17)
PAPER = (247, 246, 242)
RED = (214, 40, 40)

# Fictional organisations, one list per kind. "(sample)" is printed after each on the document.
SCHOOLS = ["Akwaaba Hills School", "Riverside Academy", "Golden Palm Basic School", "Harmattan Senior High"]
HOSPITALS = ["Riverside Teaching Hospital", "Coastline Community Clinic", "Hillcrest Medical Centre"]
AGENCIES = ["Lands Records Office (sample)", "Births and Records Office (sample)", "Civic Services Office"]
BANKS = ["Partner Bank (sample)", "Coastal Trust Bank (sample)"]
SUPPLIERS = ["Kobby Building Supplies", "RoofWorks Ltd", "Mama Esi Catering", "Bright Gates and Welding",
             "Sunrise Electrical Services"]
LAW = ["Mensah and Partners, Solicitors (sample)", "Owusu Survey Consultants (sample)"]
INSURERS = ["Harbour Life Assurance (sample)"]


# --------------------------------------------------------------------------- helpers

def _rng(*parts) -> random.Random:
    return random.Random(hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest())


@lru_cache(maxsize=16)
def _font(size: int):
    from PIL import ImageFont

    return ImageFont.load_default(size=size)


def _latin(text) -> str:
    repl = {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "…": "...", "•": "-",
            "₵": "GHS ", " ": " "}
    s = str(text if text is not None else "")
    for k, v in repl.items():
        s = s.replace(k, v)
    return s.encode("latin-1", "replace").decode("latin-1")


def _mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _jitter(c, rng, n=12):
    return tuple(max(0, min(255, v + rng.randint(-n, n))) for v in c)


def _money(amount, currency="GHS") -> str:
    try:
        return f"{currency} {float(amount):,.2f}"
    except (TypeError, ValueError):
        return f"{currency} {amount}"


def _ref(seed: str, prefix="SMP") -> str:
    return f"{prefix}-{hashlib.sha256(seed.encode()).hexdigest()[:8].upper()}"


# --------------------------------------------------------------------------- photo scenes

def _sky(d, rng, horizon):
    top = _jitter((96, 150, 214), rng, 18)
    low = _jitter((214, 228, 240), rng, 10)
    for y in range(horizon):
        d.line([(0, y), (W, y)], fill=_mix(top, low, y / max(horizon, 1)))
    for _ in range(rng.randint(1, 4)):  # clouds
        cx, cy, r = rng.randint(0, W), rng.randint(10, max(12, horizon - 40)), rng.randint(18, 40)
        for k in range(4):
            d.ellipse([cx + k * r * 0.7 - r, cy - r * 0.6, cx + k * r * 0.7 + r, cy + r * 0.6], fill=(250, 250, 252))


def _ground(d, rng, horizon, base=(176, 96, 58)):
    far, near = _jitter(_mix(base, (200, 170, 130), 0.35), rng, 8), _jitter(base, rng, 10)
    for y in range(horizon, H):
        d.line([(0, y), (W, y)], fill=_mix(far, near, (y - horizon) / max(H - horizon, 1)))
    for _ in range(70):  # mottled earth
        x, y = rng.randint(0, W), rng.randint(horizon, H)
        r = rng.randint(2, 9) * (1 + (y - horizon) / (H - horizon))
        d.ellipse([x - r * 2, y - r * 0.5, x + r * 2, y + r * 0.5], fill=_jitter(near, rng, 22))


def _shrub(d, rng, x, y, s):
    for _ in range(6):
        dx, dy, r = rng.randint(-s, s), rng.randint(-s // 2, 0), rng.randint(s // 2, s)
        d.ellipse([x + dx - r, y + dy - r, x + dx + r, y + dy + r // 2], fill=_jitter((60, 120, 52), rng, 22))


def _palm(d, rng, x, base, h):
    top = base - h
    d.line([(x, base), (x + rng.randint(-14, 14), top)], fill=(110, 84, 52), width=max(4, h // 28))
    for k in range(7):
        a = math.pi * (0.1 + 0.8 * k / 6)
        ex, ey = x + math.cos(a) * h * 0.42 * (1 if k % 2 else -1), top + math.sin(a) * h * 0.18
        d.line([(x, top), (ex, ey)], fill=(52, 118, 46), width=max(3, h // 34))


def _pillar(d, x, y, s):
    """A survey beacon: a concrete post with a red top."""
    d.rectangle([x - s, y - 4 * s, x + s, y], fill=(222, 220, 212), outline=(120, 120, 116))
    d.rectangle([x - s, y - 4 * s, x + s, y - 3 * s], fill=(200, 40, 40))


def _blocks(d, rng, x0, y0, x1, y1, bh=18, color=(170, 170, 164)):
    y, row = y1, 0
    while y > y0:
        top = max(y0, y - bh)
        off = (row % 2) * bh
        x = x0 - off
        while x < x1:
            d.rectangle([max(x0, x), top, min(x1, x + bh * 2), y], fill=_jitter(color, rng, 8),
                        outline=(120, 118, 112))
            x += bh * 2
        y, row = top, row + 1


def _house(d, rng, x, base, w, h, stage):
    """A one-storey house at a construction stage: foundation, blockwork, roofing, finishing or complete."""
    if stage == "foundation":
        d.polygon([(x, base), (x + w, base), (x + w - 30, base - 40), (x + 30, base - 40)], fill=(120, 72, 44))
        d.rectangle([x + 30, base - 46, x + w - 30, base - 38], fill=(160, 160, 156))
        for k in range(9):  # rebar
            xx = x + 40 + k * (w - 80) / 8
            d.line([(xx, base - 40), (xx, base - 110)], fill=(90, 60, 40), width=3)
        d.line([(x + 40, base - 90), (x + w - 40, base - 90)], fill=(90, 60, 40), width=2)
        for k in range(4):  # block stack
            _blocks(d, rng, x + w + 10, base - 20 - k * 4, x + w + 80, base - k * 4, bh=10)
        return
    wall_h = h if stage != "blockwork" else int(h * rng.uniform(0.45, 0.7))
    if stage in ("blockwork", "roofing"):
        _blocks(d, rng, x, base - wall_h, x + w, base)
    else:
        paint = _jitter(rng.choice([(236, 226, 196), (230, 214, 180), (222, 232, 226), (244, 240, 232)]), rng, 6)
        d.rectangle([x, base - wall_h, x + w, base], fill=paint, outline=(140, 130, 118))
        d.rectangle([x, base - 14, x + w, base], fill=(150, 140, 128))
    if stage == "blockwork":
        d.line([(x + w * 0.3, base - wall_h - 70), (x + w * 0.3, base)], fill=(150, 120, 80), width=4)
        d.line([(x + w * 0.7, base - wall_h - 70), (x + w * 0.7, base)], fill=(150, 120, 80), width=4)
        return
    roof = [(x - 20, base - wall_h), (x + w + 20, base - wall_h), (x + w * 0.5, base - wall_h - h * 0.55)]
    if stage == "roofing":
        for k in range(8):  # trusses
            xx = x + k * w / 7
            peak_y = base - wall_h - h * 0.55 * (1 - abs(xx - (x + w / 2)) / (w / 2 + 20))
            d.line([(xx, base - wall_h), (xx, peak_y)], fill=(140, 100, 60), width=3)
        d.line(roof + [roof[0]], fill=(140, 100, 60), width=5)
        half = [roof[0], (x + w * 0.5, base - wall_h - h * 0.55), (x + w * 0.5, base - wall_h)]
        d.polygon(half, fill=(170, 176, 182), outline=(110, 116, 122))
    else:
        d.polygon(roof, fill=rng.choice([(150, 60, 48), (60, 80, 110), (110, 116, 122)]), outline=(70, 50, 40))
    for k in range(3 if w > 240 else 2):  # windows
        wx = x + 30 + k * (w - 60) / (3 if w > 240 else 2)
        d.rectangle([wx, base - wall_h * 0.7, wx + 46, base - wall_h * 0.35],
                    fill=(70, 100, 130) if stage != "roofing" else (40, 40, 40), outline=(230, 230, 230))
    dx = x + w - 70
    d.rectangle([dx, base - wall_h * 0.75, dx + 40, base - 14], fill=(110, 70, 40) if stage != "roofing" else (40, 40, 40))
    if stage == "finishing":  # scaffold and paint buckets
        for k in range(3):
            xx = x - 10 + k * 26
            d.line([(xx, base), (xx, base - wall_h - 10)], fill=(90, 90, 90), width=3)
        for k in range(4):
            d.line([(x - 12, base - k * wall_h / 3), (x + 50, base - k * wall_h / 3)], fill=(90, 90, 90), width=2)
        d.rectangle([x + w + 10, base - 26, x + w + 34, base], fill=(230, 230, 230), outline=(120, 120, 120))


def _fence(d, rng, horizon_y, base):
    d.rectangle([0, base - 60, W, base], fill=_jitter((206, 200, 188), rng, 6), outline=(150, 145, 136))
    for k in range(0, W, 60):
        d.rectangle([k, base - 66, k + 14, base], fill=(190, 184, 172))


def _interior(d, rng, room):
    wall = _jitter(rng.choice([(236, 228, 210), (220, 230, 226), (240, 236, 226)]), rng, 6)
    floor_y = int(H * rng.uniform(0.6, 0.7))
    d.rectangle([0, 0, W, floor_y], fill=wall)
    floor = _jitter((150, 110, 80) if room != "kitchen" else (190, 190, 186), rng, 8)
    d.rectangle([0, floor_y, W, H], fill=floor)
    for k in range(0, W, 48):
        d.line([(k, floor_y), (k - 120, H)], fill=_mix(floor, (0, 0, 0), 0.15))
    wx = rng.randint(40, W - 240)
    d.rectangle([wx, 70, wx + 180, 230], fill=(170, 206, 232), outline=(250, 250, 250), width=8)
    d.line([(wx + 90, 70), (wx + 90, 230)], fill=(250, 250, 250), width=5)
    if room == "living":
        sx = rng.randint(30, W - 330)
        d.rounded_rectangle([sx, floor_y - 110, sx + 300, floor_y + 20], 16, fill=_jitter((90, 110, 140), rng, 20))
        d.rounded_rectangle([sx + 14, floor_y - 70, sx + 286, floor_y - 10], 10, fill=_jitter((110, 130, 160), rng, 20))
        d.rectangle([sx + 320, floor_y - 40, sx + 400, floor_y + 30], fill=(120, 84, 52))
    elif room == "kitchen":
        d.rectangle([0, floor_y - 120, W, floor_y], fill=(200, 196, 188), outline=(140, 136, 128))
        d.rectangle([0, floor_y - 130, W, floor_y - 118], fill=(90, 90, 92))
        for k in range(0, W, 120):
            d.rectangle([k + 8, floor_y - 108, k + 112, floor_y - 8], outline=(150, 146, 138), width=2)
        d.rectangle([W - 200, floor_y - 170, W - 120, floor_y - 130], fill=(60, 60, 64))
    elif room == "front":
        d.rectangle([W // 2 - 60, floor_y - 260, W // 2 + 60, floor_y], fill=(110, 72, 44), outline=(70, 46, 30))
        d.ellipse([W // 2 + 36, floor_y - 140, W // 2 + 48, floor_y - 128], fill=(220, 190, 80))
    else:  # bedroom or care visit room
        d.rectangle([60, floor_y - 70, 360, floor_y + 30], fill=(240, 240, 236), outline=(160, 160, 156))
        d.rectangle([60, floor_y - 120, 90, floor_y + 30], fill=(120, 84, 52))
    return floor_y


def _groceries(d, rng, floor_y):
    tx = rng.randint(200, 360)
    d.rectangle([tx, floor_y - 40, tx + 320, floor_y - 26], fill=(130, 90, 56))
    d.line([(tx + 20, floor_y - 26), (tx + 20, floor_y + 60)], fill=(110, 76, 46), width=8)
    d.line([(tx + 300, floor_y - 26), (tx + 300, floor_y + 60)], fill=(110, 76, 46), width=8)
    x = tx + 16
    for _ in range(rng.randint(5, 7)):
        kind, c = rng.choice(["bag", "bottle", "box", "fruit"]), _jitter(rng.choice(
            [(220, 60, 40), (240, 180, 40), (60, 140, 70), (230, 230, 230), (90, 120, 200)]), rng, 20)
        if kind == "bag":
            d.rectangle([x, floor_y - 110, x + 50, floor_y - 40], fill=c)
            x += 56
        elif kind == "bottle":
            d.rectangle([x, floor_y - 100, x + 22, floor_y - 40], fill=c)
            d.rectangle([x + 6, floor_y - 116, x + 16, floor_y - 100], fill=c)
            x += 30
        elif kind == "box":
            d.rectangle([x, floor_y - 84, x + 44, floor_y - 40], fill=c, outline=(80, 80, 80))
            x += 50
        else:
            for k in range(3):
                d.ellipse([x + k * 14, floor_y - 62, x + k * 14 + 22, floor_y - 40], fill=c)
            x += 50
        if x > tx + 290:
            break


def _paper(rng, w, h, title, lines, stamp=None, issuer=""):
    """A sheet of paper with text, for receipt photos and scanned pages."""
    from PIL import Image, ImageDraw

    p = Image.new("RGB", (w, h), _jitter((250, 248, 240), rng, 4))
    d = ImageDraw.Draw(p)
    y = 18
    if issuer:
        d.text((18, y), _latin(issuer).upper(), fill=(40, 40, 60), font=_font(17))
        y += 26
    d.text((18, y), title, fill=INK, font=_font(24))
    y += 38
    for ln in lines:
        d.text((18, y), ln, fill=(50, 50, 56), font=_font(15))
        y += 23
        if y > h - 30:
            break
    if stamp:
        cx, cy, r = w - 90, h - 90, 62
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(40, 70, 170), width=5)
        d.ellipse([cx - r + 10, cy - r + 10, cx + r - 10, cy + r - 10], outline=(40, 70, 170), width=2)
        tw = d.textlength(stamp, font=_font(15))
        d.text((cx - tw / 2, cy - 9), stamp, fill=(40, 70, 170), font=_font(15))
    return p


def _desk(d, rng):
    base = _jitter((150, 104, 66), rng, 14)
    for y in range(0, H):
        d.line([(0, y), (W, y)], fill=_mix(base, (0, 0, 0), 0.06 * math.sin(y / 9 + rng.random()) + 0.06))


def _crack(d, rng, x, y, length):
    pts, cx, cy = [], x, y
    for _ in range(14):
        pts.append((cx, cy))
        cx += rng.randint(-14, 14)
        cy += length / 14
    d.line(pts, fill=(40, 34, 30), width=4)
    for k in range(2, 12, 4):
        bx, by = pts[k]
        d.line([(bx, by), (bx + rng.randint(-40, 40), by + rng.randint(10, 30))], fill=(50, 44, 40), width=2)
    return pts


PHOTO_KINDS = ("land", "house", "foundation", "blockwork", "roofing", "finishing", "defect", "listing",
               "listing_land", "care", "groceries", "receipt", "room_front", "room_living", "room_kitchen",
               "gate", "pillar", "document", "work", "id", "register", "delivery")

DEFAULT_CAPTIONS = {
    "land": "Plot of land with corner pillars", "house": "House, front view", "foundation": "Foundation stage",
    "blockwork": "Blockwork stage", "roofing": "Roofing stage", "finishing": "Finishing stage",
    "defect": "Inspection: defect found", "listing": "Listing photo", "listing_land": "Listing photo: plot",
    "care": "Care visit", "groceries": "Care visit: groceries delivered", "receipt": "Receipt",
    "room_front": "Inspection: front door", "room_living": "Inspection: living room",
    "room_kitchen": "Inspection: kitchen", "gate": "Gate and boundary pillar", "pillar": "Boundary pillar",
    "document": "Stamped acknowledgement", "work": "Repair work done", "id": "ID document",
    "register": "Register page", "delivery": "Delivery on the day",
}


def _scene(kind, rng, img, d, caption, seed):
    from PIL import Image, ImageDraw

    horizon = int(H * rng.uniform(0.36, 0.5))
    if kind in ("land", "listing_land", "pillar"):
        _sky(d, rng, horizon)
        _ground(d, rng, horizon)
        for _ in range(rng.randint(3, 8)):
            _shrub(d, rng, rng.randint(0, W), horizon + rng.randint(0, 40), rng.randint(12, 30))
        for _ in range(rng.randint(1, 3)):
            _palm(d, rng, rng.randint(20, W - 20), horizon + rng.randint(5, 30), rng.randint(110, 190))
        corners = [(rng.randint(60, 200), H - rng.randint(70, 120)), (rng.randint(500, 660), H - rng.randint(60, 110)),
                   (rng.randint(420, 560), horizon + rng.randint(30, 60)),
                   (rng.randint(150, 300), horizon + rng.randint(30, 60))]
        if kind == "pillar":
            _pillar(d, W // 2 + rng.randint(-120, 120), H - 90, 22)
        else:
            d.line(corners + [corners[0]], fill=(240, 236, 220), width=2)
            for i, (cx, cy) in enumerate(corners):
                _pillar(d, cx, cy, 9 if i < 2 else 5)
    elif kind in ("house", "listing", "foundation", "blockwork", "roofing", "finishing", "gate", "work"):
        _sky(d, rng, horizon)
        _ground(d, rng, horizon, base=(170, 100, 64) if kind != "listing" else (120, 150, 80))
        for _ in range(rng.randint(1, 3)):
            _palm(d, rng, rng.choice([rng.randint(10, 120), rng.randint(600, 710)]), horizon + 20, rng.randint(140, 220))
        w = rng.randint(300, 440)
        x = rng.randint(30, W - w - 60)
        base = horizon + rng.randint(150, 200)
        stage = {"house": "complete", "listing": "complete", "gate": "complete", "work": "complete"}.get(kind, kind)
        _house(d, rng, x, base, w, rng.randint(150, 190), stage)
        if kind == "gate":
            _fence(d, rng, horizon, H - 40)
            gx = rng.randint(200, 440)
            d.rectangle([gx, H - 150, gx + 200, H - 40], fill=(40, 60, 50), outline=(20, 20, 20), width=3)
            for k in range(1, 8):
                d.line([(gx + k * 25, H - 150), (gx + k * 25, H - 40)], fill=(20, 30, 26), width=2)
            _pillar(d, gx - 40, H - 40, 12)
        for _ in range(rng.randint(2, 5)):
            _shrub(d, rng, rng.randint(0, W), base + rng.randint(5, 50), rng.randint(14, 26))
        if kind == "work":
            d.rectangle([x + 20, base - 30, x + 120, base - 10], fill=(240, 200, 60), outline=INK)
    elif kind == "defect":
        d.rectangle([0, 0, W, H], fill=(190, 188, 182))
        _blocks(d, rng, 0, 0, W, H, bh=44, color=(186, 184, 178))
        x = rng.randint(220, 480)
        pts = _crack(d, rng, x, rng.randint(40, 120), rng.randint(260, 360))
        cx, cy = pts[len(pts) // 2]
        d.ellipse([cx - 110, cy - 150, cx + 110, cy + 150], outline=RED, width=6)
        tx = rng.randint(30, 120)  # measuring tape
        d.rectangle([tx, 60, tx + 34, 440], fill=(244, 206, 40), outline=INK)
        for k in range(60, 440, 19):
            d.line([(tx, k), (tx + (16 if (k // 19) % 5 else 28), k)], fill=INK, width=2)
        d.rectangle([cx + 80, cy - 180, cx + 230, cy - 146], fill=RED)
        d.text((cx + 90, cy - 176), "DEFECT", fill=(255, 255, 255), font=_font(24))
    elif kind in ("care", "groceries", "room_front", "room_living", "room_kitchen"):
        room = {"room_front": "front", "room_living": "living", "room_kitchen": "kitchen"}.get(kind, "bedroom")
        floor_y = _interior(d, rng, room)
        if kind in ("care", "groceries"):
            _groceries(d, rng, floor_y)
    elif kind == "delivery":
        _sky(d, rng, horizon)
        _ground(d, rng, horizon, base=(120, 150, 80))
        for k in range(rng.randint(2, 4)):  # tents
            tx = 40 + k * rng.randint(150, 200)
            d.polygon([(tx, horizon + 140), (tx + 140, horizon + 140), (tx + 70, horizon + 60)],
                      fill=_jitter((240, 240, 240), rng, 6), outline=(150, 150, 150))
            d.rectangle([tx + 10, horizon + 140, tx + 130, horizon + 220], fill=_jitter((230, 120, 40), rng, 30))
        for k in range(rng.randint(4, 8)):  # chairs
            cx = rng.randint(20, W - 40)
            d.rectangle([cx, H - 140, cx + 30, H - 100], fill=(240, 240, 240), outline=(120, 120, 120))
    elif kind in ("receipt", "document", "register"):
        _desk(d, rng)
        if kind == "register":
            lines = [f"{k + 1:>3}.  Plot {rng.randint(1, 99)}{rng.choice('ABCD')}   allotted   "
                     f"{rng.randint(1, 28):02d}/{rng.randint(1, 12):02d}/{rng.randint(1998, 2024)}" for k in range(14)]
            sheet = _paper(rng, 560, 470, "Allocation register (sample)", lines, issuer="Family allocation book")
        elif kind == "document":
            lines = ["Received the documents listed below", "for processing.", "", "Ref: " + _ref(caption + seed),
                     "", "Officer: SAMPLE OFFICER", "Date: as stamped"]
            sheet = _paper(rng, 520, 440, "Acknowledgement", lines, stamp="RECEIVED", issuer=rng.choice(AGENCIES))
        else:
            amt = rng.randint(80, 2400)
            lines = [f"Receipt no. {_ref(caption + seed, 'R')}", "Received from: SAMPLE CLIENT", "",
                     f"Item: {caption[:34]}", f"Amount: GHS {amt:,}.00", "Paid by: bank transfer", "",
                     "Cashier: sample"]
            sheet = _paper(rng, 440, 470, "OFFICIAL RECEIPT", lines, stamp="PAID",
                           issuer=rng.choice(SCHOOLS + HOSPITALS))
        sheet = sheet.rotate(rng.uniform(-6, 6), expand=True, fillcolor=_jitter((150, 104, 66), rng, 4))
        img.paste(sheet, ((W - sheet.width) // 2 + rng.randint(-30, 30), max(4, (H - BANNER - sheet.height) // 2)))
    elif kind == "id":
        d.rectangle([0, 0, W, H], fill=_jitter((70, 74, 82), rng, 10))
        card = Image.new("RGB", (560, 350), (226, 236, 230))
        cd = ImageDraw.Draw(card)
        cd.rectangle([0, 0, 560, 56], fill=(30, 90, 70))
        cd.text((20, 14), "SAMPLE IDENTITY CARD", fill=(255, 255, 255), font=_font(24))
        cd.rectangle([24, 80, 164, 250], fill=(200, 206, 204), outline=(120, 120, 120))
        cd.ellipse([64, 104, 124, 164], fill=(150, 156, 160))
        cd.pieslice([44, 160, 144, 260], 180, 360, fill=(150, 156, 160))
        for i, (k, v) in enumerate([("Surname", "SAMPLE"), ("Given names", "NOT A REAL PERSON"),
                                    ("Number", "XXX-000000000-0"), ("Date of birth", "01/01/1970")]):
            cd.text((186, 80 + i * 40), k, fill=(90, 96, 100), font=_font(13))
            cd.text((186, 96 + i * 40), v, fill=INK, font=_font(18))
        cd.rectangle([0, 280, 560, 350], fill=RED)
        cd.text((30, 296), "SAMPLE · NOT A REAL ID", fill=(255, 255, 255), font=_font(30))
        card = card.rotate(rng.uniform(-4, 4), expand=True, fillcolor=_jitter((70, 74, 82), rng, 4))
        img.paste(card, ((W - card.width) // 2, (H - BANNER - card.height) // 2))


def _light(img, rng):
    """Patchy light and cloud shadow, different for every seed. Besides looking more like a phone photo, it
    keeps two sample photos of the same scene apart for Tenmina Field's near-duplicate check (average hash)."""
    from PIL import Image, ImageChops, ImageEnhance

    small = Image.new("L", (6, 5))
    small.putdata([rng.randint(185, 255) for _ in range(30)])
    field = small.resize((W, H), Image.Resampling.BICUBIC).convert("RGB")
    return ImageChops.multiply(ImageEnhance.Brightness(img).enhance(1.08), field)


def _frame(img, rng):
    """How the phone was held: a zoom, a shift and a slight tilt, different for every seed."""
    from PIL import Image

    s = rng.uniform(0.62, 0.92)
    cw, ch = int(W * s), int(H * s)
    x, y = rng.randint(0, W - cw), rng.randint(0, H - ch)
    tilted = img.rotate(rng.uniform(-5, 5), resample=Image.Resampling.BILINEAR, center=(x + cw / 2, y + ch / 2))
    return tilted.crop((x, y, x + cw, y + ch)).resize((W, H), Image.Resampling.BILINEAR)


def _banner(img, d, caption):
    d.rectangle([0, H - BANNER, W, H], fill=INK)
    d.rounded_rectangle([12, H - BANNER + 9, 168, H - 9], 6, fill=LIME)
    d.text((22, H - BANNER + 14), "SAMPLE PHOTO", fill=INK, font=_font(18))
    d.text((182, H - BANNER + 14), _latin(caption)[:58], fill=(247, 246, 242), font=_font(17))
    d.rounded_rectangle([W - 158, 10, W - 10, 38], 6, fill=(17, 17, 17))
    d.text((W - 148, 15), "Tenmina demo", fill=(247, 246, 242), font=_font(15))


@lru_cache(maxsize=512)
def photo(kind: str, seed: str = "", *, caption: str = "", model: str | None = None, make: str = "Samsung",
          when: datetime | None = None) -> bytes:
    """A JPEG photo of a drawn scene, marked SAMPLE PHOTO with a caption, 720 x 540, under 150 KB.

    `model`, `make` and `when` go into EXIF as a phone would write them (Tenmina Field checks them)."""
    if kind not in PHOTO_KINDS:
        raise ValueError(f"Unknown sample photo kind: {kind}")
    caption = caption or DEFAULT_CAPTIONS[kind]
    # Drawn scenes of one kind look alike to an 8 x 8 average hash. Tenmina Field flags a capture that is
    # within a few bits of a photo on another project, so a photo too close to one made earlier in this run
    # is framed again (seed#1, seed#2, ...). The same run order always gives the same bytes.
    for n in range(24):
        data = _render(kind, seed if n == 0 else f"{seed}#{n}", caption, model, make, when)
        h = _ahash(data)
        if all(bin(h ^ other).count("1") > NEAR_BITS for other in _SEEN.values()):
            break
    _SEEN[(kind, seed)] = h
    return data


NEAR_BITS = 6
_SEEN: dict = {}


def _ahash(data: bytes) -> int:
    """The same 64-bit average hash as evidence.services._image_meta."""
    from PIL import Image

    px = list(Image.open(io.BytesIO(data)).convert("L").resize((8, 8)).tobytes())
    avg = sum(px) / 64
    return int("".join("1" if p >= avg else "0" for p in px), 2)


def _render(kind, seed, caption, model, make, when) -> bytes:
    from PIL import Image, ImageDraw

    rng = _rng("photo", kind, seed)
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    _scene(kind, rng, img, d, caption, seed)
    img = _light(_frame(img, rng), rng)
    d = ImageDraw.Draw(img)
    _banner(img, d, caption)
    exif = Image.Exif()
    if model:
        exif[271], exif[272] = make, model
    if when:
        exif[306] = when.strftime("%Y:%m:%d %H:%M:%S")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=72, optimize=True, exif=exif)
    return buf.getvalue()


PHOTO_WORDS = [
    (r"defect|crack", "defect"), (r"trench|rebar|foundation|footing|setting.?out|excavat", "foundation"),
    (r"block|wall|lintel|column", "blockwork"), (r"roof|truss", "roofing"),
    (r"finish|paint|plaster|tiling|fixture|handover_photo", "finishing"),
    (r"grocer|shopping|market|delivered", "groceries"), (r"care|checkin|checkout|check_in|check_out|visit", "care"),
    (r"kitchen", "room_kitchen"), (r"living|lounge", "room_living"), (r"front|door|entrance|room", "room_front"),
    (r"receipt|bill_photo", "receipt"), (r"ghana.?card|passport|parent_id|old_card|identity|\bid\b", "id"),
    (r"register|ledger|allocation", "register"), (r"acknowledg|stamp|handover|result", "document"),
    (r"gate", "gate"), (r"pillar|beacon|corner", "pillar"), (r"work_photo|repair|work", "work"),
    (r"listing", "listing"), (r"plot|land|site|survey|satellite", "land"), (r"house|building|unit|bungalow", "house"),
    (r"deliver|event|tent|venue|catering", "delivery"),
]


def photo_kind_for(text: str, default: str = "land") -> str:
    t = (text or "").lower()
    for pattern, kind in PHOTO_WORDS:
        if re.search(pattern, t):
            return kind
    return default


def photo_for(text: str, seed: str = "", *, default="land", **kw) -> bytes:
    """A sample photo whose scene matches the words in `text` (a role, a requirement key or a file name)."""
    return photo(photo_kind_for(text, default), seed or text, **kw)


# --------------------------------------------------------------------------- PDF documents

PDF_KINDS = ("receipt", "invoice", "fee_note", "site_plan", "bank_letter", "bank_advice", "id", "certificate",
             "agreement", "quote", "search_result", "survey", "legal_note", "consent", "policy", "statement",
             "approval", "letter", "errand_result", "report")

TITLES = {
    "receipt": "Official receipt", "invoice": "Invoice", "fee_note": "School fees bill", "site_plan": "Site plan",
    "bank_letter": "Bank letter: account confirmation", "bank_advice": "Bank advice", "id": "Identity document",
    "certificate": "Certificate of registration", "agreement": "Agreement", "quote": "Quotation",
    "search_result": "Official search result", "survey": "Survey report", "legal_note": "Legal note",
    "consent": "Consent form", "policy": "Policy document", "statement": "Statement",
    "approval": "Signed approval", "letter": "Letter", "errand_result": "Certified document", "report": "Report",
}


def _issuer_for(kind, rng):
    return {
        "receipt": rng.choice(SCHOOLS + HOSPITALS), "fee_note": rng.choice(SCHOOLS),
        "invoice": rng.choice(SUPPLIERS), "quote": rng.choice(SUPPLIERS), "bank_letter": rng.choice(BANKS),
        "bank_advice": rng.choice(BANKS), "certificate": rng.choice(AGENCIES), "search_result": AGENCIES[0],
        "survey": LAW[1], "legal_note": LAW[0], "agreement": LAW[0], "consent": LAW[0],
        "policy": INSURERS[0], "errand_result": rng.choice(AGENCIES), "site_plan": LAW[1],
        "id": "Sample identity authority", "approval": LAW[0],
    }.get(kind, "Tenmina demo data")


@lru_cache(maxsize=512)
def _pdf_cached(kind, seed, title, issuer, reference, to, lines, items, amount, currency, on, note):
    from fpdf import FPDF

    rng = _rng("pdf", kind, seed)
    pdf = FPDF(format="A4")
    pdf.set_compression(True)
    pdf.set_creation_date(FIXED_DATE)
    pdf.set_title(_latin(f"SAMPLE {title}"))
    pdf.set_author("Tenmina demo data")
    pdf.set_creator("Tenmina samples")
    pdf.set_producer("Tenmina")
    pdf.set_auto_page_break(True, margin=22)
    pdf.add_page()
    w = pdf.epw
    # Watermark
    pdf.set_text_color(236, 232, 226)
    pdf.set_font("Helvetica", "B", 92)
    with pdf.rotation(35, x=105, y=160):
        pdf.text(28, 190, "SAMPLE")
    pdf.set_text_color(17, 17, 17)
    # Letterhead
    pdf.set_fill_color(17, 17, 17)
    pdf.rect(pdf.l_margin, 12, w, 18, style="F")
    pdf.set_xy(pdf.l_margin + 4, 15)
    pdf.set_text_color(247, 246, 242)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(w - 54, 6, _latin(issuer), new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(pdf.l_margin + 4)
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(w - 54, 5, "Fictional organisation for demo data. Not a real record.")
    pdf.set_fill_color(*LIME)
    pdf.set_text_color(17, 17, 17)
    pdf.set_xy(pdf.l_margin + w - 44, 16)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(40, 10, "SAMPLE", align="C", fill=True)
    pdf.set_xy(pdf.l_margin, 36)
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(w, 10, _latin(title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    meta = [("Reference", reference), ("Date", on)]
    if to:
        meta.append(("To", to))
    for k, v in meta:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(30, 6, _latin(k))
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(w - 30, 6, _latin(v), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    if kind == "site_plan":
        _site_plan(pdf, rng, w)
    if kind == "id":
        pdf.set_fill_color(*RED)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 20)
        pdf.cell(w, 16, _latin("SAMPLE · NOT A REAL ID"), align="C", fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(17, 17, 17)
        pdf.ln(3)
    pdf.set_font("Helvetica", "", 10)
    for ln in lines:
        pdf.multi_cell(w, 5.4, _latin(ln), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)
    if items:
        pdf.ln(2)
        pdf.set_fill_color(240, 238, 232)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(w - 45, 7, "Item", fill=True)
        pdf.cell(45, 7, "Amount", fill=True, align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        for label, amt in items:
            pdf.cell(w - 45, 7, _latin(label), border="B")
            pdf.cell(45, 7, _latin(_money(amt, currency)), border="B", align="R", new_x="LMARGIN", new_y="NEXT")
    if amount is not None:
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 12)
        label = {"receipt": "Amount received", "quote": "Quoted total", "bank_advice": "Amount"}.get(kind, "Total")
        pdf.cell(w - 45, 9, label)
        pdf.cell(45, 9, _latin(_money(amount, currency)), align="R", new_x="LMARGIN", new_y="NEXT")
    if kind in ("receipt", "certificate", "errand_result", "search_result", "bank_letter", "bank_advice"):
        x, y = pdf.l_margin + w - 46, pdf.get_y() + 6
        pdf.set_draw_color(40, 70, 170)
        pdf.set_line_width(0.8)
        pdf.ellipse(x, y, 40, 40)
        pdf.set_text_color(40, 70, 170)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_xy(x, y + 15)
        pdf.cell(40, 10, {"receipt": "PAID", "bank_letter": "CONFIRMED", "bank_advice": "PROCESSED"}.get(
            kind, "CERTIFIED"), align="C")
        pdf.set_text_color(17, 17, 17)
        pdf.set_y(y + 44)
    if kind in ("agreement", "consent", "approval", "quote", "policy", "legal_note", "survey", "bank_letter"):
        pdf.ln(8)
        pdf.set_font("Helvetica", "", 10)
        for who in ("Signed for the first party", "Signed for the second party"
                    if kind in ("agreement", "consent") else "Authorised signatory"):
            pdf.cell(w / 2, 6, "______________________________")
        pdf.ln(6)
        for who in ("First party (sample)", "Second party (sample)" if kind in ("agreement", "consent")
                    else "Authorised signatory (sample)"):
            pdf.cell(w / 2, 6, who)
        pdf.ln(8)
    if note:
        pdf.ln(2)
        pdf.set_font("Helvetica", "I", 9)
        pdf.multi_cell(w, 5, _latin(note), new_x="LMARGIN", new_y="NEXT")
    pdf.set_auto_page_break(False)
    pdf.set_y(-26)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(110, 110, 110)
    pdf.multi_cell(w, 4, "SAMPLE DOCUMENT for Tenmina demo data. The organisation, people and figures are "
                         "fictional working assumptions. It is not a real record and has no legal effect.",
                   new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def _site_plan(pdf, rng, w):
    x0, y0, size = pdf.l_margin + 10, pdf.get_y() + 4, 110
    pdf.set_draw_color(180, 180, 180)
    pdf.set_line_width(0.1)
    for k in range(0, size + 1, 10):  # grid
        pdf.line(x0 + k, y0, x0 + k, y0 + size)
        pdf.line(x0, y0 + k, x0 + size, y0 + k)
    pts = [(x0 + rng.uniform(15, 35), y0 + rng.uniform(15, 30)), (x0 + rng.uniform(75, 95), y0 + rng.uniform(10, 25)),
           (x0 + rng.uniform(80, 100), y0 + rng.uniform(80, 95)), (x0 + rng.uniform(10, 30), y0 + rng.uniform(75, 100))]
    pdf.set_draw_color(17, 17, 17)
    pdf.set_line_width(0.7)
    pdf.polygon(pts, style="D")
    pdf.set_font("Helvetica", "B", 8)
    for i, (px, py) in enumerate(pts):
        pdf.set_fill_color(200, 40, 40)
        pdf.circle(px - 1.5, py - 1.5, 3, style="F")
        pdf.text(px + 2, py - 2, f"P{i + 1}")
    pdf.set_font("Helvetica", "", 8)
    pdf.text(x0 + size + 6, y0 + 6, "N")
    pdf.line(x0 + size + 7.5, y0 + 8, x0 + size + 7.5, y0 + 22)
    pdf.text(x0, y0 + size + 6, "Scale 1:1000 (sample). Coordinates are illustrative only.")
    pdf.set_y(y0 + size + 10)
    lat, lng = rng.uniform(5.55, 5.70), rng.uniform(-0.30, -0.10)
    pdf.set_font("Helvetica", "", 9)
    for i in range(4):
        pdf.cell(w, 5, f"Pillar P{i + 1}: {lat + rng.uniform(-0.001, 0.001):.6f} N, "
                       f"{abs(lng + rng.uniform(-0.001, 0.001)):.6f} W", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(w, 5, f"Area about {rng.uniform(0.12, 0.3):.2f} acres (sample).", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)


DEFAULT_LINES = {
    "receipt": ["Received with thanks for the item below.", "Paid by bank transfer from the partner bank."],
    "invoice": ["Please pay the amount below to the account on file.", "Payment terms: 14 days."],
    "fee_note": ["Fees for the coming term.", "Pay to the school's verified bank account only."],
    "bank_letter": ["We confirm that the account below is held with us in the name shown.",
                    "Account name: SAMPLE ACCOUNT HOLDER", "Account number: ending 0000 (sample)"],
    "bank_advice": ["We confirm the transfer below was processed today.", "Value date: as shown."],
    "id": ["This placeholder stands in for an identity document in demo data.",
           "Name: SAMPLE PERSON", "Number: XXX-000000000-0"],
    "certificate": ["This certifies that the organisation named is registered.",
                    "Registration number: shown above.", "Valid until: renewal date on the register."],
    "agreement": ["The parties agree to the terms set out in the schedule.",
                  "Money is held by the licensed partner bank and released only on approved instructions."],
    "quote": ["Quotation for the work below. Valid for 30 days.", "Labour and materials included."],
    "search_result": ["Result of an official search of the register for the plot named.",
                      "Registered interests: as listed. Caveats: none recorded (sample)."],
    "survey": ["The pillars found on site were measured against the site plan.",
               "Difference found: within 0.5 m (sample figure)."],
    "legal_note": ["Summary of the documents reviewed and the findings.", "Recommendation: proceed with conditions."],
    "consent": ["The family heads named consent to the sale of the plot described.",
                "Witnessed at the family meeting."],
    "policy": ["Policy schedule and terms for the cover named.", "The insurer is licensed; Tenmina only introduces."],
    "statement": ["Statement of bills, payments and receipts for the period."],
    "approval": ["I have read the text and approve it for publication."],
    "letter": ["Please find the details below."],
    "errand_result": ["Certified copy issued on request.", "Collected by Tenmina's agent and handed over."],
    "report": ["Findings and evidence are set out below."],
    "site_plan": ["Site plan of the plot named, with pillar positions."],
}


def pdf(kind: str, seed: str = "", *, title: str | None = None, issuer: str | None = None,
        reference: str | None = None, to: str | None = None, lines=None, items=None, amount=None,
        currency: str = "GHS", on: date | str | None = None, note: str | None = None) -> bytes:
    """A one-page PDF marked SAMPLE: letterhead, title, reference, lines, an optional item table and total."""
    if kind not in PDF_KINDS:
        raise ValueError(f"Unknown sample document kind: {kind}")
    rng = _rng("pdf-defaults", kind, seed)
    issuer = issuer or _issuer_for(kind, rng)
    if not issuer.lower().endswith("(sample)"):
        issuer = f"{issuer} (sample)"
    on = on or date(2026, rng.randint(6, 10), rng.randint(1, 28))
    on = on.strftime("%d %B %Y") if isinstance(on, (date, datetime)) else str(on)
    lines = tuple(lines) if lines else tuple(DEFAULT_LINES.get(kind, []))
    if seed:
        lines = lines + (f"Document: {seed}",)
    items = tuple((str(a), str(b)) for a, b in items) if items else ()
    return _pdf_cached(kind, seed, title or TITLES[kind], issuer, reference or _ref(f"{kind}|{seed}"), to or "",
                       lines, items, None if amount is None else str(amount), currency, on, note or "")


DOC_WORDS = [
    (r"site.?plan|plot.?plan|cadastral", "site_plan"), (r"receipt|proof.?of.?payment", "receipt"),
    (r"school|term.?fee|fees.?bill|fee.?note", "fee_note"), (r"invoice|bill", "invoice"),
    (r"credit.?advice|debit.?advice|bank.?advice|remittance|bank.?confirmation|bulk", "bank_advice"),
    (r"bank.?letter|bank.?ack|account.?confirm", "bank_letter"),
    (r"ghana.?card|passport|old_card|parent_id|identity|\bid\b", "id"),
    (r"registration|certificate|licen[cs]e|company", "certificate"),
    (r"search", "search_result"), (r"survey", "survey"), (r"legal|title|indenture|deed|lawyer-opinion", "legal_note"),
    (r"consent", "consent"), (r"agreement|mandate|tenancy|contract|terms-signed", "agreement"),
    (r"quote|quotation|estimate|boq", "quote"), (r"policy|terms", "policy"), (r"statement", "statement"),
    (r"approval|sign.?off|lawyer|insurer", "approval"), (r"birth|certified|result|marriage", "errand_result"),
    (r"report", "report"),
]


def doc_kind_for(text: str, default: str = "letter") -> str:
    t = (text or "").lower().replace("_", "-")
    for pattern, kind in DOC_WORDS:
        if re.search(pattern, t):
            return kind
    return default


def _title_from(name: str) -> str:
    stem = re.sub(r"\.(pdf|txt|jpe?g|png)$", "", name or "", flags=re.I)
    stem = re.sub(r"[-_]+", " ", stem).strip()
    return stem[:1].upper() + stem[1:] if stem else ""


def file_for(name: str, content_type: str | None = None, *, seed: str | None = None, model: str | None = None,
             make: str = "Samsung", when: datetime | None = None, **doc) -> tuple[bytes, str, str]:
    """A sample file for a seed: (bytes, content type, file name).

    `name` is the role or file name ("receipt-KATH-0120", "site_photo", "quote-roofworks.txt"). Images come
    back as JPEG photos, everything else as a PDF; pass `content_type` to force one. Extra keyword arguments
    (issuer, amount, currency, lines, title, to) go into the PDF."""
    seed = seed or name
    stem = re.sub(r"\.(pdf|txt|jpe?g|png)$", "", name or "sample", flags=re.I)
    want_image = content_type in ("image/jpeg", "image/jpg") or (
        content_type is None and re.search(r"\.(jpe?g|png)$|photo|picture|image", name or "", re.I))
    if want_image:
        kind = photo_kind_for(stem)
        return photo(kind, seed, caption=doc.get("title") or _title_from(stem) or DEFAULT_CAPTIONS[kind],
                     model=model, make=make, when=when), "image/jpeg", f"{stem}.jpg"
    kind = doc_kind_for(stem)
    doc.setdefault("title", f"{TITLES[kind]}: {_title_from(stem)}" if kind in ("letter", "report", "approval")
                   else None)
    return pdf(kind, seed, **doc), "application/pdf", f"{stem}.pdf"
