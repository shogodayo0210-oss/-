#!/usr/bin/env python3
"""game/data/*.json の整合性を検査する。

設計上の約束事（予算・カテゴリ上限・参照整合・デッキ構築制限が意味を持つか）を
機械的に確認するためのもの。特典やカードを足したら必ず通す。

    python3 game/tools/validate.py
"""

import json
import statistics
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

        # 看板の特典。これ1つで覚えてもらうので、必ず手持ちの中から1つ選ぶ。
        if avatar["signature"] not in refs:
            errors.append(
                f"{avatar['id']}: signature {avatar['signature']} を持っていない"
            )
        elif not by_id[avatar["signature"]]["changes_flow"]:
            errors.append(
                f"{avatar['id']}: 看板の {by_id[avatar['signature']]['name']} は"
                "数字が変わるだけの特典。手順が変わるもの（changes_flow）を看板にする"
            )

        # 同居を禁じた組み合わせ（例：索敵で見てから枠を埋める＝カウンターピック）
        for perk in (by_id[r] for r in refs):
            banned = set(perk.get("exclusive_with", [])) & set(refs)
            for other in sorted(banned):
                errors.append(
                    f"{avatar['id']}: {perk['name']} と {by_id[other]['name']} は"
                    "同時に持てない"
                )

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

        others = [p["name"] for p in held if p["id"] != avatar["signature"]]
        rows.append((avatar["name"], total, by_id[avatar["signature"]]["name"], others))

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
    roster = match["roster"]
    slots = roster["chosen_slots"] + roster["random_slots"]
    if slots != roster["slots"]:
        errors.append(
            f"match: {roster['chosen_slots']}+{roster['random_slots']} が "
            f"出撃枠 {roster['slots']} と合わない"
        )


def check_characters(chars, match, errors):
    """ユニットの数字。DPS は 攻撃力÷攻撃間隔 の導出値として毎回ここで計算する。"""
    units = chars["characters"]
    roster = match["roster"]
    rules = match["readability"]
    lo, hi = roster["unit_cost_range"]
    cd_lo, cd_hi = roster["unit_cooldown_range_sec"]

    seen = set()
    for unit in units:
        if unit["id"] in seen:
            errors.append(f"characters: id が重複 {unit['id']}")
        seen.add(unit["id"])
        if not lo <= unit["cost"] <= hi:
            errors.append(
                f"{unit['name']}: コスト {unit['cost']} が {lo}〜{hi} の外"
            )
        if not cd_lo <= unit["cooldown_sec"] <= cd_hi:
            errors.append(
                f"{unit['name']}: 再出撃CD {unit['cooldown_sec']}秒 が "
                f"{cd_lo}〜{cd_hi}秒 の外"
            )
        # 高コストほど連打できない、という関係が崩れていないか
        expected = unit["cost"] / 25
        if not 0.4 <= unit["cooldown_sec"] / expected <= 1.6:
            errors.append(
                f"{unit['name']}: 再出撃CD {unit['cooldown_sec']}秒 が"
                f"コスト {unit['cost']} に対して外れすぎ（目安 {expected:.0f}秒）"
            )

    dps = {u["id"]: u["attack"] / u["attack_interval_sec"] for u in units}
    hp_median = statistics.median(u["hp"] for u in units)
    dps_median = statistics.median(dps.values())
    speed_median = statistics.median(u["speed_mps"] for u in units)
    FAR = 50  # ここを超えたら遠距離扱い

    for unit in units:
        near, far = unit["attack_band_m"]
        if near < 0 or near >= far:
            errors.append(
                f"{unit['name']}: 攻撃範囲 [{near}, {far}] が帯になっていない"
            )
            continue

        # 死角を持つのは「相手の前線を飛び越えて後ろを叩く」ための兵器。
        # 単体攻撃だと役割が立たないうえ、近づかれた時の弱さだけが残る。
        if near > 0 and unit["pierce"] < 2:
            errors.append(
                f"{unit['name']}: 死角 {near}m を持つのに貫通 {unit['pierce']}。"
                "後方範囲は範囲攻撃で成立させる"
            )

        # 攻撃発生。振り始めが見えないと、見切りもカードも合わせられない。
        if unit["attack_windup_sec"] >= unit["attack_interval_sec"]:
            errors.append(
                f"{unit['name']}: 攻撃発生 {unit['attack_windup_sec']}秒 が"
                f"攻撃間隔 {unit['attack_interval_sec']}秒 以上"
            )
        if (unit["attack"] > rules["big_hit_threshold"]
                and unit["attack_windup_sec"] < rules["min_charge_windup_sec"]):
            errors.append(
                f"{unit['name']}: 1発 {unit['attack']} の大きい一撃なのに発生 "
                f"{unit['attack_windup_sec']}秒。{rules['min_charge_windup_sec']}秒 以上にして"
                "、見てから動けるようにする"
            )

        # ノックバック1回あたりの耐久。細かすぎると押されっぱなしで機能しない。
        per_kb = unit["hp"] / unit["knockback"]
        if per_kb < roster["min_hp_per_knockback"]:
            errors.append(
                f"{unit['name']}: ノックバック{unit['knockback']}回で1回あたり "
                f"{per_kb:.0f} しか耐えられない"
                f"（下限 {roster['min_hp_per_knockback']}）"
            )

        s_lo, s_hi = roster["siege_mult_range"]
        if not s_lo <= unit["siege_mult"] <= s_hi:
            errors.append(
                f"{unit['name']}: 対拠点倍率 {unit['siege_mult']} が {s_lo}〜{s_hi} の外"
            )

        if far <= FAR:
            continue

        # 遠距離の縛り。次のどれかは必ず空けること。
        #   死角がある / 体力が中央値以下 / 手数が中央値以下
        # 全部埋まると「近づいても倒せない遠距離」になって詰む。
        outs = []
        if near > 0:
            outs.append(f"死角{near}m")
        if unit["hp"] <= hp_median:
            outs.append("体力が中央値以下")
        if dps[unit["id"]] <= dps_median:
            outs.append("手数が中央値以下")
        if not outs:
            errors.append(
                f"{unit['name']}: 射程 {far}m で死角なし・体力も手数も上位"
                f"（HP {unit['hp']} > {hp_median:.0f}、"
                f"DPS {dps[unit['id']]:.0f} > {dps_median:.0f}）。"
                "死角・体力・手数のどれかを空ける"
            )

        # 速い遠距離は、安全な位置を保ったまま前線を押し上げてしまう。
        if unit["speed_mps"] > speed_median:
            errors.append(
                f"{unit['name']}: 射程 {far}m で速度 {unit['speed_mps']} は"
                f"中央値 {speed_median:.1f} 超え。遠距離は足を遅くする"
            )

    # ティアはランダム枠の鏡像抽選の土台。コスト帯が重なっていると意味を失う。
    by_tier = {}
    for unit in units:
        by_tier.setdefault(unit["tier"], []).append(unit["cost"])
    order = sorted(by_tier, key=lambda t: min(by_tier[t]))
    for lower, upper in zip(order, order[1:]):
        if max(by_tier[lower]) >= min(by_tier[upper]):
            errors.append(
                f"characters: ティア {lower} と {upper} のコスト帯が重なっている"
                f"（{max(by_tier[lower])} ≥ {min(by_tier[upper])}）"
            )

    # 抽選テンプレートが参照するティアに、実際にユニットがあるか
    needed = {t for tpl in match["random_slot_draw"]["mirrored_tier_templates"]
              for t in tpl}
    for tier in sorted(needed - set(by_tier)):
        errors.append(
            f"characters: 抽選テンプレートが参照するティア {tier} のユニットが無い"
        )

    return dps


def money_at(economy, seconds):
    """t秒時点で到達しうる所持額。

    「レベルiまで上げて、そこで止めて貯める」筋を全部試して最大を取る。
    上げ続ける筋だけを見ると、上げた直後は所持金0なので実態より低く出る。
    """
    levels = economy["growth"]["levels"]
    best = 0.0
    money, t = economy["start"], 0.0

    for i, level in enumerate(levels):
        if t > seconds:
            break
        # ここで止めた場合、残り時間ぶん貯められる
        best = max(best, min(level["max"],
                             money + level["per_sec"] * (seconds - t)))
        if "upgrade_cost" not in level:
            break
        cost = level["upgrade_cost"]
        if money < cost:
            t += (cost - money) / level["per_sec"]
            money = cost
        money -= cost

    return best


def check_economy(economy, chars, cards, trumps, errors):
    """資金の成長。上限が足りないと、そのユニットは永久に出せない。"""
    levels = economy["growth"]["levels"]

    for lower, upper in zip(levels, levels[1:]):
        if upper["max"] <= lower["max"] or upper["per_sec"] <= lower["per_sec"]:
            errors.append(
                f"economy: レベル{upper['level']} が レベル{lower['level']} より"
                "強くなっていない"
            )
    for level in levels[:-1]:
        if "upgrade_cost" not in level:
            errors.append(f"economy: レベル{level['level']} に upgrade_cost が無い")
        elif level["upgrade_cost"] > level["max"]:
            errors.append(
                f"economy: レベル{level['level']} の強化費用 {level['upgrade_cost']} が"
                f"そのレベルの上限 {level['max']} を超えていて、永久に払えない"
            )

    ceiling = levels[-1]["max"]
    priced = ([(u["name"], u["cost"]) for u in chars["characters"]]
              + [(c["name"], c["cost"]) for c in cards["cards"]]
              + [(t["name"], t["cost"]) for t in trumps["trumps"]])
    for name, cost in priced:
        if cost > ceiling:
            errors.append(
                f"{name}: コスト {cost} が最終レベルの上限 {ceiling} を超えていて、"
                "永久に出せない"
            )

    cheapest = min(u["cost"] for u in chars["characters"])
    if cheapest > levels[0]["max"]:
        errors.append(
            f"economy: 初期上限 {levels[0]['max']} では最安の {cheapest} すら出せない"
        )


def check_trumps(trumps, match, errors):
    """切り札。1試合1回しか出せないので、出せないまま終わる設定は事故。"""
    rules = match["trump"]
    economy = match["economy"]
    unlock = rules["unlock_at_sec"]
    reachable = money_at(economy, unlock)

    for trump in trumps["trumps"]:
        if trump["cost"] > reachable:
            errors.append(
                f"{trump['name']}: 解禁の {unlock}秒 時点で貯まる "
                f"{reachable:.0f} では出せない。解禁時刻かコストを見直す"
            )
        # 召喚演出は相手が見て対応するための時間。反応より短いと不意打ちになる。
        if trump["summon_sec"] < match["readability"]["human_reaction_sec"]:
            errors.append(
                f"{trump['name']}: 召喚 {trump['summon_sec']}秒 は反応 "
                f"{match['readability']['human_reaction_sec']}秒 より短く、対応できない"
            )
        if trump["lifespan_sec"] <= 0:
            errors.append(f"{trump['name']}: 寿命が設定されていない")


def main():
    perks, avatars = load("perks"), load("avatars")
    cards, match = load("cards"), load("match")
    chars, trumps = load("characters"), load("trumps")

    errors = []
    check_perks(perks, errors)
    rows = check_avatars(perks, avatars, errors)
    check_cards(cards, match, errors)
    check_readability(perks, cards, match, errors)
    check_match(match, errors)
    check_characters(chars, match, errors)
    check_economy(match["economy"], chars, cards, trumps, errors)
    check_trumps(trumps, match, errors)

    width = max((len(name) for name, _, _, _ in rows), default=0)
    sig_width = max((len(sig) for _, _, sig, _ in rows), default=0)
    for name, total, signature, others in rows:
        print(f"{name:<{width}}  {total:>2}pt  {signature:<{sig_width}}"
              f"  + {'/'.join(others) if others else '—'}")

    if errors:
        print()
        for error in errors:
            print(f"NG  {error}")
        return 1

    print(f"\nOK  アバター {len(rows)} / 特典 {len(perks['perks'])} / "
          f"カード {len(cards['cards'])} / ユニット {len(chars['characters'])} / "
          f"切り札 {len(trumps['trumps'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
