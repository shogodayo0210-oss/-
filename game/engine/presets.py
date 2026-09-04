"""見本の編成。

編成フェーズ（設計書3章）はまだ人が操作する形になっていないので、
ここで決め打ちにしてある。CLI も試遊版も同じものを使う。
"""

from __future__ import annotations

from .battle import Loadout
from .draft import draw_random_slots, pick_template

PRESETS = {
    "rush":     ("scout",   ["grunt", "spear", "twin", "archer", "shield", "sweeper"],
                 ["advance", "warcry", "mire"], "gale_edge"),
    "balanced": ("marshal", ["grunt", "spear", "shield", "archer", "sweeper", "cannon"],
                 ["warcry", "rust", "levy"], "colossus"),
    "greed":    ("bulwark", ["grunt", "shield", "archer", "cannon", "mortar", "titan"],
                 ["bulwark", "rally", "blight"], "archmage"),
}


def build(game, name: str, seed: str, side: str) -> Loadout:
    """選んだ6種に、抽選の2種を足して8枠にする。"""
    avatar, chosen, deck, trump = PRESETS[name]
    template = pick_template(game, seed)
    owned = list(game.units)
    drawn = draw_random_slots(game, seed, side, owned, tuple(chosen), template)
    return Loadout(avatar=avatar, roster=tuple(chosen) + tuple(drawn),
                   deck=tuple(deck), trump=trump)
