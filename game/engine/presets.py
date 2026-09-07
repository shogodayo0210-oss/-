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
#
# **3方針とも種族で固めてある。** 種族呪文（5.5）は編成にその種族が3体以上
# 無いと撃てないので、散らした編成では測れない ―― 「同じ種族で固めるか、
# 役割で散らすか」という択そのものを、方針の側にも入れておく。
# 前線起点の射抜き（2.1）も1体ずつ入れてある。安い1体で前線を止める形への
# 答えなので、盤面に居ないと引き分けの原因が測れない。
PRESETS = {
    # 動物5体。安く速く、獣性（速度×2.5）で一気に押し込む
    "rush":     ("scout",   ["ratling", "hound", "boar", "raider", "rider",
                             "berserk"],
                 "beastblood", "gale_edge"),
    # 王国軍5体＋弩兵の射抜き。鬨の陣（攻撃×1.7を11秒）で線を押す
    "balanced": ("marshal", ["grunt", "shieldman", "spear", "crossbow", "archer",
                             "paladin"],
                 "kingsroar", "colossus"),
    # 古代兵器5体＋攻城弩の射抜き。過負荷（攻撃間隔×0.3）で焼き切る
    "greed":    ("bulwark", ["stonewall", "golem", "arbalest", "mortar",
                             "ballista", "titan"],
                 "overclock", "archmage"),
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
