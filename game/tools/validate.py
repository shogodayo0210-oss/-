#!/usr/bin/env python3
"""game/data/*.json の整合性を検査する。

設計上の約束事（予算・カテゴリ上限・参照整合・デッキ構築制限が意味を持つか）を
機械的に確認するためのもの。特典やカードを足したら必ず通す。

    python3 game/tools/validate.py
"""

import json
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"


def load(name):
    with open(DATA / f"{name}.json", encoding="utf-8") as f:
        return json.load(f)


def check_perks(perks, errors):
    seen = set()
    for perk in perks["perks"]:
        if perk["id"] in seen:
            errors.append(f"perks: id が重複 {perk['id']}")
        seen.add(perk["id"])
        if perk["category"] not in perks["budget"]["category_caps"]:
            errors.append(f"perks: 未知のカテゴリ {perk['category']} ({perk['id']})")
        if perk["cost"] < 1:
            errors.append(f"perks: cost が 1 未満 {perk['id']}")


def check_avatars(perks, avatars, errors):
    budget = perks["budget"]
    by_id = {p["id"]: p for p in perks["perks"]}
    rows = []

    for avatar in avatars["avatars"]:
        refs = avatar["perks"]
        if len(refs) != len(set(refs)):
            errors.append(f"{avatar['id']}: 同じ特典を二重に持っている")

        unknown = [r for r in refs if r not in by_id]
        for ref in unknown:
            errors.append(f"{avatar['id']}: 未定義の特典 {ref}")
        if unknown:
            continue

        held = [by_id[r] for r in refs]
        total = sum(p["cost"] for p in held)
        if not budget["min_total"] <= total <= budget["max_total"]:
            errors.append(
                f"{avatar['id']}: 合計 {total}pt が予算 "
                f"{budget['min_total']}〜{budget['max_total']}pt の外"
            )

        counts = {}
        for perk in held:
            counts[perk["category"]] = counts.get(perk["category"], 0) + 1
        for category, count in sorted(counts.items()):
            cap = budget["category_caps"][category]
            if count > cap:
                errors.append(
                    f"{avatar['id']}: {category} が {count} 個（上限 {cap}）"
                )

        rows.append((avatar["name"], total, "/".join(p["name"] for p in held)))

    return rows


def check_cards(cards, match, errors):
    pool = sorted(c["cost"] for c in cards["cards"])
    size = match["cards"]["deck_size"]
    limit = match["cards"]["max_deck_cost"]

    if len(pool) < size:
        errors.append(f"cards: プールが {len(pool)} 枚。デッキ {size} 枚を組めない")
        return

    if sum(pool[:size]) > limit:
        errors.append(
            f"cards: 最安 {size} 枚でも {sum(pool[:size])} で上限 {limit} を超える"
            "（合法なデッキが存在しない）"
        )
    if sum(pool[-size:]) <= limit:
        errors.append(
            f"cards: 最高 {size} 枚でも {sum(pool[-size:])} で上限 {limit} 以内"
            "（構築制限が何も縛っていない）"
        )

    names = [c["name"] for c in cards["cards"]]
    if len(names) != len(set(names)):
        errors.append("cards: カード名が重複（同名不可ルールと衝突）")


def check_readability(perks, cards, match, errors):
    """反応して防げるか。見切りのような「合わせる」特典が成立する条件を検査する。

    0.3秒の窓は、相手の予備動作が見えて、反応が間に合って、窓が当たりを
    覆えて初めて機能する。他の特典（詠唱短縮など）がこの条件を壊しやすいので、
    数字を動かしたら必ずここで落ちるようにしておく。
    """
    rules = match.get("readability")
    if not rules:
        return

    reactive = [
        p for p in perks["perks"]
        if p["category"] == "combat_active"
        and p["params"].get("startup_sec") == 0.0
        and "invuln_sec" in p["params"]
    ]
    if not reactive:
        return

    mults = [
        p["params"]["cast_time_mult"] for p in perks["perks"]
        if "cast_time_mult" in p["params"]
    ]
    fastest = min(mults, default=1.0)
    floor = rules["min_cast_sec"]
    eps = 1e-9

    for perk in reactive:
        window = perk["params"]["invuln_sec"]

        needed = rules["human_reaction_sec"] + window
        if rules["min_charge_windup_sec"] + eps < needed:
            errors.append(
                f"readability: ため攻撃の予備動作 {rules['min_charge_windup_sec']}秒 では"
                f"「{perk['name']}」({window}秒) に合わせられない。"
                f"反応 {rules['human_reaction_sec']}秒＋窓で {needed:.2f}秒 が要る"
            )

        for card in cards["cards"]:
            effective = max(card["cast_sec"] * fastest, floor)
            if effective + eps < window:
                errors.append(
                    f"readability: {card['name']} の詠唱が短縮後 {effective:.2f}秒 になり、"
                    f"「{perk['name']}」({window}秒) で覆えない。"
                    f"min_cast_sec の床を上げるか短縮率を緩める"
                )


def check_match(match, errors):
    fmt = match["format"]
    slots = fmt["chosen_slots"] + fmt["random_slots"]
    if slots != fmt["team_size"]:
        errors.append(
            f"match: {fmt['chosen_slots']}+{fmt['random_slots']} が "
            f"team_size {fmt['team_size']} と合わない"
        )
    if fmt["ko_to_win"] >= fmt["team_size"]:
        errors.append(
            f"match: ko_to_win {fmt['ko_to_win']} が編成数以上。"
            "全員出撃になり「出さない選択」が消える"
        )


def main():
    perks, avatars = load("perks"), load("avatars")
    cards, match = load("cards"), load("match")

    errors = []
    check_perks(perks, errors)
    rows = check_avatars(perks, avatars, errors)
    check_cards(cards, match, errors)
    check_readability(perks, cards, match, errors)
    check_match(match, errors)

    width = max((len(name) for name, _, _ in rows), default=0)
    for name, total, detail in rows:
        print(f"{name:<{width}}  {total:>2}pt  {detail}")

    if errors:
        print()
        for error in errors:
            print(f"NG  {error}")
        return 1

    print(f"\nOK  アバター {len(rows)} / 特典 {len(perks['perks'])} / "
          f"カード {len(cards['cards'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
