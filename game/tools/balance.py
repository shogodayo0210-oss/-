#!/usr/bin/env python3
"""試合そのものを測る。**「先に押し込んだ側がそのまま勝つ」を数字にする道具。**

`validate.py` は data が約束を守っているかを見るが、約束を全部守っていても
試合がつまらないことはある。ここは反対側 ―― 実際に何百試合か回して、
その形が出てしまっていないかを見る。

出るもの:

  先制→勝ちの一致率  序盤に押し込んだ側が、そのまま勝った割合。
                      **100%に近いほど悪い。** 押し返す手が無いということなので。
                      50%なら、序盤の優勢は勝敗を決めていない。
  逆転率              中盤に押されていた側が勝った割合。低すぎると詰み。
  決着率              時間切れではなく拠点撃破で終わった割合。0%だと
                      前線が固まって誰も攻め落とせていない。
  前線の到達           前線が相手陣のどこまで届いたか。レーンを長くした意味が
                      あるかは、ここが動いているかで分かる。

レーン長・場の上限・試合時間は上書きできる。data を書き換えずに
「レーンをもう100m伸ばしたらどうなるか」を測れるようにするため。

    python3 game/tools/balance.py
    python3 game/tools/balance.py --matches 8
    python3 game/tools/balance.py --lane 240 --cap 24 --limit 270
"""

from __future__ import annotations

import argparse
import copy
import statistics
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from game.engine.battle import Battle                      # noqa: E402
from game.engine.data import GameData, load                # noqa: E402
from game.engine.draft import commit, match_seed           # noqa: E402
from game.engine.policy import POLICIES                    # noqa: E402
from game.engine.presets import PRESETS, build             # noqa: E402

# 序盤・中盤をどこで測るか。試合時間に対する割合で持つので、
# 試合の長さを変えても同じ意味の点を見る。
EARLY, MID = 0.20, 0.50


def tweak(game: GameData, lane=None, cap=None, limit=None) -> GameData:
    """data を書き換えずに、場の寸法だけ差し替えた盤面を作る。"""
    if lane is None and cap is None and limit is None:
        return game
    match = copy.deepcopy(game.match)
    if lane is not None:
        match["field"]["length_m"] = lane
    if cap is not None:
        match["field"]["max_units_per_side"] = cap
    if limit is not None:
        match["victory"]["time_limit_sec"] = limit
    return replace(game, match=match)


class Sample:
    """1試合ぶんの観測。"""

    def __init__(self, battle: Battle):
        self.limit = battle.game.time_limit
        self.lane = battle.game.lane_length
        self.leader_at: dict[float, int | None] = {}
        self.deepest = [0.0, 0.0]
        # 自拠点の傷で解禁される札が、実際に使える状態が何秒あったか。
        # 一番浅い閾値で測る ―― そこを割った瞬間から手が増える。
        gates = [card.base_hp_gate for card in battle.game.cards.values()
                 if card.gated]
        self.gate = max(gates) if gates else 0.0
        self.hurt = [0.0, 0.0]

    def watch(self, battle: Battle) -> None:
        for mark in (EARLY, MID):
            if mark not in self.leader_at and battle.t >= self.limit * mark:
                lead = battle.leader()
                self.leader_at[mark] = None if lead is None else lead.index
        for i, side in enumerate(battle.sides):
            self.deepest[i] = max(self.deepest[i], battle.advance_of(side))
            if side.base_hp <= battle.game.base_hp * self.gate:
                self.hurt[i] += battle.tick


def one(game: GameData, a: str, b: str, match_id: str):
    seed = match_seed(
        commit(tuple(PRESETS[a][1]), (PRESETS[a][2],), PRESETS[a][3],
               f"{match_id}:a"),
        commit(tuple(PRESETS[b][1]), (PRESETS[b][2],), PRESETS[b][3],
               f"{match_id}:b"),
        match_id)
    battle = Battle(game, build(game, a, seed, "a"), build(game, b, seed, "b"),
                    POLICIES[a], POLICIES[b])
    sample = Sample(battle)
    while not battle.finished():
        battle.step()
        sample.watch(battle)
    from game.engine.battle import Result
    return Result.of(battle), sample


def agreement(rows, mark: float) -> tuple[int, int]:
    """その時点で押し込んでいた側が、そのまま勝った回数 / 勝敗が付いた回数。"""
    hit = total = 0
    for result, sample in rows:
        lead = sample.leader_at.get(mark)
        if lead is None or result.winner is None:
            continue
        total += 1
        hit += (lead == result.winner)
    return hit, total


def report(game: GameData, rows) -> int:
    n = len(rows)
    full = game.base_hp
    lane = game.lane_length

    early_hit, early_n = agreement(rows, EARLY)
    mid_hit, mid_n = agreement(rows, MID)
    decisive = sum(1 for r, _ in rows if min(r.base_hp) <= 0)
    draws = sum(1 for r, _ in rows if r.winner is None)
    dealt = [1 - min(r.base_hp) / full for r, _ in rows]
    reach = [max(s.deepest) / lane for _, s in rows]
    seconds = [r.seconds for r, _ in rows]

    def pct(hit, total):
        return f"{hit / total:.0%}（{hit}/{total}）" if total else "—（勝敗なし）"

    print(f"\n{n}試合  レーン{lane:.0f}m  上限{game.match['field']['max_units_per_side']}体"
          f"  {game.time_limit:.0f}秒")
    print("─" * 62)
    print(f"  先制→勝ちの一致率（{EARLY:.0%}時点）  {pct(early_hit, early_n)}")
    print(f"  中盤→勝ちの一致率（{MID:.0%}時点）  {pct(mid_hit, mid_n)}")
    if mid_n:
        print(f"  逆転率（中盤に押されていた側の勝ち）  "
              f"{(mid_n - mid_hit) / mid_n:.0%}")
    print(f"  決着率（拠点撃破）                 {decisive / n:.0%}")
    print(f"  引き分け                          {draws / n:.0%}")
    print(f"  与ダメージ（多い側の平均）           {statistics.mean(dealt):.0%}")
    print(f"  前線の到達（レーンの何%まで）        "
          f"{statistics.mean(reach):.0%}（最大 {max(reach):.0%}）")
    print(f"  平均の長さ                        {statistics.mean(seconds):.0f}秒")

    # 押し返す手が「届いているか」。拠点が傷ついた状態で過ごした時間と、
    # そこで解禁される札が実際に撃たれた回数を並べて見る。
    gate = rows[0][1].gate if rows else 0.0
    hurt = [max(s.hurt) for _, s in rows]
    names = {card.name for card in game.cards.values() if card.gated}
    casts = sum(1 for r, _ in rows for _, _, text in r.events
                if any(name in text for name in names))
    cap = game.combat["siege_cap_dps"]
    print(f"  攻城にかかる秒数（設計値）           {full / cap:.0f}秒"
          f"（拠点 {full} ÷ 攻城口 {cap}）")
    print(f"  拠点が傷んでいた時間（{gate:.0%}以下）    "
          f"中央 {statistics.median(hurt):.0f}秒 / 最大 {max(hurt):.0f}秒")
    print(f"  解禁される札を撃った回数            {casts}回")

    # ここが設計上の赤信号。数字を動かすたびに見る場所。
    problems = []
    if early_n and early_hit / early_n >= 0.9:
        problems.append(
            "先に押し込んだ側がほぼ必ず勝っている。押し返す手が足りない ―― "
            "拠点の傷で解禁される札、遠方範囲の死角、増援の歩く距離のどれかを見る")
    if decisive / n <= 0.05:
        problems.append(
            "拠点撃破がほとんど無い。前線が固まって誰も攻め落とせていない ―― "
            "レーンが増援の足に対して長すぎるか、場の上限が低すぎる")
    if statistics.mean(reach) < 0.55:
        problems.append(
            "前線が相手陣まで届いていない。レーンを伸ばした意味が出ていない")
    if draws / n >= 0.7:
        problems.append("引き分けが多すぎる。決着の手段が足りない")
    if mid_n >= 8 and mid_hit == mid_n:
        problems.append(
            "中盤に押されていた側が一度も勝っていない。前半で決まりきっている ―― "
            "拠点の傷で解禁される札が届いていないか、効果が小さすぎる")
    if names and casts == 0:
        problems.append(
            "自拠点の傷で解禁される札が一度も撃たれていない。**傷ついた拠点という"
            "状態が存在していない疑い** ―― 攻城口の上限（combat.siege_cap_dps）に"
            "対して拠点HPが薄すぎると、拠点は『無傷』か『0』しか取らなくなる")

    for line in problems:
        print(f"\nNG  {line}")
    return 1 if problems else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="balance")
    parser.add_argument("--matches", type=int, default=4,
                        help="方針の組み合わせ1つあたりの試合数")
    parser.add_argument("--lane", type=float, help="レーン長を上書きして測る")
    parser.add_argument("--cap", type=int, help="場の上限を上書きして測る")
    parser.add_argument("--limit", type=float, help="試合時間を上書きして測る")
    args = parser.parse_args(argv)

    game = tweak(load(), args.lane, args.cap, args.limit)
    names = sorted(PRESETS)
    rows = []
    for a in names:
        for b in names:
            for i in range(args.matches):
                rows.append(one(game, a, b, f"m{i}"))
    return report(game, rows)


if __name__ == "__main__":
    raise SystemExit(main())
