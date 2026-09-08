"""試合中の判断。

設計書の主張（攻めが弱いと成長が正解になり、攻めが強いと成長が博打になる）が
本当に成り立つかを見るために、性格の違う方針をいくつか置いてある。
"""

from __future__ import annotations

from .battle import Battle, Side


def _pressure(battle: Battle, side: Side, within: float) -> bool:
    """自陣の近くまで敵が来ているか。"""
    return any(abs(f.x - side.base_x) <= within
               for f in battle.live(1 - side.index))


def _try_parry(battle: Battle, side: Side) -> bool:
    """相手の詠唱に合わせる。反応時間を待ってから、窓が完了を覆う位置で押す。"""
    if side.parry_charges <= 0:
        return False
    enemy = battle.enemy_of(side)
    if enemy.casting is None:
        return False
    reaction = battle.game.readability["human_reaction_sec"]
    window = battle.game.perks["parry"].params["invuln_sec"]
    if battle.t - enemy.cast_started < reaction:
        return False                      # まだ見えていない
    if enemy.cast_left > window * 0.5:
        return False                      # 早すぎる。窓が先に切れる
    return battle.use_parry(side)


def _try_card(battle: Battle, side: Side) -> bool:
    """呪文はユニットと同じ資金を食う。**出撃ぶんを残してから撃つ。**

    ここが新しい択で、いくら効果が大きくても、前線を維持できなくなるほど
    払うと負ける。方針の側にも「取っておく」という判断が要る。
    """
    if side.casting is not None or side.gcd_left > 0:
        return False
    own_units = len(battle.live(side.index))
    foe_units = len(battle.live(1 - side.index))

    cheapest = min((side.unit_cost(battle.game.units[uid])
                    for uid in side.loadout.roster), default=0.0)
    reserve = cheapest * 3          # 壁を切らさないぶんは手を付けない

    best, best_card = None, None
    for source in side.sources():
        if not side.castable(source):
            continue
        card = side.card_of(source)
        if side.money - card.cost < reserve:
            continue
        scope = card.apply.scope
        if scope.startswith("own") and scope.endswith("units") and own_units < 2:
            continue                # 誰も居ないところに自軍強化を撒かない
        if scope == "enemy_units" and foe_units < 2:
            continue
        if best_card is None or card.power > best_card.power:
            best, best_card = source, card

    return battle.start_cast(side, best) if best else False


def _try_deploy(battle: Battle, side: Side) -> bool:
    """前に立つ者を切らさないまま、**高いものは貯めて出す。**

    「一番高いものを出す」だけにしていたときは、両軍とも遠距離だけの隊列に
    なって、80mの空きを挟んで撃ち合ったまま試合が終わった（実測で決着率0%）。
    遠距離は前に立つ者が居て初めて仕事になるので、頭数の下限を先に埋める。

    そのうえで **貯める** ―― 「いまその場で買える一番高いもの」を毎tick
    買っていたときは、資金が1〜10を行き来するだけで、巨兵（40）も臼砲（22）も
    一度も場に出なかった（実測：greed が300秒で兵卒75体・臼砲3体・巨兵0体、
    使えなかった資金34を抱えたまま時間切れ）。コストの幅を1〜40に広げた意味は、
    **貯めるという判断が方針の側にも無いと測れない。**
    """
    game = battle.game
    line = game.far_threshold
    alive = [f for f in side.fighters if f.alive]
    front = sum(1 for f in alive if f.spec.far <= line)
    ready = [uid for uid in side.loadout.roster
             if side.deploy_cd.get(uid, 0.0) <= 0]
    affordable = [uid for uid in ready
                  if side.money >= side.unit_cost(game.units[uid])]

    close = [uid for uid in affordable if game.units[uid].far <= line]
    if front < max(2, battle.max_units // 3) and close:
        return battle.deploy(side, min(close, key=lambda uid: game.units[uid].cost))

    # 狙いは「財布の上限で届く一番高いもの」。届くまでは何も出さずに貯める。
    #
    # ただし **隊列の半分は前に立つ者にする。** 一番高いものは遠距離である
    # ことが多く、これを付けないと狙いが臼砲（22・射程80m）に固定されて
    # 隊列が砲の壁になる（実測：1試合で臼砲6・重弩6に対して巨兵2）。
    # 遠距離は前に立つ者が居て初めて仕事になる、という設計そのもの。
    #
    # なおこれを付けても balanced 対 greed の引き分けは減らない ―― あちらは
    # 「自陣のすぐ前に1コストを出し続けられる側は前線を明け渡さない」という
    # 盤面の話で、方針の買い方とは別（設計書12.5）。
    pool = ready
    if front * 2 < len(alive):
        pool = [uid for uid in ready if game.units[uid].far <= line] or ready
    reachable = [uid for uid in pool
                 if side.unit_cost(game.units[uid]) <= side.money_cap]
    if reachable:
        goal = max(reachable, key=lambda uid: game.units[uid].cost)
        if side.unit_cost(game.units[goal]) > side.money:
            return False
        return battle.deploy(side, goal)
    if not affordable:
        return False
    return battle.deploy(side, max(affordable, key=lambda uid: game.units[uid].cost))


def make_policy(target_level: int, defend_within: float = 40.0):
    """資金をどこまで育ててから戦うか、で性格が変わる。"""

    def policy(battle: Battle, side: Side) -> None:
        _try_parry(battle, side)
        if side.busy:
            return                       # レベルアップ中は手が空かない

        under_pressure = _pressure(battle, side, defend_within)
        alive = sum(1 for f in side.fighters if f.alive)

        if not under_pressure and side.level < target_level:
            if side.can_upgrade():
                side.upgrade()
                return
            # 貯めている間は出撃を控える。これをしないと毎tick使い切って
            # いつまでも上のレベルに届かない ―― 設計書4.3の「育てている間は
            # 何も出せない」は、方針の側にも要る。
            if alive >= 1:
                return

        battle.summon_trump(side)
        _try_card(battle, side)

        if side.surge_charges > 0 and not under_pressure:
            front = [f.x for f in battle.live(side.index)]
            if front:
                # 前線が自陣寄りで止まっているなら押し上げる
                depth = abs(max(front, key=lambda x: abs(x - side.base_x))
                            - side.base_x)
                if depth < battle.game.lane_length * 0.4:
                    battle.use_surge(side)

        _try_deploy(battle, side)

    return policy


# 「どこまで育ててから戦うか」と「どこまで来られたら守りに戻るか」。
# **どちらも data の尺度に合わせて置き直すもの。** 財布の上限は 6〜46、
# レーンは360m。ここが古い尺度のままだと、方針が一番安いユニットしか
# 買えなくなり、試合が「兵卒の押し合い」で固まる（実測で決着率0%）。
POLICIES = {
    "rush":     make_policy(target_level=4, defend_within=150.0),
    "balanced": make_policy(target_level=6, defend_within=120.0),
    "greed":    make_policy(target_level=8, defend_within=90.0),
}
