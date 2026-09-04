"""1試合を回して結果を出す。

    python3 -m game.engine --a rush --b greed
    python3 -m game.engine --repeat 50            # 相性を見る
    python3 -m game.engine --timeline             # 何が起きたか全部出す
"""

from __future__ import annotations

import argparse
import collections

from .battle import NOT_SIMULATED, Battle, Loadout
from .data import load
from .draft import commit, draw_random_slots, match_seed, pick_template
from .policy import POLICIES

# 見本ぶんしかユニットが無いので、編成はここで決め打ちにしてある。
PRESETS = {
    "rush":     ("scout",   ["grunt", "spear", "twin", "archer", "shield", "sweeper"],
                 ["advance", "warcry", "mire"], "gale_edge"),
    "balanced": ("marshal", ["grunt", "spear", "shield", "archer", "sweeper", "cannon"],
                 ["warcry", "rust", "levy"], "colossus"),
    "greed":    ("bulwark", ["grunt", "shield", "archer", "cannon", "mortar", "titan"],
                 ["bulwark", "rally", "blight"], "archmage"),
}


def build(game, name: str, seed: str, side: str) -> Loadout:
    avatar, chosen, deck, trump = PRESETS[name]
    template = pick_template(game, seed)
    owned = list(game.units)
    drawn = draw_random_slots(game, seed, side, owned, tuple(chosen), template)
    return Loadout(avatar=avatar, roster=tuple(chosen) + tuple(drawn),
                   deck=tuple(deck), trump=trump)


def one_match(game, a: str, b: str, match_id: str, verbose: bool = False):
    seed = match_seed(commit(tuple(PRESETS[a][1]), tuple(PRESETS[a][2]),
                             PRESETS[a][3], f"{match_id}:a"),
                      commit(tuple(PRESETS[b][1]), tuple(PRESETS[b][2]),
                             PRESETS[b][3], f"{match_id}:b"),
                      match_id)
    battle = Battle(game, build(game, a, seed, "a"), build(game, b, seed, "b"),
                    POLICIES[a], POLICIES[b], verbose=verbose)
    return battle, battle.run(), seed


def main() -> int:
    parser = argparse.ArgumentParser(prog="game.engine")
    parser.add_argument("--a", default="rush", choices=sorted(PRESETS))
    parser.add_argument("--b", default="greed", choices=sorted(PRESETS))
    parser.add_argument("--match-id", default="m1")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--timeline", action="store_true")
    parser.add_argument("--all", action="store_true",
                        help="全ての組み合わせを総当たりする")
    args = parser.parse_args()

    game = load()

    if args.all:
        names = sorted(PRESETS)
        width = max(len(n) for n in names)
        print(f"{'':<{width}}  " + "  ".join(f"{n:>8}" for n in names))
        draws = 0
        for a in names:
            cells = []
            for b in names:
                score = 0.0
                for i in range(args.repeat):
                    _, result, _ = one_match(game, a, b, f"m{i}")
                    if result.winner is None:
                        score += 0.5
                        draws += 1
                    elif result.winner == 0:
                        score += 1.0
                cells.append(f"{score / args.repeat:>7.0%} ")
            print(f"{a:<{width}}  " + "  ".join(cells))
        total = len(names) ** 2 * args.repeat
        print(f"\n（行が先手側。勝ち1・引き分け0.5で採点。"
              f"引き分け {draws / total:.0%}）")
        return 0

    if args.repeat > 1:
        tally = collections.Counter()
        lengths = []
        for i in range(args.repeat):
            _, result, _ = one_match(game, args.a, args.b, f"m{i}")
            tally[result.winner] += 1
            lengths.append(result.seconds)
        total = args.repeat
        print(f"{args.a} vs {args.b}  ({total}試合)")
        print(f"  {args.a:<10} {tally[0] / total:>6.0%}")
        print(f"  {args.b:<10} {tally[1] / total:>6.0%}")
        print(f"  {'引き分け':<10} {tally[None] / total:>6.0%}")
        print(f"  平均 {sum(lengths) / total:.0f}秒")
        return 0

    battle, result, seed = one_match(game, args.a, args.b, args.match_id,
                                     verbose=args.timeline)
    a, b = battle.sides
    names = (args.a, args.b)

    print(f"シード {seed[:16]}…")
    for side, name in zip(battle.sides, names):
        avatar = game.avatars[side.loadout.avatar]
        roster = "・".join(game.units[u].name for u in side.loadout.roster)
        print(f"\nP{side.index + 1} {name}  アバター={avatar.name}"
              f"（看板 {game.perks[avatar.signature].name}）")
        print(f"   出撃  {roster}")
        print(f"   カード {'・'.join(game.cards[c].name for c in side.loadout.deck)}")
        print(f"   切り札 {game.trumps[side.loadout.trump].name}")

    if not args.timeline and battle.events:
        print("\n主な出来事")
        for t, side, text in battle.events[:14]:
            print(f"  [{t:6.2f}] P{side + 1} {text}")
        if len(battle.events) > 14:
            print(f"  … 他 {len(battle.events) - 14} 件（--timeline で全部出る）")

    print(f"\n結果  {result.reason}  {result.seconds:.0f}秒")
    for i, (side, name) in enumerate(zip(battle.sides, names)):
        mark = "勝" if result.winner == i else ("分" if result.winner is None else "負")
        pct = result.base_hp[i] / game.base_hp
        print(f"  [{mark}] P{i + 1} {name:<9} 拠点 {result.base_hp[i]:>7.0f}"
              f" ({pct:>4.0%})  資金Lv{result.level[i]}")

    skipped = sorted(
        {p for side in battle.sides for p in side.perks} & NOT_SIMULATED)
    if skipped:
        print("\n未実装の特典（この試合では効いていない）: "
              + "・".join(game.perks[p].name for p in skipped))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
