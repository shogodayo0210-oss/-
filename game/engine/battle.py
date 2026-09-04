"""1レーンの戦闘。

固定タイムステップの決定論的シミュレーション。同じ入力からは必ず同じ試合になるので、
リプレイと不正検証が同じ経路を通る（設計書8章）。

数値はひとつもここに書かない。全部 `data/*.json` から来る。
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field

from collections import deque

from .data import Card, GameData, Trump, Unit
from .draft import stock_sequence

# 位置の比較に使う許容差。左右のユニットは逆向きに動くので、同じ地点でも
# 浮動小数点の下位桁が一致しない。素で比較すると「前の味方に詰まるか」の
# 判定が 1e-16 の差でひっくり返り、左右対称の試合が割れる。
EPS = 1e-6

# 効果の対象。カードの scope はこの4つのどれか。
OWN_UNITS, ENEMY_UNITS, OWN_DEPLOY, ENEMY_ECONOMY = (
    "own_units", "enemy_units", "own_deploy", "enemy_economy")

# シミュレータが再現していない特典。情報系（索敵・読心・検算）は編成と
# 読み合いの話で、戦闘の数字には効かない。編成系は3章のドラフト側の話。
NOT_SIMULATED = {
    "scout_1", "scout_2", "mind_read", "gauge_sight",
    "pick_plus", "reroll", "promote", "reserve", "pocket", "late_pick",
    "bunker", "feint", "recall",
    "intel_net", "card_watch", "overdrive", "siege_order", "breach_order",
    "warchest", "swift_start", "veteran",
}


@dataclass(frozen=True)
class Loadout:
    """試合に持ち込むもの。編成フェーズの出力。"""
    avatar: str
    roster: tuple[str, ...]     # 出撃できるユニット8種
    brought: str                # 持ち込む呪文1枚。確実に手に入る代わりにCDが長い
    trump: str
    stock_seed: str = "stock"   # ランダムストックの並びを決める種

    @property
    def deck(self) -> tuple[str, ...]:
        """持ち込みだけ。commit や表示のために1枚のタプルとして見せる。"""
        return (self.brought,)


@dataclass
class Effect:
    """カードがかけた、時間で切れる修正。"""
    stat: str
    mult: float | None
    add: float | None
    until: float
    source: str


@dataclass
class Fighter:
    """場に出ている1体。切り札も同じクラスで扱う。"""
    spec: Unit
    side: int
    x: float
    hp: float
    facing: int
    windup_left: float = 0.0
    recover_left: float = 0.0
    stun_left: float = 0.0
    knockbacks_done: int = 0
    summon_left: float = 0.0
    lifespan_left: float = math.inf

    @property
    def alive(self) -> bool:
        return self.hp > 0

    @property
    def ready(self) -> bool:
        """召喚演出が終わって、実際に戦える状態か。"""
        return self.summon_left <= 0

    def band(self, speed_mult: float = 1.0) -> tuple[float, float]:
        """世界座標での攻撃が当たる帯。向きで反転する。"""
        near, far = self.spec.near, self.spec.far
        if self.facing > 0:
            return self.x + near, self.x + far
        return self.x - far, self.x - near


class Side:
    """片方のプレイヤー。拠点・資金・場のユニット・カード・特典を持つ。"""

    def __init__(self, game: GameData, loadout: Loadout, index: int):
        self.game = game
        self.loadout = loadout
        self.index = index
        self.base_x = 0.0 if index == 0 else game.lane_length
        self.facing = 1 if index == 0 else -1

        self.base_hp = float(game.base_hp)
        self.level = 1
        self.money = float(game.economy["start"])

        self.fighters: list[Fighter] = []
        self.deploy_cd: dict[str, float] = {}
        self.gcd_left = 0.0
        self.casting: Card | None = None
        self.cast_source: tuple[str, int] | None = None
        self.cast_left = 0.0
        self.cast_started = 0.0
        self.effects: list[Effect] = []

        # 呪文。持ち込み1枚は確実に手に入る代わりに個別クールタイムが長く、
        # ストック3枠は運だが資金さえあれば続けて撃てる（設計書5章）。
        rules = game.card_rules
        self.brought = loadout.brought
        self.brought_cd = 0.0
        self.restock_sec = rules["restock_sec"]
        self._queue: deque[str] = deque(
            stock_sequence(game, loadout.stock_seed, 96))
        self.stock: list[str | None] = []
        self.restock: list[float] = [0.0] * rules["stock_slots"]
        for _ in range(rules["stock_slots"]):
            self.stock.append(self._draw())

        self.trump_used = False
        self.deploy_lock_left = 0.0
        self.upgrading_left = 0.0

        avatar = game.avatars[loadout.avatar]
        self.perks = set(avatar.perks)
        self.parry_charges = self._perk_param("parry", "charges", 0)
        self.parry_until = -1.0
        self.surge_charges = self._perk_param("surge", "charges", 0)
        self.last_stand_used = False

        if "head_start" in self.perks:
            self.money += self.game.perks["head_start"].params["start_money"]

        self.log: list[str] = []

    # ------------------------------------------------------------------ 呪文
    def _draw(self) -> str | None:
        """ストックに1枚流し込む。いま並んでいる札とは重ならないようにする。"""
        for _ in range(len(self._queue)):
            card_id = self._queue.popleft()
            self._queue.append(card_id)          # 並びは循環させる
            if card_id not in self.stock:
                return card_id
        return None

    def card_of(self, source: tuple[str, int]) -> Card | None:
        kind, index = source
        if kind == "brought":
            return self.game.cards[self.brought]
        if 0 <= index < len(self.stock) and self.stock[index]:
            return self.game.cards[self.stock[index]]
        return None

    def castable(self, source: tuple[str, int]) -> bool:
        """いま撃てるか。資金・詠唱中・共通CD・育成中・個別CDを全部見る。"""
        if self.casting is not None or self.gcd_left > 0 or self.busy:
            return False
        if source[0] == "brought" and self.brought_cd > 0:
            return False
        card = self.card_of(source)
        return card is not None and self.money >= card.cost

    def sources(self) -> list[tuple[str, int]]:
        return [("brought", 0)] + [("stock", i) for i in range(len(self.stock))]

    # ------------------------------------------------------------------ 特典
    def _perk_param(self, perk_id: str, key: str, default):
        if perk_id not in self.perks:
            return default
        return self.game.perks[perk_id].params.get(key, default)

    # ------------------------------------------------------------------ 効果
    def stat(self, name: str, base: float) -> float:
        """かかっている効果を掛けたあとの値。掛けてから足す。"""
        value = base
        for e in self.effects:
            if e.stat != name:
                continue
            if e.mult is not None:
                value *= e.mult
            if e.add is not None:
                value += e.add
        return value

    def add_effect(self, effect: Effect) -> None:
        self.effects.append(effect)

    # ------------------------------------------------------------------ 資金
    @property
    def level_row(self) -> dict:
        return self.game.levels[self.level - 1]

    @property
    def money_cap(self) -> float:
        return self.level_row["max"]

    @property
    def income(self) -> float:
        return self.stat("income", self.level_row["per_sec"])

    @property
    def upgrade_cost(self) -> float | None:
        return self.level_row.get("upgrade_cost")

    def can_upgrade(self) -> bool:
        cost = self.upgrade_cost
        return cost is not None and self.money >= cost

    @property
    def busy(self) -> bool:
        """レベルアップ中。設計書4.3の「育てている間は何も出せない」の実体。"""
        return self.upgrading_left > 0

    def upgrade(self) -> None:
        self.money -= self.upgrade_cost
        self.level += 1
        self.upgrading_left = self.game.economy["growth"]["upgrade_sec"]

    def unit_cost(self, spec: Unit) -> float:
        return self.stat("cost", spec.cost)

    def deploy_cooldown(self, spec: Unit) -> float:
        return self.stat("deploy_cooldown", spec.cooldown_sec)


class Battle:
    """1試合。`run()` を呼ぶと決着まで進む。"""

    def __init__(self, game: GameData, a: Loadout, b: Loadout,
                 policy_a, policy_b, verbose: bool = False):
        self.game = game
        self.sides = (Side(game, a, 0), Side(game, b, 1))
        self.policies = (policy_a, policy_b)
        self.tick = game.combat["tick_sec"]
        self.kb_distance = game.combat["knockback_distance_m"]
        self.spacing = game.combat["unit_spacing_m"]
        self.kb_stun = game.combat["knockback_stun_sec"]
        self.max_units = game.match["field"]["max_units_per_side"]
        self.t = 0.0
        # そのtickの世界の見え方。全員が同じ盤面を見て動くので、
        # 「先に処理された側が先に殴れる」という順番の有利が出ない。
        self._snap: list[list[tuple[float, Fighter]]] = [[], []]
        self._damage: list[tuple[Fighter, float]] = []
        self._base_damage: list[tuple[Side, float]] = []
        self.events: list[tuple[float, int, str]] = []
        self.verbose = verbose

    # ------------------------------------------------------------------ 記録
    def note(self, side: int, text: str) -> None:
        self.events.append((self.t, side, text))
        if self.verbose:
            print(f"[{self.t:6.2f}] P{side + 1} {text}")

    # -------------------------------------------------------------- 出撃・行動
    def enemy_of(self, side: Side) -> Side:
        return self.sides[1 - side.index]

    def deploy(self, side: Side, unit_id: str) -> bool:
        spec = self.game.units[unit_id]
        cost = side.unit_cost(spec)
        if (side.money < cost or side.deploy_cd.get(unit_id, 0.0) > 0
                or side.deploy_lock_left > 0 or side.busy
                or len(side.fighters) >= self.max_units):
            return False
        side.money -= cost
        side.deploy_cd[unit_id] = side.deploy_cooldown(spec)
        side.fighters.append(Fighter(spec=spec, side=side.index, x=side.base_x,
                                     hp=float(spec.hp), facing=side.facing))
        return True

    def summon_trump(self, side: Side) -> bool:
        spec: Trump = self.game.trumps[side.loadout.trump]
        rules = self.game.trump_rules
        if (side.trump_used or self.t < rules["unlock_at_sec"]
                or side.money < spec.cost or side.deploy_lock_left > 0
                or side.busy):
            return False
        side.money -= spec.cost
        side.trump_used = True
        side.fighters.append(Fighter(
            spec=spec, side=side.index, x=side.base_x, hp=float(spec.hp),
            facing=side.facing, summon_left=spec.summon_sec,
            lifespan_left=spec.lifespan_sec + spec.summon_sec))
        self.note(side.index, f"切り札 {spec.name} を召喚（演出 {spec.summon_sec}秒）")
        return True

    def cast_time(self, side: Side, card: Card) -> float:
        """詠唱。短縮しても床は割らない（設計書7.5の契約）。"""
        seconds = card.cast_sec
        if "quick_cast" in side.perks:
            seconds *= self.game.perks["quick_cast"].params["cast_time_mult"]
        return max(seconds, self.game.readability["min_cast_sec"])

    def start_cast(self, side: Side, source: tuple[str, int]) -> bool:
        """詠唱に入る。**資金と札はこの時点で消える。**

        見切られた場合も戻らない。撃つ判断そのものに値段が付いているので、
        「相手が見切りを持っているか」が資金の読み合いに直結する。
        """
        if not side.castable(source):
            return False
        card = side.card_of(source)
        side.money -= card.cost

        kind, index = source
        if kind == "brought":
            side.brought_cd = card.cooldown_sec
        else:
            side.stock[index] = None
            side.restock[index] = side.restock_sec

        side.casting = card
        side.cast_source = source
        side.cast_left = self.cast_time(side, card)
        side.cast_started = self.t
        where = "持ち込み" if kind == "brought" else f"ストック{index + 1}"
        self.note(side.index,
                  f"{card.name} を詠唱（{where}・{card.cost} / {side.cast_left:.2f}秒）")
        return True

    def resolve_cast(self, side: Side) -> None:
        card = side.casting
        side.casting = None
        side.cast_source = None
        enemy = self.enemy_of(side)
        side.gcd_left = self.game.card_rules["global_cooldown_sec"]

        # 見切りは「呪文を潰す」。無敵の窓が詠唱の完了を覆っていれば不発。
        # 資金も札も戻らないので、潰された側の損は資金ぶんだけ大きい。
        if enemy.parry_until >= self.t:
            reward = self.game.perks["parry"].params["money_on_success"]
            enemy.money = min(enemy.money + reward, enemy.money_cap)
            enemy.parry_until = -1.0
            self.note(enemy.index,
                      f"見切り成功 — {card.name}（{card.cost}）を潰した（資金 +{reward}）")
            return

        target = side if card.apply.scope.startswith("own") else enemy
        target.add_effect(Effect(stat=card.apply.stat, mult=card.apply.mult,
                                 add=card.apply.add,
                                 until=self.t + card.duration_sec, source=card.id))
        self.note(side.index, f"{card.name} 発動（{card.duration_sec}秒）")

    def use_parry(self, side: Side) -> bool:
        if side.parry_charges <= 0:
            return False
        params = self.game.perks["parry"].params
        side.parry_charges -= 1
        side.parry_until = self.t + params["invuln_sec"]
        side.deploy_lock_left = params["deploy_lock_sec"]
        self.note(side.index, f"見切り（無敵 {params['invuln_sec']}秒）")
        return True

    def use_surge(self, side: Side) -> bool:
        if side.surge_charges <= 0:
            return False
        params = self.game.perks["surge"].params
        side.surge_charges -= 1
        side.add_effect(Effect(stat="speed", mult=params["speed_mult"], add=None,
                               until=self.t + params["duration_sec"], source="surge"))
        self.note(side.index, f"突撃（速度 ×{params['speed_mult']} / {params['duration_sec']}秒）")
        return True

    # ------------------------------------------------------------------ 戦闘
    def snapshot(self) -> None:
        """tickの頭で盤面を固定する。全員がこれを見て動く。"""
        self._snap = [
            sorted(((f.x, f) for f in side.fighters if f.alive and f.ready),
                   key=lambda pair: pair[0])
            for side in self.sides
        ]

    def live(self, index: int) -> list[Fighter]:
        """そのtickの頭で場に居た側のユニット。方針もここを見る。"""
        return [f for _, f in self._snap[index]]

    def targets_in_band(self, fighter: Fighter) -> list[Fighter]:
        lo, hi = fighter.band()
        rows = self._snap[1 - fighter.side]
        xs = [x for x, _ in rows]
        lo_i, hi_i = bisect_left(xs, lo - EPS), bisect_right(xs, hi + EPS)
        found = rows[lo_i:hi_i]
        found.sort(key=lambda pair: abs(pair[0] - fighter.x))
        return [f for _, f in found]

    def base_in_band(self, fighter: Fighter) -> bool:
        lo, hi = fighter.band()
        return lo - EPS <= self.sides[1 - fighter.side].base_x <= hi + EPS

    def advance_limit(self, fighter: Fighter) -> float:
        """前を行く味方に詰まる位置。これが無いと全員が同じ点に重なり、
        攻撃範囲の設計（前線範囲・後方範囲）が意味を失う。"""
        rows = self._snap[fighter.side]
        xs = [x for x, _ in rows]
        if fighter.facing > 0:
            idx = bisect_right(xs, fighter.x + EPS)
            if idx >= len(xs):
                return self.game.lane_length
            return xs[idx] - self.spacing
        idx = bisect_left(xs, fighter.x - EPS) - 1
        if idx < 0:
            return 0.0
        return xs[idx] + self.spacing

    def apply_damage(self, victim: Fighter, amount: float) -> None:
        side = self.sides[victim.side]
        victim.hp -= amount
        if victim.hp <= 0:
            return

        kb = side.stat("knockback", victim.spec.knockback)
        if kb < 1:                                    # 堅陣：後退しなくなる
            return
        segment = victim.spec.hp / kb
        crossed = int((victim.spec.hp - victim.hp) // segment)
        if crossed > victim.knockbacks_done:
            victim.knockbacks_done = crossed
            victim.x -= victim.facing * self.kb_distance
            victim.x = max(0.0, min(self.game.lane_length, victim.x))
            victim.stun_left = self.kb_stun
            victim.windup_left = 0.0

    def resolve_attack(self, fighter: Fighter) -> None:
        side = self.sides[fighter.side]
        enemy = self.enemy_of(side)
        power = side.stat("attack", fighter.spec.attack)

        if enemy.parry_until >= self.t:
            return

        wall_line = self.game.wall_threshold

        # 拠点も帯の中の「的」のひとつ。近い順に、貫通の数だけ当たる。
        #
        # 以前は「敵ユニットが1体でも帯に居れば拠点は絶対に安全」だった。
        # これだと両者が安い壁を出し続ける限り拠点に永久に触れられず、
        # 実測で36試合中28が0対0の引き分けになっていた。
        # 拠点を的の列に混ぜると、**貫通の余りが拠点に届く** ――
        # 前線を薙げるユニットだけが攻城できる、という設計どおりの形になる。
        targets: list[tuple[float, Fighter | None]] = [
            (abs(f.x - fighter.x), f) for f in self.targets_in_band(fighter)]
        if self.base_in_band(fighter):
            targets.append((abs(enemy.base_x - fighter.x), None))
        targets.sort(key=lambda pair: pair[0])   # 同着は先に入った敵が優先

        for _, victim in targets[: fighter.spec.pierce]:
            if victim is None:
                self._base_damage.append(
                    (enemy, power * fighter.spec.siege_mult))
            else:
                bonus = (fighter.spec.anti_wall_mult
                         if victim.spec.is_wall(wall_line) else 1.0)
                self._damage.append((victim, power * bonus))

    def step_fighter(self, fighter: Fighter) -> None:
        side = self.sides[fighter.side]
        dt = self.tick

        if fighter.summon_left > 0:
            fighter.summon_left -= dt
            return
        if fighter.stun_left > 0:
            fighter.stun_left -= dt
            return

        interval_mult = side.stat("attack_interval", 1.0)
        if fighter.recover_left > 0:
            fighter.recover_left -= dt
            return
        if fighter.windup_left > 0:
            fighter.windup_left -= dt
            if fighter.windup_left <= 0:
                self.resolve_attack(fighter)
                cycle = fighter.spec.attack_interval_sec * interval_mult
                windup = fighter.spec.attack_windup_sec * interval_mult
                fighter.recover_left = max(0.0, cycle - windup)
            return

        if self.targets_in_band(fighter) or self.base_in_band(fighter):
            fighter.windup_left = fighter.spec.attack_windup_sec * interval_mult
            return

        speed = side.stat("speed", fighter.spec.speed_mps)
        moved = fighter.x + fighter.facing * speed * dt
        limit = self.advance_limit(fighter)
        fighter.x = min(moved, limit) if fighter.facing > 0 else max(moved, limit)
        fighter.x = max(0.0, min(self.game.lane_length, fighter.x))

    # ------------------------------------------------------------------ 進行
    def step(self) -> None:
        dt = self.tick

        # 盤面の固定は判断より前。あとにすると、先に動いた側の出撃が
        # 同じtickの相手の判断に見えてしまい、後手だけが得をする。
        self.snapshot()

        for side in self.sides:
            side.money = min(side.money + side.income * dt, side.money_cap)
            side.effects = [e for e in side.effects if e.until > self.t]
            side.gcd_left = max(0.0, side.gcd_left - dt)
            side.deploy_lock_left = max(0.0, side.deploy_lock_left - dt)
            side.upgrading_left = max(0.0, side.upgrading_left - dt)
            for uid in list(side.deploy_cd):
                side.deploy_cd[uid] = max(0.0, side.deploy_cd[uid] - dt)

            side.brought_cd = max(0.0, side.brought_cd - dt)
            for i, left in enumerate(side.restock):
                if side.stock[i] is not None:
                    continue
                side.restock[i] = left = max(0.0, left - dt)
                if left <= 0:
                    side.stock[i] = side._draw()

            if ("last_stand" in side.perks and not side.last_stand_used
                    and side.base_hp <= self.game.base_hp
                    * self.game.perks["last_stand"].params["threshold"]):
                side.last_stand_used = True
                gain = self.game.perks["last_stand"].params["money_gain"]
                side.money = min(side.money + gain, side.money_cap)
                self.note(side.index, f"起死回生（資金 +{gain}）")

        for side, policy in zip(self.sides, self.policies):
            policy(self, side)

        for side in self.sides:
            if side.casting is not None:
                side.cast_left -= dt
                if side.cast_left <= 0:
                    self.resolve_cast(side)

        self._damage.clear()
        self._base_damage.clear()
        for side in self.sides:
            for fighter in list(side.fighters):
                if fighter.lifespan_left is not math.inf:
                    fighter.lifespan_left -= dt
                self.step_fighter(fighter)

        # 両者ぶんまとめて適用する。片方の攻撃が先に通って相手が
        # 撃ち返せない、という順番の有利をなくすため。
        for victim, amount in self._damage:
            self.apply_damage(victim, amount)
        for side, amount in self._base_damage:
            side.base_hp -= amount

        for side in self.sides:
            enemy = self.enemy_of(side)
            survivors = []
            for fighter in side.fighters:
                if not fighter.alive:
                    reward = fighter.spec.cost * self.game.economy["kill_reward_ratio"]
                    enemy.money = min(enemy.money + reward, enemy.money_cap)
                    continue
                if fighter.lifespan_left <= 0:
                    self.note(side.index, f"{fighter.spec.name} が寿命で退場")
                    continue
                survivors.append(fighter)
            side.fighters = survivors

        self.t += dt

    def finished(self) -> bool:
        return (self.t >= self.game.time_limit
                or any(s.base_hp <= 0 for s in self.sides))

    def run(self) -> "Result":
        while not self.finished():
            self.step()
        return Result.of(self)


@dataclass
class Result:
    winner: int | None          # 0 / 1 / None（引き分け）
    reason: str
    seconds: float
    base_hp: tuple[float, float]
    level: tuple[int, int]
    events: list[tuple[float, int, str]] = field(default_factory=list)

    @classmethod
    def of(cls, battle: Battle) -> "Result":
        a, b = battle.sides
        hp = (max(0.0, a.base_hp), max(0.0, b.base_hp))
        if hp[0] <= 0 or hp[1] <= 0:
            winner = 0 if hp[1] <= 0 else 1
            reason = "拠点撃破"
        else:
            full = battle.game.base_hp
            dealt = ((full - hp[1]) / full, (full - hp[0]) / full)
            if abs(dealt[0] - dealt[1]) < 1e-9:
                winner, reason = None, "時間切れ・与ダメージ同率"
            else:
                winner = 0 if dealt[0] > dealt[1] else 1
                reason = "時間切れ・与ダメージ割合"
        return cls(winner=winner, reason=reason, seconds=battle.t, base_hp=hp,
                   level=(a.level, b.level), events=battle.events)
