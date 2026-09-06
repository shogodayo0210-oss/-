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

from game.engine.data import (COST_MINUS_IF_LAST_SAME_RACE,  # noqa: E402
                              COST_MINUS_PER_SAME_RACE_IN_ROSTER,
                              COST_MULT_WHEN_HURT, TRAIT_KINDS,
                              GameData, Unit, load)
from game.engine.presets import trial_roster  # noqa: E402

# 「ここを超えたら遠距離」は data 側（roster.far_threshold_m）にある。
# 検査だけが知っている数字にすると、キャラを作る側から見えない。


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
    bonus = game.gate_power_bonus
    first = game.levels[0]
    income1 = first["income_amount"] / first["income_every_sec"]

    # 条件付きの札は、撃てないまま終わる試合があるぶんだけ強くてよい。
    # その差（gate_power_bonus）を引いた値で帯を見るので、
    # 「条件付きだけが同じ値段で強い」が、際限なくならずに成立する。
    def rated(card) -> float:
        return card.rated_power(bonus)

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
        report.check(plo <= rated(card) < phi,
                     f"{card.name}: 効果の大きさ {rated(card):.1f}"
                     f"{'（条件付きぶんを引いた値）' if card.gated else ''} が"
                     f"「{card.band}」の想定 {plo}〜{phi} の外。"
                     "**コストと強さがずれている**")

        if card.gated:
            report.check(0.0 < card.base_hp_gate < 1.0,
                         f"{card.name}: 解禁の閾値 {card.base_hp_gate} が 0〜1 の外")
            report.check(card.target == "own",
                         f"{card.name}: 拠点の傷で解禁される札は自軍にかけるものに限る。"
                         "妨害だと『押している側が押し返される』ではなく"
                         "『押している側が一方的に殴られる』になる")

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
    # 並べ替えは (コスト, 大きさ) で決める。コストだけで並べると、同額の中の
    # どれが境目に来るかが JSON に書いた順に左右されて、検査が気まぐれになる。
    for band in order:
        members = sorted((c for c in pool if c.band == band),
                         key=lambda c: (c.cost, rated(c)))
        for a, b in zip(members, members[1:]):
            if a.cost == b.cost:
                continue
            report.check(rated(a) <= rated(b) + 1e-9,
                         f"{b.name}（{b.cost}）は {a.name}（{a.cost}）より高いのに"
                         f"効果が小さい（{rated(b):.1f} < {rated(a):.1f}）")

    # 押し込まれている側だけが持てる札が、実在すること。
    # これが無いと、先に前線を上げた側がそのまま勝ち切る形に戻る。
    gated = [c for c in pool if c.gated]
    report.check(bool(gated),
                 "cards: 拠点の傷で解禁される札が1枚も無い。"
                 "押し込まれている側に、押している側が持てない手が要る")

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


def check_reach(spec: Unit, game: GameData, report: Report) -> None:
    """射程まわりの規則。ユニットにも切り札にも同じものを掛ける。

    切り札だけ例外にすると、そこだけ答えの無い札ができる。
    """
    roster = game.roster_rules
    far_line = game.far_threshold
    area = game.area_pierce_min
    ratio = roster["blind_spot_ratio_min"]

    report.check(spec.far <= game.max_reach,
                 f"{spec.name}: 射程 {spec.far}m が上限 {game.max_reach}m を超える")

    if not report.check(0 <= spec.near < spec.far,
                        f"{spec.name}: 攻撃範囲 "
                        f"[{spec.near}, {spec.far}] が帯になっていない"):
        return

    # 死角は「相手の前線を飛び越えて後ろを叩く」ための兵器の条件。
    report.check(spec.near <= 0 or spec.pierce >= area,
                 f"{spec.name}: 死角 {spec.near}m を持つのに貫通 {spec.pierce}。"
                 "後方範囲は範囲攻撃で成立させる")

    # ── **遠距離の範囲攻撃は、必ず遠方範囲（死角持ち）** ──────────
    # 遠くまで届く範囲攻撃が足元まで拾えると、前に出ても後ろに回っても
    # 倒せない。死角があれば、安い1体を懐に送るだけで黙らせられる。
    if spec.is_rear_area(far_line, area):
        report.check(spec.near > 0,
                     f"{spec.name}: 射程 {spec.far}m（遠距離）で貫通 {spec.pierce}"
                     "（範囲）なのに死角が無い。"
                     "**遠距離の範囲攻撃は遠方範囲にする** ―― "
                     "懐に入れば黙る、が唯一の答えになる")
        report.check(spec.near >= spec.far * ratio - 1e-9,
                     f"{spec.name}: 死角 {spec.near}m が射程 {spec.far}m の "
                     f"{ratio:.0%} に届かない（{spec.far * ratio:.0f}m 必要）。"
                     "浅すぎる死角は、懐に入る側が入る前に撃たれて終わる")


def check_characters(game: GameData, report: Report) -> None:
    units = list(game.units.values())
    roster = game.roster_rules
    lo, hi = roster["unit_cost_range"]
    cd_lo, cd_hi = roster["unit_cooldown_range_sec"]
    sp_lo, sp_hi = roster["speed_range_mps"]
    s_lo, s_hi = roster["siege_mult_range"]
    w_lo, w_hi = roster["anti_wall_mult_range"]
    wall_line = roster["wall_threshold"]
    far_line = game.far_threshold

    hp_median = statistics.median(u.hp for u in units)
    dps_median = statistics.median(u.dps for u in units)
    speed_median = statistics.median(u.speed_mps for u in units)

    report.check(len(units) >= game.min_types_per_match,
                 f"characters: ユニットが {len(units)} 体しか居ない。"
                 f"1試合で {game.min_types_per_match} 種類を出すには足りない")

    for unit in units:
        report.check(sp_lo <= unit.speed_mps <= sp_hi,
                     f"{unit.name}: 速度 {unit.speed_mps} が "
                     f"{sp_lo}〜{sp_hi} の外")
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
        report.check(unit.anti_wall_mult <= 1.5 or unit.far <= far_line,
                     f"{unit.name}: 対壁倍率 {unit.anti_wall_mult} で射程 "
                     f"{unit.far}m。壁特攻は接近戦の役割に限る")
        _windup_rule(unit, game, report)
        check_reach(unit, game, report)

        per_kb = unit.hp / unit.knockback
        report.check(per_kb >= roster["min_hp_per_knockback"],
                     f"{unit.name}: ノックバック{unit.knockback}回で1回あたり "
                     f"{per_kb:.0f} しか耐えられない"
                     f"（下限 {roster['min_hp_per_knockback']}）")

        if not unit.is_ranged(far_line):
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

    # 強いキャラほど再出撃までが長い ―― 比ではなく**順序**で縛る。
    # コストが1〜15と15倍ぶん広いので、ひとつの係数では表せない。
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
    rich_line = statistics.median(u.cost for u in units)
    toughest_cheap = max((u.hp for u in units if u.cost <= 2), default=0)
    fragile_rich = [u for u in units
                    if u.cost >= rich_line and u.hp < toughest_cheap
                    and u.is_ranged(far_line)]
    report.check(bool(fragile_rich),
                 f"characters: 安い壁（体力{toughest_cheap}）より脆い高コストの"
                 "遠距離が1体も居ない。壁が守る相手が存在せず、前線を取る意味が薄れる")

    # 壁と、その壁を崩す答えの両方が要る。片方だけだと、
    # 「安い壁を並べるだけで前線が保たれる」か「壁が意味を持たない」に倒れる。
    walls = [u for u in units if u.is_wall(wall_line)]
    breakers = [u for u in units if u.anti_wall_mult > 1.5]
    report.check(bool(walls), "characters: 壁（対拠点倍率が低いユニット）が居ない")
    report.check(bool(breakers),
                 "characters: 壁特攻を持つユニットが居ない。"
                 "安い壁を並べるだけで前線が保たれてしまう")

    # ── 壁は1〜2、その2段で役割が割れていること ──────────────────
    # にゃんこ大戦争の「ねこ（1）／壁猫（2）」。1は殴りながら数で線を作り、
    # 2は殴らない代わりに硬い。同じ役を2段に分けないと、序盤の択が
    # 「壁を出すか出さないか」の1つしか無くなる。
    chip = [u for u in units if u.cost == 1]
    tank = [u for u in units if u.cost == 2 and u.is_wall(wall_line)]
    report.check(bool(chip), "characters: コスト1のユニットが居ない")
    if report.check(bool(tank),
                    "characters: コスト2の壁が居ない。"
                    "最安の削り役（1）と、殴らない硬い壁（2）の2段が要る"):
        hardest = max(tank, key=lambda u: u.hp)
        softest = max(chip, key=lambda u: u.hp)
        report.check(hardest.hp > softest.hp * 2,
                     f"{hardest.name}（2）は {softest.name}（1）の2倍も硬くない"
                     f"（{hardest.hp} 対 {softest.hp}）。"
                     "値段が倍なら、壁としての仕事も倍でないと2段にならない")
        report.check(hardest.dps < softest.dps,
                     f"{hardest.name}（2）は {softest.name}（1）より殴れてしまう。"
                     "壁猫は硬さを買う札で、火力を買う札ではない")

    # ── 速攻の答えが在ること ────────────────────────────────
    # 高コストの範囲攻撃は、放っておけば必ず最適解になる（安いユニットが
    # 何体来ても薙がれる）。**足だけで先に触れる**キャラが要る。
    quick = [u for u in units
             if u.speed_mps > speed_median and u.cost <= rich_line
             and u.dps > dps_median]
    report.check(bool(quick),
                 "characters: 中央値より速く・中央値より痛く・値段は中央値以下、"
                 "という速攻役が居ない。高コストの範囲攻撃を咎める手が無くなる")

    # 遠方範囲（死角を持つ遠距離の範囲攻撃）と、その死角に入れる足の両方。
    rear = game.rear_area_units()
    report.check(bool(rear),
                 "characters: 遠方範囲が1体も居ない。"
                 "前線の後ろを叩く手段が無いと、壁を並べるだけで拠点が守れる")
    if rear:
        deepest = max(rear, key=lambda u: u.near)
        divers = [u for u in units
                  if u.speed_mps > speed_median and u.far < deepest.near]
        report.check(bool(divers),
                     f"characters: {deepest.name} の死角 {deepest.near}m に"
                     "潜り込める足の速いユニットが居ない。"
                     "死角は、そこに入れる者が居て初めて弱点になる")

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
    """レーンの長さが、射程に対して十分あるか。

    **レーンは最長射程の3倍以上。** 120mだった頃は最長射程110mがレーンとほぼ
    同じで、自陣に立った砲が敵拠点の10m手前まで届いた。押し込んだ側の後衛が
    一歩も動かずに拠点を削れるので、先に前線を上げた側がそのまま勝つ。
    「レーン長より短ければよい」では足りない、というのがこの規則の由来。

    逆に長すぎてもいけない ―― 一度360mまで伸ばしたときは、勝っている側でも
    拠点まで歩ききれずに36試合すべてが引き分けになった。上限は試合時間と
    速度から決まるので、ここでは下限だけを縛って、上は balance.py で測る。
    """
    lane = game.lane_length
    reach = game.max_reach
    ratio = game.roster_rules["lane_per_reach_min"]
    report.check(lane >= reach * ratio - 1e-9,
                 f"field: レーン {lane:.0f}m が最長射程 {reach:.0f}m の "
                 f"{ratio:g}倍（{reach * ratio:.0f}m）に届かない。"
                 "自陣から敵拠点の近くまで届く射程が残ると、"
                 "押し込んだ側が動かずに拠点を削れる")

    everyone = list(game.units.values()) + list(game.trumps.values())
    longest = max(everyone, key=lambda u: u.far)
    report.check(longest.far <= reach,
                 f"field: {longest.name} の射程 {longest.far}m が"
                 f"上限 {reach:.0f}m を超える")

    # 一番遅いキャラでも、試合時間のうちにレーンを渡りきれること。
    # 渡りきれない足があると、そのキャラは「前線が上がってから出す札」しか
    # 名乗れず、序盤の択から丸ごと外れる。
    slowest = min(game.units.values(), key=lambda u: u.speed_mps)
    crossing = lane / slowest.speed_mps
    report.check(crossing <= game.time_limit * 0.5,
                 f"field: 最も遅い {slowest.name}（速度 {slowest.speed_mps}）は"
                 f"レーン {lane:.0f}m を渡るのに {crossing:.0f}秒 かかり、"
                 f"試合 {game.time_limit:.0f}秒 の半分を超える")


def range_band(spec: Unit, game: GameData) -> str:
    """射程の帯の名前。data の range_families がそのまま境目。"""
    bands = game.roster_rules["range_families"]
    for name in ("接近戦", "前線範囲", "遠距離"):
        lo, hi = bands[name]
        if lo < spec.far <= hi or (lo == 0 and spec.far <= hi):
            return name
    return "遠距離"


def check_range_price(game: GameData, report: Report) -> None:
    """**射程が長いほど、同じ値段で買えるDPSは低い。**

    遠距離は前線に立たないので被弾しない。その安全がそのまま値段に乗る、
    というのがこの規則。逆に接近戦は殴られながら殴るので、同じ値段でも
    手数を多くしてよい。1体ずつではなく**帯の中央値**で見る ―― 個々の
    キャラには役割ぶんの凹凸があってよく、崩してはいけないのは全体の傾きの方。
    """
    order = ["接近戦", "前線範囲", "遠距離"]
    buckets: dict[str, list[float]] = {name: [] for name in order}
    for unit in game.units.values():
        buckets[range_band(unit, game)].append(unit.dps / unit.cost)

    for name in order:
        if not report.check(bool(buckets[name]),
                            f"characters: 射程帯「{name}」のユニットが1体も居ない"):
            return

    medians = {name: statistics.median(values) for name, values in buckets.items()}
    for near, far in zip(order, order[1:]):
        report.check(medians[near] > medians[far],
                     f"characters: 「{near}」のDPS/コスト中央値 {medians[near]:.1f} が"
                     f"「{far}」の {medians[far]:.1f} を上回っていない。"
                     "射程が伸びたら、そのぶん同じ値段で買える手数は落とす")

    # 遠距離が試合の火力を担わないこと。担うと、前に出る理由が消える。
    dps_median = statistics.median(u.dps for u in game.units.values())
    for unit in game.units.values():
        if not unit.is_ranged(game.far_threshold):
            continue
        report.check(unit.dps <= dps_median,
                     f"{unit.name}: 射程 {unit.far}m で DPS {unit.dps:.0f} が"
                     f"中央値 {dps_median:.0f} を超える。"
                     "被弾しない側が火力まで持つと、近づく理由が無くなる")


def check_races(game: GameData, report: Report) -> None:
    """種族は編成の材料。特性がここを見るので、揃っていないと成立しない。"""
    declared = set(game.races)
    used = {u.race for u in game.units.values()}
    for race in sorted(used - declared):
        report.errors.append(f"characters: 未宣言の種族 {race}")
    for race in sorted(declared - used):
        report.errors.append(f"roster: 種族 {race} のユニットが1体も居ない")

    need = game.roster_rules["slots"]
    for race in sorted(declared & used):
        members = game.units_of_race(race)
        report.check(len(members) >= need,
                     f"種族 {race}: {len(members)}体しか居ない。"
                     f"出撃枠 {need} を同じ種族で埋められないと、"
                     "その種族の同胞持ちだけが割を食う")

    for trump in game.trumps.values():
        report.check(trump.race in declared,
                     f"{trump.name}: 未宣言の種族 {trump.race}")


def check_traits(game: GameData, report: Report) -> None:
    """特性。**触れてよいのは出撃コストだけ。**

    戦闘中の数字に効く特性を足し始めると、シミュレータがキャラごとの
    分岐だらけになって、何が効いたのか読めなくなる。ここはその一線を
    機械で守るための検査。
    """
    rules = game.trait_rules
    floor = rules["min_deploy_cost"]
    slots = game.roster_rules["slots"]
    cap = game.levels[-1]["max"]

    for trait in game.traits.values():
        report.check(trait.kind in TRAIT_KINDS,
                     f"{trait.name}: 未知の特性の種類 {trait.kind}。"
                     "出撃コストに効くもの以外は足さない")
        report.check(bool(trait.describe()),
                     f"{trait.name}: 説明が組み立てられない（{trait.kind}）")

    holders = [u for u in game.units.values() if u.trait]
    for unit in holders:
        trait = game.trait_of(unit)
        if not report.check(trait is not None,
                            f"{unit.name}: 未定義の特性 {unit.trait}"):
            continue
        params = trait.params

        report.check(unit.cost <= cap,
                     f"{unit.name}: 素のコスト {unit.cost} が最終上限 {cap} を超える")

        if trait.kind == COST_MINUS_PER_SAME_RACE_IN_ROSTER:
            # 同胞は「同じ種族で固める」ことへの報酬。固めきったときの値段が
            # 素の値段よりはっきり安く、かつ床を割らないこと。
            best = unit.cost - params["amount"] * (slots - 1)
            report.check(best >= floor,
                         f"{unit.name}: 同種族で固めると {best} まで下がり、"
                         f"下限 {floor} を割る")
            report.check(best <= unit.cost * 0.7,
                         f"{unit.name}: 固めても {unit.cost} → {best} しか下がらない。"
                         "種族で固める理由にならない")
            mates = len(game.units_of_race(unit.race)) - 1
            report.check(mates >= slots - 1,
                         f"{unit.name}: 種族 {unit.race} に同胞が {mates}体しか"
                         f"居らず、枠 {slots} を埋めきれない")
        elif trait.kind == COST_MINUS_IF_LAST_SAME_RACE:
            report.check(unit.cost - params["amount"] >= floor,
                         f"{unit.name}: 連携で {floor} を割る")
            # 「出す順番を作る」対価なので、安いキャラに付けても意味がない。
            report.check(unit.cost >= statistics.median(
                u.cost for u in game.units.values()),
                f"{unit.name}: 連携はコストの高いキャラに付ける。"
                "安いキャラだと、下ごしらえの手間に見合わない")
        elif trait.kind == COST_MULT_WHEN_HURT:
            report.check(0.0 < params["mult"] < 1.0,
                         f"{unit.name}: 背水の倍率 {params['mult']} が 0〜1 の外")
            report.check(0.0 < params["base_hp_at_most"] < 1.0,
                         f"{unit.name}: 背水の閾値が 0〜1 の外")

    report.check(rules["max_per_character"] == 1,
                 "traits: 1体に2つ以上の特性を許すと、値段がどこから来たのか"
                 "読めなくなる。data 側の trait はいまも1つしか持てない形なので、"
                 "上限を変えるなら Unit.trait も複数形にすること")

    # 特性が1つも使われていないと、data だけあって効いていない状態になる。
    used = {u.trait for u in holders}
    for trait in game.traits.values():
        report.check(trait.id in used,
                     f"traits: {trait.name} を持つユニットが1体も居ない")


def check_roster_size(game: GameData, report: Report) -> None:
    """1試合に出せる種類が、読み合いになる数に届いているか。

    種類が少ないと相手の手が数えられてしまい、出す順番の択が消える。
    """
    roster = game.roster_rules
    need = game.min_types_per_match
    slots = roster["slots"]
    report.check(slots >= need,
                 f"roster: 出撃枠が {slots} 種類しかない（下限 {need}）。"
                 "相手の手が数えられてしまい、読み合いにならない")
    report.check(roster["chosen_slots"] + roster["random_slots"] == slots,
                 f"roster: 固定 {roster['chosen_slots']} ＋ 抽選 "
                 f"{roster['random_slots']} が枠数 {slots} と合わない")

    # 試遊用の見本編成も同じ下限を満たすこと。ここが6体のままだと、
    # 実際に遊べる唯一の編成が読み合いにならない形で固定される。
    trial = trial_roster()
    ids = [u["id"] for u in trial["roster"]]
    report.check(len(ids) >= need,
                 f"preset_roster: 見本編成が {len(ids)} 種類しかない（下限 {need}）")
    report.check(len(ids) == len(set(ids)), "preset_roster: 同じユニットが二重に居る")
    for uid in ids:
        if uid not in game.units:
            report.errors.append(f"preset_roster: 知らないユニット {uid}")

    known = [game.units[u] for u in ids if u in game.units]
    if known:
        report.check(any(u.is_wall(game.wall_threshold) for u in known),
                     "preset_roster: 壁が入っていない")
        report.check(any(u.anti_wall_mult > 1.5 for u in known),
                     "preset_roster: 壁を崩す答えが入っていない")
        rear = [u for u in known
                if u.is_rear_area(game.far_threshold, game.area_pierce_min)]
        report.check(bool(rear), "preset_roster: 遠方範囲が入っていない")
        if rear:
            deepest = max(u.near for u in rear)
            speed_median = statistics.median(u.speed_mps
                                             for u in game.units.values())
            report.check(any(u.speed_mps > speed_median and u.far < deepest
                             for u in known),
                         f"preset_roster: 死角 {deepest:.0f}m に飛び込める"
                         "足の速いユニットが入っていない")


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
    check_range_price(game, report)
    check_races(game, report)
    check_traits(game, report)
    check_field(game, report)
    check_roster_size(game, report)
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
