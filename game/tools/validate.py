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
    """呪文は資金で撃つ。**コストの高さが、そのまま強さの帯になっている**か。

    無料だった頃は占有率（継続÷CT）が唯一の物差しだったが、資金を払うように
    なったので「効かせ続けるのに収入の何割を食うか」＝維持費が主役になる。
    """
    rules = game.card_rules
    gcd = rules["global_cooldown_sec"]
    pool = list(game.cards.values())
    bands = rules["cost_bands"]
    powers = rules["power_bands"]
    first = game.levels[0]
    income1 = first["income_amount"] / first["income_every_sec"]

    report.check(len(pool) >= rules["stock_slots"] + rules["brought"],
                 f"cards: プールが {len(pool)} 枚。"
                 f"持ち込み{rules['brought']}＋ストック{rules['stock_slots']} を賄えない")
    names = [c.name for c in pool]
    report.check(len(names) == len(set(names)), "cards: カード名が重複")

    for card in pool:
        report.check(card.duration_sec < card.cooldown_sec,
                     f"{card.name}: 継続 {card.duration_sec}秒 がクールタイム "
                     f"{card.cooldown_sec}秒 以上。持ち込むと常時かかったままになる")
        report.check(card.cooldown_sec >= gcd,
                     f"{card.name}: 個別CT {card.cooldown_sec}秒 が"
                     f"共通CT {gcd}秒 より短く、意味がない")
        report.check(card.uptime <= rules["max_uptime"],
                     f"{card.name}: 占有率 {card.uptime:.0%} が上限 "
                     f"{rules['max_uptime']:.0%} を超える")

        lo, hi = bands.get(card.band, (0, 0))
        report.check(lo <= card.cost <= hi,
                     f"{card.name}: コスト {card.cost} が「{card.band}」の帯 "
                     f"{lo}〜{hi} の外")
        plo, phi = powers.get(card.band, (0, 0))
        report.check(plo <= card.power < phi,
                     f"{card.name}: 効果の大きさ {card.power:.1f} が「{card.band}」の"
                     f"想定 {plo}〜{phi} の外。**コストと強さがずれている**")

    # 帯のあいだで、コストも維持費も重ならないこと。
    # 重ならないから「高い＝強い」が一目で成り立つ。
    order = ["軽", "中", "重"]
    for lower, upper in zip(order, order[1:]):
        low = [c for c in pool if c.band == lower]
        high = [c for c in pool if c.band == upper]
        if not (low and high):
            continue
        report.check(max(c.cost for c in low) < min(c.cost for c in high),
                     f"cards: 「{lower}」と「{upper}」のコスト帯が重なっている")
        report.check(max(c.upkeep for c in low) < min(c.upkeep for c in high),
                     f"cards: 「{lower}」と「{upper}」の維持費が重なっている")

    # 帯の中では「高い方が弱い」が起きないこと。
    # 同額どうしは比べない ―― 同じ値段で役割が違うのは正しい姿。
    for band in order:
        members = sorted((c for c in pool if c.band == band), key=lambda c: c.cost)
        for a, b in zip(members, members[1:]):
            if a.cost == b.cost:
                continue
            report.check(a.power <= b.power + 1e-9,
                         f"{b.name}（{b.cost}）は {a.name}（{a.cost}）より高いのに"
                         f"効果が小さい（{b.power:.1f} < {a.power:.1f}）")

    # 一番軽い帯は、育てる前でも維持できること。ここが払えないと
    # 「呪文はお金持ちの遊び」になって、序盤の択が消える。
    light = [c for c in pool if c.band == "軽"]
    if light:
        worst = max(light, key=lambda c: c.upkeep)
        report.check(worst.upkeep <= income1 * 0.4,
                     f"{worst.name}: 維持費 {worst.upkeep:.1f}/秒 が"
                     f"Lv1収入 {income1}/秒 の40%を超え、序盤に撃てない")

    # 一番重い帯は、一番軽い帯より桁違いに重いこと。
    # 収入に対する割合ではなく**軽の何倍**で縛る ―― コストの尺度を
    # 75〜2500 から 1〜10 に変えても、この規則は壊れない。
    heavy = [c for c in pool if c.band == "重"]
    if heavy and light:
        ratio_min = rules.get("upkeep_ratio_min", 3.0)
        cheapest_heavy = min(heavy, key=lambda c: c.upkeep)
        dearest_light = max(light, key=lambda c: c.upkeep)
        ratio = cheapest_heavy.upkeep / max(dearest_light.upkeep, 1e-9)
        report.check(ratio >= ratio_min,
                     f"cards: 一番安い重（{cheapest_heavy.name}）の維持費が"
                     f"一番高い軽（{dearest_light.name}）の {ratio:.1f}倍しかない。"
                     f"{ratio_min}倍以上ないと帯を分ける意味がない")
        for card in heavy:
            report.check(card.cast_sec >= rules["heavy_min_cast_sec"],
                         f"{card.name}: 重い呪文なのに詠唱 {card.cast_sec}秒。"
                         f"{rules['heavy_min_cast_sec']}秒以上でないと見切れない")

    # ストックは軽い札ほど出やすい。重い札しか流れてこないと引き損になる。
    weights = rules["stock_weight"]
    report.check(weights.get("軽", 0) > weights.get("重", 0),
                 "cards: ストックの重みが「軽 > 重」になっていない。"
                 "撃てない札ばかり並ぶ")

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
    w_lo, w_hi = roster["anti_wall_mult_range"]
    wall_line = roster["wall_threshold"]

    hp_median = statistics.median(u.hp for u in units)
    dps_median = statistics.median(u.dps for u in units)
    speed_median = statistics.median(u.speed_mps for u in units)

    for unit in units:
        report.check(lo <= unit.cost <= hi,
                     f"{unit.name}: コスト {unit.cost} が {lo}〜{hi} の外")
        report.check(cd_lo <= unit.cooldown_sec <= cd_hi,
                     f"{unit.name}: 再出撃CD {unit.cooldown_sec}秒 が "
                     f"{cd_lo}〜{cd_hi}秒 の外")
        band = game.match["roster"]["tier_cooldown_bands"].get(unit.tier)
        if band:
            report.check(band[0] <= unit.cooldown_sec <= band[1],
                         f"{unit.name}: 再出撃CD {unit.cooldown_sec}秒 が"
                         f"ティア{unit.tier}の帯 {band[0]}〜{band[1]}秒 の外")
        report.check(s_lo <= unit.siege_mult <= s_hi,
                     f"{unit.name}: 対拠点倍率 {unit.siege_mult} が "
                     f"{s_lo}〜{s_hi} の外")
        report.check(w_lo <= unit.anti_wall_mult <= w_hi,
                     f"{unit.name}: 対壁倍率 {unit.anti_wall_mult} が "
                     f"{w_lo}〜{w_hi} の外")

        # 壁の仕事は前線を作ることであって、殴ることではない。
        if unit.is_wall(wall_line):
            report.check(unit.dps <= dps_median,
                         f"{unit.name}: 壁（対拠点 {unit.siege_mult}）なのに "
                         f"DPS {unit.dps:.0f} が中央値 {dps_median:.0f} 超え。"
                         "壁の攻撃力は低くする")

        # 壁を割るのは、壁と同じ距離まで出てきた者の仕事。
        # 遠くから安全に壁を溶かせると、前に出る理由が無くなる。
        report.check(unit.anti_wall_mult <= 1.5 or unit.far <= FAR,
                     f"{unit.name}: 対壁倍率 {unit.anti_wall_mult} で射程 "
                     f"{unit.far}m。壁特攻は接近戦の役割に限る")
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

    # 壁と、その壁を崩す答えの両方が要る。片方だけだと、
    # 「安い壁を並べるだけで前線が保たれる」か「壁が意味を持たない」に倒れる。
    # 強いキャラほど再出撃までが長い ―― 比ではなく**順序**で縛る。
    # コスト帯が 75〜2500 と3桁ぶん広いので、ひとつの係数では表せない。
    by_cost = sorted(units, key=lambda u: (u.cost, u.cooldown_sec))
    for cheap, dear in zip(by_cost, by_cost[1:]):
        if cheap.cost == dear.cost:
            continue      # 同額どうしは比べない。同じ値段で役割が違うのは正しい
        report.check(cheap.cooldown_sec <= dear.cooldown_sec,
                     f"{dear.name}（{dear.cost}）は {cheap.name}（{cheap.cost}）より"
                     f"高いのに再出撃が早い（{dear.cooldown_sec}秒 < "
                     f"{cheap.cooldown_sec}秒）")

    # ── 上位互換は居てよい。ただし「同じ資金ぶん並べれば勝てる」こと ──
    # 全項目で上回るキャラが居るのは構わない。差別化は**コストの差**で付ける ――
    # 双剣1体ぶんの資金で兵卒は5体出せて、体力の合計では上回る。
    # 逆に「同じ資金を積んでも安い側が何ひとつ勝てない」なら、
    # その安いキャラは存在する意味を失う。
    higher = [("体力", lambda u: u.hp), ("DPS", lambda u: u.dps),
              ("射程", lambda u: u.far), ("速度", lambda u: u.speed_mps),
              ("対拠点", lambda u: u.siege_mult),
              ("対壁", lambda u: u.anti_wall_mult), ("貫通", lambda u: u.pierce)]
    lower = [("ノックバック", lambda u: u.knockback),
             ("攻撃発生", lambda u: u.attack_windup_sec),
             ("死角", lambda u: u.near)]

    def dominates(rich: Unit, poor: Unit) -> bool:
        return (all(f(rich) >= f(poor) for _, f in higher)
                and all(f(rich) <= f(poor) for _, f in lower))

    for poor in units:
        for rich in units:
            if poor.cost >= rich.cost or not dominates(rich, poor):
                continue
            n = rich.cost / poor.cost          # 同じ資金で買える数
            report.check(poor.hp * n > rich.hp or poor.dps * n > rich.dps,
                         f"{rich.name}（{rich.cost}）は {poor.name}（{poor.cost}）の"
                         f"全項目で上回る上に、同じ資金ぶん（{n:.0f}体）並べても"
                         f"体力もDPSも届かない（体力 {poor.hp * n:.0f} 対 {rich.hp} / "
                         f"DPS {poor.dps * n:.0f} 対 {rich.dps:.0f}）。"
                         "安い側が存在する意味を失う")

    # ── 守られる側が居ること ────────────────────────────────
    # 高コストの高火力・高射程が、安い壁より脆い。だから壁に仕事がある。
    toughest_cheap = max((u.hp for u in units if u.cost <= 2), default=0)
    fragile_rich = [u for u in units
                    if u.cost >= 7 and u.hp < toughest_cheap and u.far > FAR]
    report.check(bool(fragile_rich),
                 f"characters: 安い壁（体力{toughest_cheap}）より脆い高コストの"
                 "遠距離が1体も居ない。壁が守る相手が存在せず、前線を取る意味が薄れる")

    walls = [u for u in units if u.is_wall(wall_line)]
    breakers = [u for u in units if u.anti_wall_mult > 1.5]
    report.check(bool(walls), "characters: 壁（対拠点倍率が低いユニット）が居ない")
    report.check(bool(breakers),
                 "characters: 壁特攻を持つユニットが居ない。"
                 "安い壁を並べるだけで前線が保たれてしまう")

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

    def per_sec(level: dict) -> float:
        return level["income_amount"] / level["income_every_sec"]

    for level in levels:
        if t > seconds:
            break
        best = max(best, min(level["max"],
                             money + per_sec(level) * (seconds - t)))
        if "upgrade_cost" not in level:
            break
        cost = level["upgrade_cost"]
        if money < cost:
            t += (cost - money) / per_sec(level)
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


def check_field(game: GameData, report: Report) -> None:
    """場に置ける数は、レーンに物理的に入る数を超えられない。

    超えると入りきらないぶんが前線で詰まり、資金をいくら積んでも
    線が動かなくなる。実測で、上限30体（入るのは20体）のとき
    拠点への与ダメージが平均7%まで落ちていた。
    """
    lane = game.lane_length
    spacing = game.combat["unit_spacing_m"]
    cap = game.match["field"]["max_units_per_side"]
    fits = int(lane / spacing)
    report.check(cap <= fits,
                 f"field: 場の上限 {cap}体 に対し、レーン {lane:.0f}m ÷ 隊列間隔 "
                 f"{spacing}m では {fits}体しか並べない")


def check_milestones(game: GameData, report: Report) -> None:
    """時間の節目の配布。刻みで貯まるのとは別枠の、速度を上げる仕組み。"""
    drops = game.economy.get("milestones", [])
    if not drops:
        return
    limit = game.time_limit
    first_cap = game.levels[0]["max"]

    for a, b in zip(drops, drops[1:]):
        report.check(a["at_sec"] < b["at_sec"],
                     f"milestones: {a['at_sec']}秒 と {b['at_sec']}秒 の順序が逆")
    for drop in drops:
        report.check(0 < drop["at_sec"] < limit,
                     f"milestones: {drop['at_sec']}秒 は試合時間 {limit:.0f}秒 の外")
        report.check(drop.get("to", "both") in ("both", "leader"),
                     f"milestones: {drop['at_sec']}秒 の to が both / leader でない")
        report.check(drop["amount"] <= game.levels[-1]["max"],
                     f"milestones: {drop['at_sec']}秒 の +{drop['amount']} が"
                     f"最終の上限 {game.levels[-1]['max']} を超え、誰も受け取れない")

    # 最初の配布だけは、育てていなくても受け取りきれること。
    # 後半の配布が大きいのは意図的（そのころには上限が育っている）。
    report.check(drops[0]["amount"] <= first_cap,
                 f"milestones: 最初の配布 +{drops[0]['amount']} が Lv1の上限 "
                 f"{first_cap} を超える。開始直後は受け取りきれない")
    for a, b in zip(drops, drops[1:]):
        report.check(a["amount"] <= b["amount"],
                     f"milestones: {b['at_sec']}秒 の +{b['amount']} が "
                     f"{a['at_sec']}秒 の +{a['amount']} より小さい。"
                     "後になるほど大きい、が崩れている")

    # 押し込んでいる側にだけ入る配布が、序盤に少なくとも1回あること。
    # これが無いと「何も出さずに財布だけ育てる」が常に正解になる。
    early = [d for d in drops
             if d.get("to") == "leader" and d["at_sec"] <= limit * 0.25]
    report.check(bool(early),
                 "milestones: 試合の序盤に陣地ボーナス（to=leader）が無い。"
                 "安いユニットを早く出す理由が生まれない")


def check_economy(game: GameData, report: Report) -> None:
    levels = game.levels

    def per_sec(level: dict) -> float:
        return level["income_amount"] / level["income_every_sec"]

    for lower, upper in zip(levels, levels[1:]):
        report.check(upper["max"] > lower["max"],
                     f"economy: レベル{upper['level']} の上限が上がっていない")
        report.check(per_sec(upper) > per_sec(lower),
                     f"economy: レベル{upper['level']} の貯まる速さが上がっていない")
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
    reaction = game.readability["human_reaction_sec"]
    # 解禁した瞬間に払える必要はない。貯めること自体が択なので。
    # ただし**使う時間が残っているうち**には届かないと、置物になる。
    deadline = game.time_limit * rules["affordable_by_fraction"]
    reachable = money_at(game, deadline)

    for trump in game.trumps.values():
        report.check(trump.cost <= reachable,
                     f"{trump.name}: 残り時間が意味を持つ {deadline:.0f}秒 までに"
                     f"貯まるのは {reachable:.0f} で、コスト {trump.cost} に届かない")
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
    check_field(game, report)
    check_milestones(game, report)
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
