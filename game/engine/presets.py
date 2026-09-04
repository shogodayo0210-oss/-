"""見本の編成。

編成フェーズ（設計書3章）はまだ人が操作する形になっていないので、
ここで決め打ちにしてある。CLI も試遊版も同じものを使う。
"""

from __future__ import annotations

import json

from .battle import Loadout
from .data import DATA_DIR
from .draft import draw_random_slots, pick_template


def trial_six(data_dir=DATA_DIR) -> dict:
    """試遊用の6種（工程表 塊A-2）。両者これを使う。

    32体を並べると何が効いたのか分からないので、役割が数字で割れる6体に
    絞ってある。理由は `data/preset_six.json` に1体ずつ書いてある。
    """
    with open(data_dir / "preset_six.json", encoding="utf-8") as f:
        return json.load(f)["trial"]


def trial_loadout(game, seed: str, side: str) -> Loadout:
    """同じ持ち物で戦うための編成。**抽選枠を足さない**のがこの関数の要点で、
    人とAIの持ち物が完全に同じになる（ストックの並びだけ側ごとに違う）。"""
    spec = trial_six()
    return Loadout(avatar=spec["avatar"],
                   roster=tuple(u["id"] for u in spec["roster"]),
                   brought=spec["brought"], trump=spec["trump"],
                   stock_seed=f"{seed}:{side}")

# アバター / 出撃6種 / 持ち込む呪文1枚 / 切り札
PRESETS = {
    "rush":     ("scout",   ["grunt", "spear", "twin", "archer", "shield", "sweeper"],
                 "advance", "gale_edge"),
    "balanced": ("marshal", ["grunt", "spear", "shield", "archer", "sweeper", "cannon"],
                 "warcry", "colossus"),
    "greed":    ("bulwark", ["grunt", "shield", "archer", "cannon", "mortar", "titan"],
                 "bulwark", "archmage"),
}


def build(game, name: str, seed: str, side: str) -> Loadout:
    """選んだ6種に、抽選の2種を足して8枠にする。"""
    avatar, chosen, brought, trump = PRESETS[name]
    template = pick_template(game, seed)
    owned = list(game.units)
    drawn = draw_random_slots(game, seed, side, owned, tuple(chosen), template)
    return Loadout(avatar=avatar, roster=tuple(chosen) + tuple(drawn),
                   brought=brought, trump=trump,
                   stock_seed=f"{seed}:{side}")
