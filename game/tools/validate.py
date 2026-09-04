#!/usr/bin/env python3
"""`data/*.json` が設計上の約束を守っているかを検査する。

数字を動かして約束を割ったら、ここで落ちる。特典・ユニット・カードを
足したら必ず通す。依存なし。

    python3 game/tools/validate.py
"""

from __future__ import annotations

import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from game.engine.data import GameData, Unit, load  # noqa: E402

FAR = 50          # ここを超えたら遠距離扱い
CD_PER_COST = 25  # 再出撃CDの目安：コスト ÷ これ


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def check(self, ok: bool, message: str) -> bool:
        if not ok:
            self.errors.append(message)
        return ok


# --------------------------------------------------------------- アバター特典
def check_avatars(game: GameData, report: Report) -> list[tuple]:
    budget = game.budget
    rows = []

    for avatar in game.avatars.values():
        refs = avatar.perks
        report.check(len(refs) == len(set(refs)),
                     f"{avatar.id}: 同じ特典を二重に持っている")

        unknown = [r for r in refs if r not in game.perks]
        for ref in unknown:
            report.errors.append(f"{avatar.id}: 未定義の特典 {ref}")
        if unknown:
            continue

        held = [game.perks[r] for r in refs]

        # 看板はこれ1つで覚えてもらう特典。数字が変わるだけのものだと
        # 「アバターによって変わる」が伝わらないので、手順が変わるものに限る。
        if report.check(avatar.signature in refs,
                        f"{avatar.id}: signature {avatar.signature} を持っていない"):
            sig = game.perks[avatar.signature]
            report.check(sig.changes_flow,
                         f"{avatar.id}: 看板の {sig.name} は数字が変わるだけの特典。"
                         "手順が変わるもの（changes_flow）を看板にする")

        # 同居を禁じた組み合わせ（索敵で見てから枠を埋める＝カウンターピック）
        for perk in held:
            for other in sorted(set(perk.exclusive_with) & set(refs)):
                report.errors.append(
                    f"{avatar.id}: {perk.name} と {game.perks[other].name} は"
                    "同時に持てない")

        total = sum(p.cost for p in held)
        report.check(budget["min_total"] <= total <= budget["max_total"],
                     f"{avatar.id}: 合計 {total}pt が予算 "
                     f"{budget['min_total']}〜{budget['max_total']}pt の外")

        counts: dict[str, int] = {}
        for perk in held:
            counts[perk.category] = counts.get(perk.category, 0) + 1
        for category, count in sorted(counts.items()):
            cap = budget["category_caps"].get(category)
            if cap is None:
                report.errors.append(f"{avatar.id}: 未知のカテゴリ {category}")
            else:
                report.check(count <= cap,
                             f"{avatar.id}: {category} が {count} 個（上限 {cap}）")

        others = [p.name for p in held if p.id != avatar.signature]
        rows.append((avatar.name, total, game.perks[avatar.signature].name, others))

    return rows


# --------------------------------------------------------------------- カード
def check_cards(game: GameData, report: Report) -> None:
    """カードは資金ではなく時間で回す。効いている時間の割合で釣り合いを見る。"""
    rules = game.card_rules
    gcd = rules["global_cooldown_sec"]
    lo, hi = rules["uptime_range"]
    pool = list(game.cards.values())

    report.check(len(pool) >= rules["deck_size"],
                 f"cards: プールが {len(pool)} 枚。"
                 f"デッキ {rules['deck_size']} 枚を組めない")
    names = [c.name for c in pool]
    report.check(len(names) == len(set(names)),
                 "cards: カード名が重複（同名不可ルールと衝突）")

    for card in pool:
        report.check(card.duration_sec < card.cooldown_sec,
                     f"{card.name}: 継続 {card.duration_sec}秒 がクールタイム "
                     f"{card.cooldown_sec}秒 以上。常時かかったままになる")
        report.check(card.cooldown_sec >= gcd,
                     f"{card.name}: 個別クールタイム {card.cooldown_sec}秒 が"
                     f"共通クールタイム {gcd}秒 より短く、意味がない")
        report.check(lo <= card.uptime <= hi,
                     f"{card.name}: 占有率 {card.uptime:.0%}"
                     f"（継続{card.duration_sec}秒 / CT{card.cooldown_sec}秒）が"
                     f"{lo:.0%}〜{hi:.0%} の外")

    top = sorted(pool, key=lambda c: c.uptime, reverse=True)[: rules["deck_size"]]
    total = sum(c.uptime for c in top)
    report.check(total <= rules["max_deck_uptime"],
                 f"cards: 最も濃いデッキ（{'・'.join(c.name for c in top)}）の"
                 f"占有率合計が {total:.0%} で、上限 "
                 f"{rules['max_deck_uptime']:.0%} を超える")

    # 読心が公開するのは系統だけ。偏っていると情報の価値が消える。
    families = {c.family for c in pool}
    report.check(len(families) >= 3,
                 f"cards: 系統が {len(families)} 種類しかない。"
                 "読心で見えても意味が薄い")
    for side, label in (("own", "補助"), ("enemy", "妨害")):
        n = sum(1 for c in pool if c.target == side)
        report.check(n >= 2, f"cards: {label} が {n} 枚しかない")

    # 効果は必ずユニットが持っている項目か、資金まわりの項目を触る。
    # カード専用の仕組みを作らない、という方針を機械で守る。
    known = {"attack", "speed", "attack_interval", "knockback",
             "cost", "deploy_cooldown", "income"}
    for card in pool:
        report.check(card.apply.stat in known,
                     f"{card.name}: 未知の対象 {card.apply.stat}")
        report.check((card.apply.mult is None) != (card.apply.add is None),
                     f"{card.name}: mult と add はどちらか一方だけ")


# ------------------------------------------------------------------- ユニット
def _windup_rule(spec: Unit, game: GameData, report: Report) -> None:
    rules = game.readability
    report.check(spec.attack_windup_sec < spec.attack_interval_sec,
                 f"{spec.name}: 攻撃発生 {spec.attack_windup_sec}秒 が"
                 f"攻撃間隔 {spec.attack_interval_sec}秒 以上")
    if spec.attack > rules["big_hit_threshold"]:
        report.check(spec.attack_windup_sec >= rules["min_charge_windup_sec"],
                     f"{spec.name}: 1発 {spec.attack} の大きい一撃なのに発生 "
                     f"{spec.attack_windup_sec}秒。"
                     f"{rules['min_charge_windup_sec']}秒 以上にして、"
                     "見てから動けるようにする")


def check_characters(game: GameData, report: Report) -> None:
    units = list(game.units.values())
    roster = game.match["roster"]
    lo, hi = roster["unit_cost_range"]
    cd_lo, cd_hi = roster["unit_cooldown_range_sec"]
    s_lo, s_hi = roster["siege_mult_range"]

    hp_median = statistics.median(u.hp for u in units)
    dps_median = statistics.median(u.dps for u in units)
    speed_median = statistics.median(u.speed_mps for u in units)

    for unit in units:
        report.check(lo <= unit.cost <= hi,
                     f"{unit.name}: コスト {unit.cost} が {lo}〜{hi} の外")
        report.check(cd_lo <= unit.cooldown_sec <= cd_hi,
                     f"{unit.name}: 再出撃CD {unit.cooldown_sec}秒 が "
                     f"{cd_lo}〜{cd_hi}秒 の外")
        expected = unit.cost / CD_PER_COST
        report.check(0.4 <= unit.cooldown_sec / expected <= 1.6,
                     f"{unit.name}: 再出撃CD {unit.cooldown_sec}秒 がコスト "
                     f"{unit.cost} に対して外れすぎ（目安 {expected:.0f}秒）")
        report.check(s_lo <= unit.siege_mult <= s_hi,
                     f"{unit.name}: 対拠点倍率 {unit.siege_mult} が "
                     f"{s_lo}〜{s_hi} の外")
        _windup_rule(unit, game, report)

        if not report.check(0 <= unit.near < unit.far,
                            f"{unit.name}: 攻撃範囲 "
                            f"[{unit.near}, {unit.far}] が帯になっていない"):
            continue

        # 死角は「相手の前線を飛び越えて後ろを叩く」ための兵器の条件。
        report.check(unit.near <= 0 or unit.pierce >= 2,
                     f"{unit.name}: 死角 {unit.near}m を持つのに貫通 {unit.pierce}。"
                     "後方範囲は範囲攻撃で成立させる")

        per_kb = unit.hp / unit.knockback
        report.check(per_kb >= roster["min_hp_per_knockback"],
                     f"{unit.name}: ノックバック{unit.knockback}回で1回あたり "
                     f"{per_kb:.0f} しか耐えられない"
                     f"（下限 {roster['min_hp_per_knockback']}）")

        if unit.far <= FAR:
            continue

        # 死角なし・硬い・手数も多い遠距離は、近づいても倒せず詰む。
        outs = (unit.near > 0 or unit.hp <= hp_median or unit.dps <= dps_median)
        report.check(outs,
                     f"{unit.name}: 射程 {unit.far}m で死角なし・体力も手数も上位"
                     f"（HP {unit.hp} > {hp_median:.0f}、"
                     f"DPS {unit.dps:.0f} > {dps_median:.0f}）。"
                     "死角・体力・手数のどれかを空ける")
        report.check(unit.speed_mps <= speed_median,
                     f"{unit.name}: 射程 {unit.far}m で速度 {unit.speed_mps} は"
                     f"中央値 {speed_median:.1f} 超え。遠距離は足を遅くする")

    # ティアはランダム枠の鏡像抽選の土台。コスト帯が重なると意味を失う。
    by_tier: dict[str, list[int]] = {}
    for unit in units:
        by_tier.setdefault(unit.tier, []).append(unit.cost)
    order = sorted(by_tier, key=lambda t: min(by_tier[t]))
    for lower, upper in zip(order, order[1:]):
        report.check(max(by_tier[lower]) < min(by_tier[upper]),
                     f"characters: ティア {lower} と {upper} のコスト帯が重なっている"
                     f"（{max(by_tier[lower])} ≥ {min(by_tier[upper])}）")

    needed = {t for tpl in game.match["random_slot_draw"]["mirrored_tier_templates"]
              for t in tpl}
    for tier in sorted(needed - set(by_tier)):
        report.errors.append(
            f"characters: 抽選テンプレートが参照するティア {tier} のユニットが無い")


# ----------------------------------------------------------------------- 資金
def money_at(game: GameData, seconds: float) -> float:
    """t秒時点で到達しうる所持額。

    「レベルiまで上げてそこで止めて貯める」筋を全部試して最大を取る。
    上げ続ける筋だけを見ると、上げた直後は所持金0なので実態より低く出る。
    """
    levels = game.levels
    upgrade_sec = game.economy["growth"].get("upgrade_sec", 0.0)
    best = 0.0
    money, t = float(game.economy["start"]), 0.0

    for level in levels:
        if t > seconds:
            break
        best = max(best, min(level["max"],
                             money + level["per_sec"] * (seconds - t)))
        if "upgrade_cost" not in level:
            break
        cost = level["upgrade_cost"]
        if money < cost:
            t += (cost - money) / level["per_sec"]
            money = cost
        money -= cost
        t += upgrade_sec
    return best


def unlock_table(game: GameData) -> list[tuple[int, int, list[str]]]:
    """どのレベルで誰が使えるようになるか。"""
    levels = game.levels
    rows = []
    for level in levels:
        newly = [u.name for u in game.units.values()
                 if u.cost <= level["max"]
                 and not any(u.cost <= lower["max"] for lower in levels
                             if lower["level"] < level["level"])]
        rows.append((level["level"], level["max"], newly))
    return rows


def check_economy(game: GameData, report: Report) -> None:
    levels = game.levels

    for lower, upper in zip(levels, levels[1:]):
        report.check(upper["max"] > lower["max"] and upper["per_sec"] > lower["per_sec"],
                     f"economy: レベル{upper['level']} が レベル{lower['level']} より"
                     "強くなっていない")
    for level in levels[:-1]:
        if not report.check("upgrade_cost" in level,
                            f"economy: レベル{level['level']} に upgrade_cost が無い"):
            continue
        report.check(level["upgrade_cost"] <= level["max"],
                     f"economy: レベル{level['level']} の強化費用 "
                     f"{level['upgrade_cost']} がそのレベルの上限 {level['max']} を"
                     "超えていて、永久に払えない")

    ceiling = levels[-1]["max"]
    priced = ([(u.name, u.cost) for u in game.units.values()]
              + [(t.name, t.cost) for t in game.trumps.values()])
    for name, cost in priced:
        report.check(cost <= ceiling,
                     f"{name}: コスト {cost} が最終レベルの上限 {ceiling} を"
                     "超えていて、永久に出せない")

    cheapest = min(u.cost for u in game.units.values())
    report.check(cheapest <= levels[0]["max"],
                 f"economy: 初期上限 {levels[0]['max']} では"
                 f"最安の {cheapest} すら出せない")

    # コストはそのユニットの個性なので、解禁が最終レベルだと個性が試合に出ない。
    for unit in game.units.values():
        unlock = next((lv["level"] for lv in levels if lv["max"] >= unit.cost), None)
        report.check(unlock != levels[-1]["level"],
                     f"{unit.name}: 解禁が最終レベル({unlock})だけ。"
                     "そこまで行く試合が少ないと、このユニットの個性は出てこない")


# --------------------------------------------------------------------- 切り札
def check_trumps(game: GameData, report: Report) -> None:
    """1試合1回しか出せないので、出せないまま終わる設定は事故。"""
    rules = game.trump_rules
    unlock = rules["unlock_at_sec"]
    reachable = money_at(game, unlock)
    reaction = game.readability["human_reaction_sec"]

    for trump in game.trumps.values():
        report.check(trump.cost <= reachable,
                     f"{trump.name}: 解禁の {unlock}秒 時点で貯まる "
                     f"{reachable:.0f} では出せない。解禁時刻かコストを見直す")
        report.check(trump.summon_sec >= reaction,
                     f"{trump.name}: 召喚 {trump.summon_sec}秒 は反応 "
                     f"{reaction}秒 より短く、対応できない")
        report.check(trump.lifespan_sec > 0,
                     f"{trump.name}: 寿命が設定されていない")
        _windup_rule(trump, game, report)


# --------------------------------------------------------------- 反応可能性
def check_readability(game: GameData, report: Report) -> None:
    """見切りのような「合わせる」特典が成立する条件。

    0.3秒の窓は、相手の予兆が見えて、反応が間に合って、窓が覆えて
    初めて機能する。他の特典（詠唱短縮）がこれを壊しやすいので検査する。
    """
    rules = game.readability
    reactive = [p for p in game.perks.values()
                if p.category == "combat_active"
                and p.params.get("startup_sec") == 0.0
                and "invuln_sec" in p.params]
    if not reactive:
        return

    mults = [p.params["cast_time_mult"] for p in game.perks.values()
             if "cast_time_mult" in p.params]
    fastest = min(mults, default=1.0)
    floor = rules["min_cast_sec"]
    eps = 1e-9

    for perk in reactive:
        window = perk.params["invuln_sec"]
        needed = rules["human_reaction_sec"] + window
        report.check(rules["min_charge_windup_sec"] + eps >= needed,
                     f"readability: 大きい一撃の予備動作 "
                     f"{rules['min_charge_windup_sec']}秒 では"
                     f"「{perk.name}」({window}秒) に合わせられない。"
                     f"反応 {rules['human_reaction_sec']}秒＋窓で "
                     f"{needed:.2f}秒 が要る")
        for card in game.cards.values():
            effective = max(card.cast_sec * fastest, floor)
            report.check(effective + eps >= window,
                         f"readability: {card.name} の詠唱が短縮後 "
                         f"{effective:.2f}秒 になり、「{perk.name}」({window}秒) で"
                         "覆えない。min_cast_sec の床を上げるか短縮率を緩める")


# ----------------------------------------------------------------------- 出力
def main() -> int:
    game = load()
    report = Report()

    rows = check_avatars(game, report)
    check_cards(game, report)
    check_characters(game, report)
    check_economy(game, report)
    check_trumps(game, report)
    check_readability(game, report)

    width = max((len(name) for name, _, _, _ in rows), default=0)
    sig_width = max((len(sig) for _, _, sig, _ in rows), default=0)
    for name, total, signature, others in rows:
        print(f"{name:<{width}}  {total:>2}pt  {signature:<{sig_width}}"
              f"  + {'/'.join(others) if others else '—'}")

    print()
    for level, ceiling, newly in unlock_table(game):
        if newly:
            print(f"Lv{level} 上限{ceiling:>5}  {'・'.join(newly)}")

    if report.errors:
        print()
        for error in report.errors:
            print(f"NG  {error}")
        return 1

    print(f"\nOK  アバター {len(rows)} / 特典 {len(game.perks)} / "
          f"カード {len(game.cards)} / ユニット {len(game.units)} / "
          f"切り札 {len(game.trumps)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
