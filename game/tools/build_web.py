#!/usr/bin/env python3
"""Web版を1枚のHTMLに焼き込む。

`game/web/*.js` は engine と試遊版の移植で、数値は持っていない。ここが
**data と仮絵をその中に流し込む**ところ。data を直したら、このコマンドを
もう一度走らせれば Web版も同じ数字になる。

呪文ストックの並びだけは Python 側で引いてから焼き込む。Mersenne Twister を
JS に移植すると、そこが新しい食い違いの種になるので、乱数は移植しない
（一致試験は game/tools/conform.py）。

依存なし。

    $ python3 game/tools/build_web.py           # game/web/out/index.html
    $ python3 game/tools/build_web.py --matches 60
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from game.engine.data import DATA_DIR, load                 # noqa: E402
from game.engine.draft import commit, match_seed, stock_sequence  # noqa: E402
from game.engine.presets import PRESETS, trial_six          # noqa: E402
from game.tools import sprites as S                         # noqa: E402

WEB = ROOT / "game" / "web"
OUT = WEB / "out"
DATA_NAMES = ("characters", "cards", "trumps", "perks", "avatars", "match")


def bbox_top(canvas) -> int:
    """絵の実体が上から何ドット目で始まるか。

    体力の棒をここに合わせないと、頭の遥か上に浮く（view.py と同じ理由）。
    PNG を読み直さず、生成器の出力をそのまま測る。
    """
    for y, row in enumerate(canvas.px):
        if any(index != S.CLEAR for index in row):
            return y
    return 0


def art_bundle(game, unit_ids: list[str], avatar_ids: list[str]) -> dict:
    """使うぶんの仮絵だけを data: URI にする。全32体は積まない。"""
    palettes = json.loads((S.ART / "palette.json").read_text(encoding="utf-8"))
    units = list(game.units.values())
    bounds = {
        "cost": (min(u.cost for u in units), max(u.cost for u in units)),
        "hp": (min(u.hp for u in units), max(u.hp for u in units)),
        "speed": (min(u.speed_mps for u in units), max(u.speed_mps for u in units)),
    }

    def ramp(entry):
        return [(0, 0, 0, 0)] + [S.hex_rgba(entry[k]) for k in
                                 ("outline", "shadow", "base", "light",
                                  "accent", "dark_accent")]

    def uri(path: Path) -> str:
        return "data:image/png;base64," + base64.b64encode(
            path.read_bytes()).decode("ascii")

    out = {"units": {}, "avatars": {}, "bbox": {}, "families": {}}
    tmp = OUT / "_png"
    for uid in unit_ids:
        unit = game.units[uid]
        canvas = S.draw_unit(unit, bounds, game.wall_threshold)
        path = tmp / f"{uid}.png"
        S.write_png(path, canvas.to_rgba(ramp(palettes["families"][unit.family])))
        out["units"][uid] = uri(path)
        out["bbox"][uid] = bbox_top(canvas)

    for aid in avatar_ids:
        avatar = game.avatars[aid]
        canvas = S.draw_avatar(avatar.look)
        path = tmp / f"avatar-{aid}.png"
        S.write_png(path, canvas.to_rgba(ramp(palettes["looks"][avatar.look])))
        out["avatars"][aid] = uri(path)

    for name, entry in palettes["families"].items():
        out["families"][name] = entry["base"]
    return out


# 並びを1枚あたり1文字に詰めるための字。96枚×240本を素で書くと
# ファイルの半分が呪文の名前になるので、番号にして畳む。
ALPHABET = ("ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            "abcdefghijklmnopqrstuvwxyz0123456789")


def stock_table(game, trial: dict, matches: int) -> dict:
    """試合ごとの呪文ストックの並び。Python 版とまったく同じ引き方をする。

    play/__main__.py の make_battle と同じ順に seed を作るので、
    同じ試合番号なら手元の Python 版と同じ札が流れてくる。
    """
    names = list(game.cards)
    if len(names) > len(ALPHABET):
        raise SystemExit(f"呪文が {len(names)} 種で、詰める字が足りない")
    index = {name: ALPHABET[i] for i, name in enumerate(names)}

    unit_ids = tuple(u["id"] for u in trial["roster"])
    brought, trump = trial["brought"], trial["trump"]

    def packed(seed: str) -> str:
        return "".join(index[c] for c in stock_sequence(game, seed, 96))

    table = {}
    for enemy in sorted(PRESETS):
        rows = []
        for i in range(matches):
            match_id = f"play-{i}"
            seed = match_seed(
                commit(unit_ids, (brought,), trump, f"{match_id}:a"),
                commit(tuple(PRESETS[enemy][1]), (PRESETS[enemy][2],),
                       PRESETS[enemy][3], f"{match_id}:b"),
                match_id)
            rows.append([packed(f"{seed}:a"), packed(f"{seed}:b")])
        table[enemy] = rows
    return {"cards": names, "matches": table}


def build(matches: int) -> Path:
    game = load()
    trial = trial_six()
    unit_ids = [u["id"] for u in trial["roster"]]

    raw = {name: json.loads((DATA_DIR / f"{name}.json").read_text(encoding="utf-8"))
           for name in DATA_NAMES}
    preset = json.loads((DATA_DIR / "preset_six.json").read_text(encoding="utf-8"))

    OUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "raw": raw,
        "preset": preset,
        "art": art_bundle(game, unit_ids, [trial["avatar"]]),
        "stocks": stock_table(game, trial, matches),
    }

    html = (WEB / "template.html").read_text(encoding="utf-8")
    parts = {
        "/*DATA*/": "const DATA = " + json.dumps(payload, ensure_ascii=False,
                                                 separators=(",", ":")) + ";",
        "/*ENGINE*/": (WEB / "engine.js").read_text(encoding="utf-8"),
        "/*VIEW*/": (WEB / "view.js").read_text(encoding="utf-8"),
        "/*MAIN*/": (WEB / "main.js").read_text(encoding="utf-8"),
    }
    for mark, body in parts.items():
        if mark not in html:
            raise SystemExit(f"template.html に {mark} が無い")
        html = html.replace(mark, body)

    target = OUT / "index.html"
    target.write_text(html, encoding="utf-8")

    for path in sorted((OUT / "_png").glob("*.png")):
        path.unlink()
    (OUT / "_png").rmdir()

    size = target.stat().st_size
    print(f"{target.relative_to(ROOT)} — {size / 1024:.0f} KB")
    print(f"  ユニット {len(unit_ids)} / アバター 1 / "
          f"呪文の並び {len(payload['stocks']['matches'])}方針 × {matches}試合")
    return target


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="build_web")
    parser.add_argument("--matches", type=int, default=40,
                        help="呪文ストックを焼き込む試合数。これを超えると先頭に戻る")
    args = parser.parse_args(argv)
    build(args.matches)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
