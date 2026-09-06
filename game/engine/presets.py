"""見本の編成。

編成フェーズ（設計書3章）はまだ人が操作する形になっていないので、
ここで決め打ちにしてある。CLI も試遊版も同じものを使う。
"""

from __future__ import annotations

import json

from .battle import Loadout
from .data import DATA_DIR
from .draft import draw_random_slots, pick_template


def trial_roster(data_dir=DATA_DIR) -> dict:
    """試遊用の見本編成（工程表 塊A-2）。両者これを使う。

    41体を並べると何が効いたのか分からないので、役割が数字で割れる8体に
    絞ってある。**8体を下回らない** ―― それより少ないと相手の手が数えられて
    読み合いにならない（match.json の roster.min_types_per_match）。
    理由は `data/preset_roster.json` に1体ずつ書いてある。
    """
    with open(data_dir / "preset_roster.json", encoding="utf-8") as f:
        return json.load(f)["trial"]


# アバター / 出撃6種（残り2枠は抽選） / 持ち込む呪文1枚 / 切り札
PRESETS = {
    "rush":     ("scout",   ["grunt", "hound", "boar", "twin", "raider", "whirl"],
                 "advance", "gale_edge"),
    "balanced": ("marshal", ["grunt", "shieldman", "spear", "archer", "sweeper",
                             "cannon"],
                 "warcry", "colossus"),
    "greed":    ("bulwark", ["grunt", "shieldman", "archer", "arbalest", "mortar",
                             "titan"],
                 "bulwark", "archmage"),
}


def build(game, name: str, seed: str, side: str) -> Loadout:
    """選んだ6種に、抽選の2種を足して8枠にする（1試合8種類の下限）。"""
    avatar, chosen, brought, trump = PRESETS[name]
    template = pick_template(game, seed)
    owned = list(game.units)
    drawn = draw_random_slots(game, seed, side, owned, tuple(chosen), template)
    return Loadout(avatar=avatar, roster=tuple(chosen) + tuple(drawn),
                   brought=brought, trump=trump,
                   stock_seed=f"{seed}:{side}")
