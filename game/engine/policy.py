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
    if side.casting is not None or side.gcd_left > 0:
        return False
    own_units = len(battle.live(side.index))
    foe_units = len(battle.live(1 - side.index))

    for card_id in side.loadout.deck:
        if side.card_cd.get(card_id, 0.0) > 0:
            continue
        card = battle.game.cards[card_id]
        wants_own = card.apply.scope.startswith("own")
        if wants_own and own_units < 2:
            continue
        if not wants_own and card.apply.scope == "enemy_units" and foe_units < 2:
            continue
        return battle.start_cast(side, card_id)
    return False


def _try_deploy(battle: Battle, side: Side) -> bool:
    alive = sum(1 for f in side.fighters if f.alive)
    affordable = [uid for uid in side.loadout.roster
                  if side.deploy_cd.get(uid, 0.0) <= 0
                  and side.money >= side.unit_cost(battle.game.units[uid])]
    if not affordable:
        return False
    # 壁が足りない時は一番安いものを、足りている時は一番高いものを出す
    cheap = alive < 2
    pick = (min if cheap else max)(
        affordable, key=lambda uid: battle.game.units[uid].cost)
    return battle.deploy(side, pick)


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


POLICIES = {
    "rush":     make_policy(target_level=2, defend_within=50.0),
    "balanced": make_policy(target_level=4, defend_within=40.0),
    "greed":    make_policy(target_level=6, defend_within=30.0),
}
