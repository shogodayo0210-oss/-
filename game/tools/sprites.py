#!/usr/bin/env python3
"""ユニットとアバターの仮ドット絵を、data の数字から生成する。

本番の絵は人が描く。これはその前に置く**プレースホルダ**で、目的は2つ。

1. 32体ぶんの見た目を今すぐ用意して、試遊版に何かを映せるようにする
2. `art/README.md` に書いたシルエットの規約を、文章ではなく**実行できる形**にする
   ―― 射程が長ければ武器が長く、壁なら盾を持ち、速ければ前傾する。
   絵描きが入る時は、この出力が仕様書代わりになる。

依存なし（PNGの書き出しも zlib と struct だけでやる）。

    python3 game/tools/sprites.py            # game/art/out/ に書き出す
    python3 game/tools/sprites.py --sheet    # 一覧シートだけ
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from game.engine.data import Unit, load  # noqa: E402

ART = Path(__file__).resolve().parent.parent / "art"
OUT = ART / "out"
UNIT_PX = 48
AVATAR_PX = 64


# --------------------------------------------------------------------- PNG
def write_png(path: Path, pixels: list[list[tuple[int, int, int, int]]]) -> None:
    """RGBAの2次元配列をPNGにする。"""
    height, width = len(pixels), len(pixels[0])
    raw = bytearray()
    for row in pixels:
        raw.append(0)                                   # フィルタなし
        for r, g, b, a in row:
            raw += bytes((r, g, b, a))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
           + chunk(b"IEND", b""))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


def hex_rgba(value: str) -> tuple[int, int, int, int]:
    value = value.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), 255)


# ------------------------------------------------------------------ キャンバス
CLEAR, OUTLINE, SHADOW, BASE, LIGHT, ACCENT, DARKACC = range(7)


class Canvas:
    """パレット番号で描く。色は最後に流し込む。"""

    def __init__(self, size: int):
        self.size = size
        self.px = [[CLEAR] * size for _ in range(size)]

    def set(self, x: int, y: int, index: int) -> None:
        if 0 <= x < self.size and 0 <= y < self.size:
            self.px[y][x] = index

    def get(self, x: int, y: int) -> int:
        if 0 <= x < self.size and 0 <= y < self.size:
            return self.px[y][x]
        return CLEAR

    def rect(self, x0, y0, x1, y1, index=BASE) -> None:
        for y in range(int(y0), int(y1) + 1):
            for x in range(int(x0), int(x1) + 1):
                self.set(x, y, index)

    def ellipse(self, cx, cy, rx, ry, index=BASE) -> None:
        if rx <= 0 or ry <= 0:
            return
        for y in range(int(cy - ry), int(cy + ry) + 1):
            for x in range(int(cx - rx), int(cx + rx) + 1):
                dx, dy = (x - cx) / rx, (y - cy) / ry
                if dx * dx + dy * dy <= 1.0:
                    self.set(x, y, index)

    def line(self, x0, y0, x1, y1, index=BASE, thick=1) -> None:
        steps = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
        for i in range(steps + 1):
            t = i / max(steps, 1)
            x, y = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
            for oy in range(thick):
                for ox in range(thick):
                    self.set(int(x) + ox, int(y) + oy, index)

    def shade(self) -> None:
        """上を明るく、下と後ろを暗く。光は左上から。"""
        body = [(x, y) for y in range(self.size) for x in range(self.size)
                if self.px[y][x] == BASE]
        if not body:
            return
        top = min(y for _, y in body)
        bottom = max(y for _, y in body)
        span = max(bottom - top, 1)
        for x, y in body:
            depth = (y - top) / span
            if depth < 0.28 and self.get(x, y - 1) == CLEAR:
                self.px[y][x] = LIGHT
            elif depth > 0.66:
                self.px[y][x] = SHADOW

    def outline(self) -> None:
        """本体の外周1pxを輪郭にする。小さくしても形が読めるように。"""
        filled = {(x, y) for y in range(self.size) for x in range(self.size)
                  if self.px[y][x] not in (CLEAR, OUTLINE)}
        edge = set()
        for x, y in filled:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                if (x + dx, y + dy) not in filled:
                    edge.add((x + dx, y + dy))
        for x, y in edge:
            if self.get(x, y) == CLEAR:
                self.set(x, y, OUTLINE)

    def to_rgba(self, palette: list[tuple[int, int, int, int]]):
        return [[palette[i] for i in row] for row in self.px]


# ------------------------------------------------------------------ 形の規約
def norm(value: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.5
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def silhouette(unit: Unit, wall_line: float) -> str:
    """数字からシルエットの型を決める。art/README.md の規約そのもの。"""
    if unit.near > 0:
        return "mortar"          # 後方範囲：死角を持つ＝上に向いた砲身
    if unit.is_wall(wall_line):
        return "wall"            # 壁：横に広く、盾を前に
    if unit.cost >= 450:
        return "heavy"           # 大型：画面を埋める
    if unit.far > 50:
        return "ranged"          # 遠距離：細く高く、長い得物
    if unit.speed_mps >= 9:
        return "fast"            # 高速：前傾、小さい
    return "melee"


def draw_unit(unit: Unit, bounds: dict, wall_line: float) -> Canvas:
    c = Canvas(UNIT_PX)
    S = UNIT_PX
    shape = silhouette(unit, wall_line)

    big = norm(unit.cost, bounds["cost"][0], bounds["cost"][1])
    tough = norm(unit.hp, bounds["hp"][0], bounds["hp"][1])
    quick = norm(unit.speed_mps, bounds["speed"][0], bounds["speed"][1])

    ground = S - 5
    height = int(16 + 20 * big)                      # 体高
    girth = int(4 + 7 * tough)                       # 胴の太さ
    if shape == "wall":
        girth += 3
        height -= 4
    if shape in ("fast", "ranged"):
        girth = max(3, girth - 3)
    if shape == "heavy":
        girth += 2

    cx = S // 2 - int(3 * quick)                     # 速いほど後ろ足重心＝前傾
    top = ground - height
    lean = int(3 * quick)                            # 前傾の量

    # 影
    c.ellipse(S // 2 + 1, ground + 2, girth + 3, 2, SHADOW)

    # 脚
    leg_top = ground - height // 3
    c.rect(cx - girth + 1, leg_top, cx - girth + 3, ground, BASE)
    c.rect(cx + girth - 3, leg_top, cx + girth - 1, ground, BASE)
    if unit.family == "精霊":                         # 精霊は浮く
        c.rect(cx - girth + 1, leg_top, cx + girth - 1, ground, CLEAR)
        c.ellipse(cx, ground - 1, girth - 1, 2, BASE)

    # 胴
    body_top = top + height // 4
    c.ellipse(cx + lean // 2, (body_top + leg_top) // 2,
              girth, (leg_top - body_top) // 2 + 1, BASE)
    if unit.family == "機械":                         # 機械は角張らせる
        c.rect(cx - girth + lean // 2, body_top,
               cx + girth + lean // 2, leg_top, BASE)

    # 頭
    head_r = int(3 + 3 * big)
    hx, hy = cx + lean, top + head_r
    c.ellipse(hx, hy, head_r, head_r, BASE)
    if unit.family == "獣":                           # 獣は耳と尾
        c.line(hx - head_r + 1, hy - head_r, hx - head_r - 1, hy - head_r - 3, BASE, 2)
        c.line(hx + 1, hy - head_r, hx + 2, hy - head_r - 4, BASE, 2)
        c.line(cx - girth, leg_top - 2, cx - girth - 5, leg_top - 6, BASE, 2)
    if unit.family == "不死":                         # 不死は裾がほつれる
        for x in range(cx - girth, cx + girth + 1, 3):
            c.set(x, ground, CLEAR)
            c.set(x, ground - 1, CLEAR)
    if unit.family == "機械":
        c.line(hx, hy - head_r, hx, hy - head_r - 4, ACCENT, 1)
        c.set(hx, hy - head_r - 5, ACCENT)

    # 目（向きを出す）
    c.set(hx + head_r - 2, hy - 1, ACCENT)
    if unit.family != "不死":
        c.set(hx + head_r - 2, hy, DARKACC)

    # ---- 得物：帯の数字がそのまま形になる ----
    hand_x, hand_y = cx + girth + lean, leg_top - (leg_top - body_top) // 2
    reach = int(4 + 16 * norm(unit.far, 8, 160))

    if shape == "mortar":
        c.line(hand_x - 2, hand_y, hand_x + reach // 2, hand_y - reach, ACCENT, 3)
        c.ellipse(hand_x - 3, hand_y + 2, 4, 3, DARKACC)
    elif shape == "ranged":
        for i in range(-reach // 2, reach // 2 + 1):
            off = int((1 - (i / max(reach // 2, 1)) ** 2) * 3)
            c.set(hand_x + off, hand_y + i, ACCENT)
        c.line(hand_x, hand_y - reach // 2, hand_x, hand_y + reach // 2, DARKACC)
    elif shape == "wall":
        c.rect(hand_x, hand_y - girth - 3, hand_x + 3, hand_y + girth + 3, ACCENT)
        c.rect(hand_x + 1, hand_y - 1, hand_x + 2, hand_y + 1, DARKACC)
    else:
        c.line(hand_x, hand_y, hand_x + reach, hand_y - reach // 3, ACCENT, 2)
        if unit.anti_wall_mult > 1.5:                # 壁特攻は刃を厚く
            c.line(hand_x + reach // 2, hand_y - reach // 6,
                   hand_x + reach, hand_y - reach // 3, DARKACC, 3)

    # 攻城具：拠点を割る役ほど背中の装備が大きい
    if unit.siege_mult >= 1.3:
        c.rect(cx - girth - 3 + lean // 2, body_top + 1,
               cx - girth + lean // 2, body_top + 5 + int(4 * big), DARKACC)

    c.shade()
    c.outline()
    return c


def draw_avatar(look: str) -> Canvas:
    """アバターは拠点そのもの。城と人が一体になった形にする。"""
    c = Canvas(AVATAR_PX)
    S = AVATAR_PX
    ground = S - 5

    wide = {"剛力": 20, "王道": 17, "知性": 13, "可憐": 14, "俊敏": 12, "怪異": 15}[look]
    tall = {"剛力": 30, "王道": 34, "知性": 38, "可憐": 30, "俊敏": 36, "怪異": 33}[look]
    cx = S // 2

    c.ellipse(cx, ground + 2, wide + 3, 3, SHADOW)
    c.rect(cx - wide, ground - tall, cx + wide, ground, BASE)      # 塔
    for x in range(cx - wide, cx + wide + 1, 5):                   # 狭間
        c.rect(x, ground - tall - 3, x + 2, ground - tall, BASE)
    c.rect(cx - wide + 3, ground - tall + 6, cx + wide - 3,
           ground - tall + 8, DARKACC)                             # 帯

    head_r = 9
    hy = ground - tall - head_r - 3                                # 狭間より上に出す
    c.ellipse(cx, hy, head_r, head_r, BASE)                        # 顔
    c.rect(cx - 4, hy - 1, cx - 3, hy, DARKACC)
    c.rect(cx + 3, hy - 1, cx + 4, hy, DARKACC)

    if look == "可憐":                                             # リボン
        c.ellipse(cx - head_r - 2, hy - head_r + 1, 3, 2, ACCENT)
        c.ellipse(cx + head_r + 2, hy - head_r + 1, 3, 2, ACCENT)
    elif look == "剛力":                                           # 角
        c.line(cx - head_r, hy - head_r + 1, cx - head_r - 4, hy - head_r - 4, ACCENT, 2)
        c.line(cx + head_r, hy - head_r + 1, cx + head_r + 4, hy - head_r - 4, ACCENT, 2)
    elif look == "知性":                                           # 尖り帽
        for i in range(9):
            c.rect(cx - 5 + i // 2, hy - head_r - i, cx + 5 - i // 2, hy - head_r - i, ACCENT)
    elif look == "俊敏":                                           # なびく布
        c.line(cx - head_r, hy, cx - head_r - 9, hy + 5, ACCENT, 2)
    elif look == "怪異":                                           # 仮面
        c.rect(cx - head_r, hy - 2, cx + head_r, hy + 1, ACCENT)
    else:                                                          # 王道：王冠
        for i in range(5):
            c.rect(cx - 5 + i * 2, hy - head_r - 3 - (i % 2) * 2, cx - 4 + i * 2,
                   hy - head_r, ACCENT)

    c.shade()
    c.outline()
    return c


# ------------------------------------------------------------------ 一覧シート
FONT = {
    "a": "010101111101", "b": "110101110101", "c": "011100100011",
    "d": "110101101110", "e": "111100110111", "f": "111100110100",
    "g": "011100101011", "h": "101101111101", "i": "111010010111",
    "j": "001001101010", "k": "101110110101", "l": "100100100111",
    "m": "101111111101", "n": "110101101101", "o": "010101101010",
    "p": "110101110100", "q": "010101111011", "r": "110101110101",
    "s": "011100010110", "t": "111010010010", "u": "101101101011",
    "v": "101101101010", "w": "101111111111", "x": "101010010101",
    "y": "101101010010", "z": "111001010111", "_": "000000000111",
}


def stamp_text(sheet, x0, y0, text, color) -> None:
    """3×4の極小フォント。名前ではなくidを置くだけの用途。"""
    for i, ch in enumerate(text.lower()):
        bits = FONT.get(ch)
        if not bits:
            continue
        for row in range(4):
            for col in range(3):
                if bits[row * 3 + col] == "1":
                    y, x = y0 + row, x0 + i * 4 + col
                    if 0 <= y < len(sheet) and 0 <= x < len(sheet[0]):
                        sheet[y][x] = color


def contact_sheet(tiles, cell, columns, bg, label_color):
    rows = (len(tiles) + columns - 1) // columns
    pad, label = 4, 6
    width = columns * (cell + pad) + pad
    height = rows * (cell + pad + label) + pad
    sheet = [[bg] * width for _ in range(height)]
    for i, (name, rgba) in enumerate(tiles):
        r, col = divmod(i, columns)
        ox = pad + col * (cell + pad)
        oy = pad + r * (cell + pad + label)
        for y in range(cell):
            for x in range(cell):
                pixel = rgba[y][x]
                if pixel[3]:
                    sheet[oy + y][ox + x] = pixel
        stamp_text(sheet, ox, oy + cell + 1, name[:11], label_color)
    return sheet


# ---------------------------------------------------------------------- main
def main() -> int:
    parser = argparse.ArgumentParser(prog="sprites")
    parser.add_argument("--sheet", action="store_true", help="一覧シートだけ書く")
    args = parser.parse_args()

    game = load()
    palettes = json.load(open(ART / "palette.json", encoding="utf-8"))
    wall_line = game.wall_threshold
    units = list(game.units.values())
    bounds = {
        "cost": (min(u.cost for u in units), max(u.cost for u in units)),
        "hp": (min(u.hp for u in units), max(u.hp for u in units)),
        "speed": (min(u.speed_mps for u in units), max(u.speed_mps for u in units)),
    }

    def ramp(entry):
        return [(0, 0, 0, 0)] + [hex_rgba(entry[k]) for k in
                                 ("outline", "shadow", "base", "light",
                                  "accent", "dark_accent")]

    unit_tiles = []
    for unit in units:
        pal = ramp(palettes["families"][unit.family])
        rgba = draw_unit(unit, bounds, wall_line).to_rgba(pal)
        unit_tiles.append((unit.id, rgba))
        if not args.sheet:
            write_png(OUT / "units" / f"{unit.id}.png", rgba)

    avatar_tiles = []
    for avatar in game.avatars.values():
        pal = ramp(palettes["looks"][avatar.look])
        rgba = draw_avatar(avatar.look).to_rgba(pal)
        avatar_tiles.append((avatar.id, rgba))
        if not args.sheet:
            write_png(OUT / "avatars" / f"{avatar.id}.png", rgba)

    bg = hex_rgba(palettes["sheet"]["background"])
    label = hex_rgba(palettes["sheet"]["label"])
    write_png(OUT / "units_sheet.png", contact_sheet(unit_tiles, UNIT_PX, 8, bg, label))
    write_png(OUT / "avatars_sheet.png",
              contact_sheet(avatar_tiles, AVATAR_PX, 6, bg, label))

    print(f"ユニット {len(unit_tiles)} / アバター {len(avatar_tiles)} を "
          f"{OUT.relative_to(ART.parent.parent)} に書き出した")
    counts: dict[str, int] = {}
    for unit in units:
        counts[silhouette(unit, wall_line)] = counts.get(
            silhouette(unit, wall_line), 0) + 1
    print("シルエットの内訳: " + " / ".join(
        f"{k} {v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
