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

from .data import (COST_MINUS_IF_LAST_SAME_RACE,
                   COST_MINUS_PER_SAME_RACE_IN_ROSTER, COST_MULT_WHEN_HURT,
                   Card, GameData, Trump, Unit)
from .draft import stock_sequence

# 位置の比較に使う許容差。左右のユニットは逆向きに動くので、同じ地点でも
# 浮動小数点の下位桁が一致しない。素で比較すると「前の味方に詰まるか」の
# 判定が 1e-16 の差でひっくり返り、左右対称の試合が割れる。
EPS = 1e-6


# --------------------------------------------------------------- 決定論的な乱数
# **Python と JS で1ビットも違わない乱数が要る。** 呪文ストックの並びは
# Python 側で引いて焼き込めば済んだが（`build_web.py`）、雷は試合の途中で
# 引くので焼き込めない。Mersenne Twister を移植するのは危ないので、
# 32ビット整数だけで書ける小さいものを両方に置く。
#
# JS 側は `Math.imul` と `>>> 0` で同じ32ビット演算になる。


def seed32(text: str) -> int:
    """文字列から32ビットの種を作る（FNV-1a）。"""
    h = 2166136261
    for byte in text.encode("utf-8"):
        h = ((h ^ byte) * 16777619) & 0xFFFFFFFF
    return h or 1


class Rng:
    """xorshift32。**同じ種からは必ず同じ並び** ―― 試合の再現に要る。"""

    def __init__(self, seed: int):
        self.state = seed & 0xFFFFFFFF or 1

    def next(self) -> int:
        x = self.state
        x = (x ^ (x << 13)) & 0xFFFFFFFF
        x ^= x >> 17
        x = (x ^ (x << 5)) & 0xFFFFFFFF
        self.state = x
        return x

    def unit(self) -> float:
        """0以上1未満。倍精度なので JS と同じ値になる。"""
        return self.next() / 4294967296.0


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


def storm_seed(loadout: "Loadout") -> str:
    """雷の種にする、編成の名前。

    **持ち込んだものだけで作る。** 最初は `stock_seed` だけを使っていたが、
    あれは呪文の並びを焼き込むための欄で、移植側では落ちることがある ――
    `conform.py` が「181秒あたりから食い違う」と鳴って気づいた。
    落ちうる欄ひとつに雷の位置を預けると、Python と JS で違う場所に落ちる。
    """
    return (f"{loadout.avatar}:{','.join(loadout.roster)}:"
            f"{loadout.brought}:{loadout.trump}:{loadout.stock_seed}")


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
    # **種族呪文。** 空なら全軍。種族名が入っていれば、その種族のユニットに
    # だけ効く ―― 財布や出撃コストのような全軍ぶんの値には一切かからない。
    race: str = ""


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
    # **後隙。** 攻撃が当たった直後の、殴られてよい時間。`recover_left` は
    # 「次の一手までの残り」（攻撃間隔の余り）で、こちらはそのうち
    # **被弾が増える前半**だけ。分けてあるのは攻撃間隔＝DPSを動かさずに
    # 後隙の長さだけを設計値にするため。
    exposed_left: float = 0.0
    stun_left: float = 0.0
    knockbacks_done: int = 0
    summon_left: float = 0.0
    lifespan_left: float = math.inf

    @property
    def alive(self) -> bool:
        return self.hp > 0

    @property
    def exposed(self) -> bool:
        """後隙の最中か。ここで殴ると余分に通る。"""
        return self.exposed_left > 0

    @property
    def ready(self) -> bool:
        """召喚演出が終わって、実際に戦える状態か。"""
        return self.summon_left <= 0

    @property
    def hittable(self) -> bool:
        """**的になるか。** ノックバック中（硬直中）は判定が消える。

        消えるのは *当たり判定そのもの* なので、効くのは2つ。

          1. **殴られない。** 下がっている最中に追い討ちが入らない。
             回数の多いキャラ（双剣・狂戦士・亡霊将＝4回）は、
             以前は下がるたびに無防備な0.4秒を差し出していた。
          2. **すり抜けられる。** 敵は「帯に敵が入ったら止まって殴る」で
             立ち止まるので、的が消えれば**止まらずに前へ通る**。
             押し戻した相手の体を突き抜けて前線が進む。

        味方どうしはもともと重なれるので、ここでいう「すり抜け」は
        場所の取り合いではなく、**足を止めさせるかどうか**の話。
        """
        return self.alive and self.ready and self.stun_left <= 0

    def band(self, speed_mult: float = 1.0) -> tuple[float, float]:
        """世界座標での**届く範囲**。向きで反転する。

        前線起点（`spread_m` > 0）のユニットでも、まずここに敵が入らないと
        始まらない ―― 当たる帯そのものは `Battle.strike_band` が出す。
        """
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
        # 拠点に打ち込まれた攻城の待ち行列。**取り出す速さだけが上限で、
        # 一発の大きさは削らない** ―― 10秒に1度しか振らない攻城櫓（対拠点1.9）が
        # tickの粒に切り落とされないようにするため。`Battle.apply_base_damage`。
        self.siege_backlog = 0.0
        self.level = 1
        self.money = float(game.economy["start"])
        # 資金は連続では増えない。**何秒かごとに +2〜6** という刻みで貯まる。
        # 棒が滑らかに伸びるのではなく段で上がるので、「あと何回ぶんで出せる」が
        # 目で数えられる（コストが整数なのはそのため）。
        # 素の間隔を使う ―― この時点ではまだ効果がひとつも乗っていない。
        self.income_left = float(self.level_row["income_every_sec"])

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
        # **呪文は1試合に3回まで**（持ち込み・ストックの合計）。資金と
        # クールタイムだけで縛っていた頃は、撃てるときに撃つのが常に正解で
        # *いつ撃つか*が択になっていなかった。切り札（1試合1回）とは別枠。
        self.casts_left = game.casts_per_match
        self.deploy_lock_left = 0.0
        self.upgrading_left = 0.0

        # 特性が見るもの。**特性が触れるのは出撃コストだけ** なので、
        # 戦闘の側にはこの2つ以外の入口が無い。
        self.last_race: str | None = None      # 直前に出したユニットの種族
        self.min_deploy_cost = game.trait_rules["min_deploy_cost"]
        # 編成の中の同種族の数は試合中変わらないので、ここで数えておく。
        self.kin: dict[str, int] = {}
        for uid in loadout.roster:
            spec = game.units[uid]
            self.kin[uid] = sum(1 for other in loadout.roster
                                if other != uid
                                and game.units[other].race == spec.race)
        # 種族呪文が見るのはこちら ―― 編成にその種族が何体入っているか。
        self.race_count: dict[str, int] = {}
        for uid in loadout.roster:
            race = game.units[uid].race
            self.race_count[race] = self.race_count.get(race, 0) + 1

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

    def unlocked(self, card: Card) -> bool:
        """拠点の傷が条件の札か。傷んでいなければ、資金があっても撃てない。

        **押し込まれている側だけが持てる手。** 先に前線を上げた側がそのまま
        勝ち切るのを、押されている側の手数で止めるための唯一の仕組み
        （設計書5.4）。相手の拠点を削れば削るほど、相手の札が増える。
        """
        gate = card.base_hp_gate
        if gate is not None and self.base_hp > self.game.base_hp * gate:
            return False
        # **種族呪文。** 編成にその種族が足りていなければ、資金があっても撃てない。
        if card.race_locked:
            return self.race_count.get(card.race, 0) >= card.race_min
        return True

    def castable(self, source: tuple[str, int]) -> bool:
        """いま撃てるか。回数・資金・詠唱中・共通CD・育成中・個別CD・解禁。"""
        if self.casts_left <= 0:          # 1試合3回を使い切った
            return False
        if self.casting is not None or self.gcd_left > 0 or self.busy:
            return False
        if source[0] == "brought" and self.brought_cd > 0:
            return False
        card = self.card_of(source)
        return (card is not None and self.money >= card.cost
                and self.unlocked(card))

    def sources(self) -> list[tuple[str, int]]:
        return [("brought", 0)] + [("stock", i) for i in range(len(self.stock))]

    # ------------------------------------------------------------------ 特典
    def _perk_param(self, perk_id: str, key: str, default):
        if perk_id not in self.perks:
            return default
        return self.game.perks[perk_id].params.get(key, default)

    # ------------------------------------------------------------------ 効果
    def stat(self, name: str, base: float, race: str | None = None) -> float:
        """かかっている効果を掛けたあとの値。掛けてから足す。

        `race` を渡すとユニット1体ぶんの値になる ―― **種族呪文**はその種族に
        だけ効くので、全軍ぶん（資金・出撃コスト・再出撃）とは分けて出す。
        渡さなければ種族付きの効果は素通しになる。
        """
        value = base
        for e in self.effects:
            if e.stat != name:
                continue
            if e.race and e.race != race:
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
    def income_amount(self) -> float:
        return self.level_row["income_amount"]

    @property
    def income_every(self) -> float:
        """次に資金が入るまでの秒数。増収などのカードはここを縮める。"""
        return self.level_row["income_every_sec"] / max(self.stat("income", 1.0), 1e-6)

    @property
    def income(self) -> float:
        """表示と検算のための実効値（毎秒いくら）。刻みの実体は上の2つ。"""
        return self.income_amount / self.income_every

    def tick_income(self, dt: float) -> bool:
        """時間を進めて、刻みが来ていれば資金を足す。上限は超えない。"""
        self.income_left -= dt
        if self.income_left > 0:
            return False
        self.money = min(self.money + self.income_amount, self.money_cap)
        self.income_left += self.income_every
        return True

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
        # 刻みが速くなるので、次の1回までを新しい間隔で測り直す
        self.income_left = min(self.income_left, self.income_every)

    def unit_cost(self, spec: Unit) -> float:
        """いま出すのに払う額。素の値段 → 特性 → カードの倍率、の順。

        特性を先に当ててからカードを掛けるのは、「同胞で安くしたうえで
        徴発を重ねる」が読みやすいから。逆順だと、割引がどこから来たのかが
        画面の数字から追えなくなる。
        """
        base = float(spec.cost)
        trait = self.game.trait_of(spec)
        if trait is not None:
            params = trait.params
            if trait.kind == COST_MINUS_PER_SAME_RACE_IN_ROSTER:
                base -= params["amount"] * self.kin.get(spec.id, 0)
            elif trait.kind == COST_MINUS_IF_LAST_SAME_RACE:
                if self.last_race == spec.race:
                    base -= params["amount"]
            elif trait.kind == COST_MULT_WHEN_HURT:
                if self.base_hp <= self.game.base_hp * params["base_hp_at_most"]:
                    base *= params["mult"]
        value = self.stat("cost", base)
        # 資金のマス目と同じ整数で読めること。半端は切り上げる。
        return max(float(self.min_deploy_cost), math.ceil(value - 1e-9))

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
        self.kb_stun = game.combat["knockback_stun_sec"]
        self.siege_cap = game.combat["siege_cap_dps"]
        self.recover_mult = game.combat["recover_damage_mult"]
        self.max_units = game.match["field"]["max_units_per_side"]
        self.t = 0.0
        self.drops = list(game.economy.get("milestones", []))
        self._next_drop = 0
        # そのtickの世界の見え方。全員が同じ盤面を見て動くので、
        # 「先に処理された側が先に殴れる」という順番の有利が出ない。
        self._snap: list[list[tuple[float, Fighter]]] = [[], []]
        self._hittable: list[list[tuple[float, Fighter]]] = [[], []]
        self._damage: list[tuple[Fighter, float]] = []
        self._base_damage: list[tuple[Side, float]] = []
        self.events: list[tuple[float, int, str]] = []
        self.verbose = verbose

        # 画面のための直近イベント。**シミュレーションの結果ではなく、
        # 見せ方の都合だけで持っている** ―― だから conform.py の指紋には
        # 入れない（数字の一致試験にノイズを足すだけになる）。数tick分だけ
        # 覚えておいて、古いものは step() の最後で捨てる（RECENT_SEC）。
        self.base_hits: list[tuple[float, int, float, bool]] = []   # 拠点への1発
        self.level_ups: list[tuple[float, int, int]] = []           # 財布の育成完了
        self.cast_effects: list[tuple[float, int, bool]] = []       # 呪文の発動

        # ── サドンデスの雷 ───────────────────────────────────
        # 3分を過ぎたらレーンのどこかに落ちる。落ちた範囲のユニットは
        # 敵味方の区別なく必ず倒れる ―― 前線が固まって動かなくなった盤面を、
        # 外から壊すための仕組み（設計書1.2）。
        #
        # 種は両者の編成から作るので、**同じ試合は必ず同じところに落ちる**。
        bolt = game.sudden_death
        self.storm_at = game.time_limit
        self.storm_every = bolt["every_sec"]
        self.storm_radius = float(bolt["radius_m"])
        self.storm_growth = bolt["radius_growth_m"]
        self.storm_radius_max = float(bolt["radius_max_m"])
        self.storm_warn = bolt["warn_sec"]
        self.rng = Rng(seed32(storm_seed(a) + "|" + storm_seed(b) + "|storm"))
        self.bolts_fallen = 0
        # 予告中の雷。(落ちる時刻, 位置, 半径)。空なら何も来ていない。
        self.pending: list[tuple[float, float, float]] = []
        self._next_bolt = self.storm_at

    RECENT_SEC = 3.0   # base_hits/level_ups/cast_effects を何秒分だけ覚えておくか

    # ------------------------------------------------------------------ 記録
    def note(self, side: int, text: str) -> None:
        self.events.append((self.t, side, text))
        if self.verbose:
            print(f"[{self.t:6.2f}] P{side + 1} {text}")

    def _prune_recent(self) -> None:
        cutoff = self.t - self.RECENT_SEC
        self.base_hits = [h for h in self.base_hits if h[0] >= cutoff]
        self.level_ups = [h for h in self.level_ups if h[0] >= cutoff]
        self.cast_effects = [h for h in self.cast_effects if h[0] >= cutoff]

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
        side.last_race = spec.race          # 「連携」が次に見るのはこれ
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
        # 回数も詠唱に入った時点で減る。見切られても戻らない ―― 資金と同じ。
        side.casts_left -= 1

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
                  f"{card.name} を詠唱（{where}・{card.cost} / "
                  f"{side.cast_left:.2f}秒・残り{side.casts_left}回）")
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

        own = card.apply.scope.startswith("own")
        target = side if own else enemy
        # 種族呪文は、その種族のユニットにだけ乗る（`Side.stat` が絞る）。
        target.add_effect(Effect(stat=card.apply.stat, mult=card.apply.mult,
                                 add=card.apply.add,
                                 until=self.t + card.duration_sec, source=card.id,
                                 race=card.race))
        # own_* は自分を強くする＝バフ、enemy_* は相手を弱くする＝デバフ。
        # data/cards.json はこの2つしか無いので、scope からそのまま出せる。
        self.cast_effects.append((self.t, target.index, own))
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
        # **的の一覧は別に持つ。** ノックバック中は判定が消えるので
        # （`Fighter.hittable`）、殴る側から見ると居ないのと同じ ――
        # 追い討ちが入らず、足も止まらない。
        # 場に何体居るか（`live`）とは別の数え方なので、リストを分けてある。
        self._hittable = [
            [pair for pair in rows if pair[1].hittable] for rows in self._snap
        ]

    def live(self, index: int) -> list[Fighter]:
        """そのtickの頭で場に居た側のユニット。方針もここを見る。"""
        return [f for _, f in self._snap[index]]

    def _rows_between(self, side: int, lo: float, hi: float):
        """帯の中に居る**的**。ノックバック中の者はここに入らない。"""
        rows = self._hittable[side]
        xs = [x for x, _ in rows]
        return rows[bisect_left(xs, lo - EPS):bisect_right(xs, hi + EPS)]

    def strike_band(self, fighter: Fighter) -> tuple[float, float]:
        """**実際に当たる帯。** 普通は届く範囲そのもの。

        `spread_m` を持つユニットだけ違う ―― 届く範囲の中にいる
        **敵の一番手前**を起点に、そこから奥へ窓のぶんだけを叩く。
        「相手の最前列から少し奥まで」という形で、*安い1体を前に置いて
        全部止める*が通らなくなる（壁ごと後ろの列を巻き込むので）。

        窓は射程の40%以下（validate.py）。盤面を薄く塗る道具ではなく、
        **前線の一点を深く抜く**道具なので、外れたところは無傷で残る。
        """
        lo, hi = fighter.band()
        if fighter.spec.spread_m <= 0:
            return lo, hi
        rows = self._rows_between(1 - fighter.side, lo, hi)
        if not rows:
            return lo, hi                 # 誰も居ないので拠点だけが的
        # 一番手前 ＝ 自分に近いほう。向きで端が入れ替わる。
        head = rows[0][0] if fighter.facing > 0 else rows[-1][0]
        width = fighter.spec.spread_m
        if fighter.facing > 0:
            return head, min(hi, head + width)
        return max(lo, head - width), head

    def targets_in_band(self, fighter: Fighter) -> list[Fighter]:
        lo, hi = self.strike_band(fighter)
        found = list(self._rows_between(1 - fighter.side, lo, hi))
        found.sort(key=lambda pair: abs(pair[0] - fighter.x))
        return [f for _, f in found]

    def base_in_band(self, fighter: Fighter) -> bool:
        lo, hi = self.strike_band(fighter)
        return lo - EPS <= self.sides[1 - fighter.side].base_x <= hi + EPS

    def apply_damage(self, victim: Fighter, amount: float) -> None:
        side = self.sides[victim.side]
        # **後隙に入った打撃は余分に通る。** 大技を振り切った直後が一番痛い、
        # という形にして、読める大振り（発生0.6秒以上）に対する答えを
        # 「避ける」から「差し込む」に変える。
        if victim.exposed:
            amount *= self.recover_mult
        victim.hp -= amount
        if victim.hp <= 0:
            return

        kb = side.stat("knockback", victim.spec.knockback, victim.spec.race)
        if kb < 1:                                    # 堅陣：後退しなくなる
            return
        # 体力を kb 個に割った区切りを跨いだら後退する。
        #
        # **一撃で2つ跨いでも下がるのは1回だけ。** 区切りは2つ消費される。
        # これは仕様 ―― 同じ総ダメージなら手数のほうが押し戻せるので、
        # 一撃の重さは「削る力」、手数は「押す力」と役割が割れる。
        # そのうえ大技は相手の後退の残り回数を先に食うので、撃ち込むほど
        # 相手は踏みとどまる。段数ぶん下げると大技1発で40m飛んで、
        # 目で追えなくなる。
        segment = victim.spec.hp / kb
        crossed = int((victim.spec.hp - victim.hp) // segment)
        if crossed > victim.knockbacks_done:
            victim.knockbacks_done = crossed
            victim.x -= victim.facing * self.kb_distance
            victim.x = max(0.0, min(self.game.lane_length, victim.x))
            victim.stun_left = self.kb_stun
            victim.windup_left = 0.0

    def apply_base_damage(self, dt: float) -> None:
        """攻城を、**攻城口の上限の速さで**拠点に入れる。

        帯が拠点に届いた者は全員が削る。ただし削れる速さは
        `combat.siege_cap_dps` で止まる ―― 取り付ける口が詰まるので、
        20体を寄せても数体ぶんより速くはならない。

        上限は**待ち行列**で効かせる。tickごとに切り落とすと、一発が重い
        攻城（攻城櫓 1.9、10秒に1度の大振り）だけが不当に損をして、
        手数の多い者が得をする ―― 「対拠点倍率がそのまま効く」が壊れる。
        積んでから一定の速さで取り出せば、1体ぶんの攻城は遅れて全部入り、
        寄せすぎたぶんだけが（1秒ぶんの行列を超えて）捨てられる。

        上限が無かった頃は、前線が破れた瞬間に17体が一斉に拠点を捉えて
        毎秒11700が入り、拠点HP 10000 は1秒たらずで消えた（実測）。
        拠点は『無傷』か『0』しか取らず、**傷ついた拠点という状態が
        存在しなかった** ―― 自拠点の傷で解禁される札（背水・反攻・死守）も、
        背水の特性も、起死回生の特典も、届く前に試合が終わる。実測では
        解禁から決着までの猶予が2〜8秒しかなく、詠唱0.8秒＋効果8秒の札が
        入る余地が無かった。上限を置いたことで、拠点HP ÷ 上限 = 15秒が
        設計値になり、その15秒が『押し切られる側が押し返す時間』になる。
        """
        arrived = [0.0, 0.0]
        for side, amount in self._base_damage:
            arrived[side.index] += amount
        for side in self.sides:
            # 打ち込まれたぶんは待ち行列に積む。**tickの粒で切らない** ――
            # 切ると、一発が重い攻城（攻城櫓 1.9 など）だけが不当に損をする。
            # 積める上限は1秒ぶんなので、寄せすぎた打撃はそこで捨てられる。
            side.siege_backlog = min(side.siege_backlog + arrived[side.index],
                                     self.siege_cap)
            taken = min(side.siege_backlog, self.siege_cap * dt)
            side.siege_backlog -= taken
            side.base_hp -= taken

    def resolve_attack(self, fighter: Fighter) -> None:
        side = self.sides[fighter.side]
        enemy = self.enemy_of(side)
        power = side.stat("attack", fighter.spec.attack, fighter.spec.race)

        if enemy.parry_until >= self.t:
            return

        wall_line = self.game.wall_threshold

        # **帯が敵拠点に届いていれば、拠点には必ず当たる。** 拠点はユニットと
        # 貫通の枠を奪い合わない。
        #
        # 以前は拠点も「的の列」に混ぜて、近い順に貫通の数だけ当てていた。
        # そうすると貫通ぶんの壁が拠点の前に並んでいる限り拠点に一発も入らず、
        # **自陣に20体を固めた側は、どれだけ押し込まれても拠点が無傷のまま
        # 終わる**（実測：圧倒的に強い編成が兵卒と盾兵だけの相手に300秒かけて
        # 拠点0ダメージ、36試合すべて引き分け）。守り切る手が絶対になると、
        # 押し合いに勝つ意味そのものが消える。
        #
        # 分けたことで、対拠点倍率が全ユニットの生きた数字になった ――
        # 壁（0.3〜0.5）は届いても削れず、攻城櫓（1.9）は届けば速い。
        # 守る側の仕事は「拠点に届かせないこと」そのものになる。
        #
        # ここで積むのは1体ぶんの取り分。**合計に上限をかけるのは
        # `apply_base_damage`。** 帯が届いた全員が削るが、寄せた数だけ
        # 速くはならない。
        if self.base_in_band(fighter):
            dealt = power * fighter.spec.siege_mult
            self._base_damage.append((enemy, dealt))
            # 画面向け。壁（対拠点倍率が低いユニット）が殴った一撃だけ、
            # View 側が別扱いで灰色に見せる ―― 「これは削れない」が伝わるように。
            self.base_hits.append(
                (self.t, enemy.index, dealt, fighter.spec.is_wall(wall_line)))

        for victim in self.targets_in_band(fighter)[: fighter.spec.pierce]:
            bonus = (fighter.spec.anti_wall_mult
                     if victim.spec.is_wall(wall_line) else 1.0)
            self._damage.append((victim, power * bonus))

    def step_fighter(self, fighter: Fighter) -> None:
        side = self.sides[fighter.side]
        dt = self.tick

        # **後隙は実時間で抜ける。** ノックバックされようが気絶させられようが、
        # 振り切った直後の時間は同じだけ流れる ―― 状態で伸び縮みさせると、
        # 「押し戻して後隙を伸ばす」という読みようのない挙動が生まれる。
        if fighter.exposed_left > 0:
            fighter.exposed_left -= dt

        if fighter.summon_left > 0:
            fighter.summon_left -= dt
            return
        if fighter.stun_left > 0:
            fighter.stun_left -= dt
            return

        interval_mult = side.stat("attack_interval", 1.0, fighter.spec.race)
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
                # 後隙は「次の一手までの残り」の**前半だけ**。残りは構え直しで
                # そこはもう余分には入らない ―― こう分けると、攻撃間隔
                # （＝DPS）を一切動かさずに後隙の長さだけを設計値にできる。
                fighter.exposed_left = min(
                    fighter.spec.attack_recover_sec * interval_mult,
                    fighter.recover_left)
            return

        if self.targets_in_band(fighter) or self.base_in_band(fighter):
            fighter.windup_left = fighter.spec.attack_windup_sec * interval_mult
            return

        # **味方どうしは重ならないように詰まらない。** 進めるところまで進んで、
        # 敵が自分の帯に入ったところで止まる ―― にゃんこ大戦争と同じ形。
        #
        # 以前は「前の味方に隊列間隔ぶん詰まる」で並ばせていた。そちらだと、
        # 自陣に押し込まれた側の20体が数十mに詰まって身動きが取れなくなり、
        # 前の1体しか殴れない。実測で、圧倒的に強い編成が兵卒と盾兵だけの
        # 相手に300秒かけて拠点0ダメージ、36試合すべて引き分けになった。
        # 詰まりを外すと、**立ち位置は射程が決める** ―― 接近戦は接触点まで出て、
        # 遠距離はその手前で止まる。前線範囲・遠方範囲の設計はこれで成立する。
        speed = side.stat("speed", fighter.spec.speed_mps, fighter.spec.race)
        moved = fighter.x + fighter.facing * speed * dt
        fighter.x = max(0.0, min(self.game.lane_length, moved))

    # ------------------------------------------------------------------ 進行
    def step(self) -> None:
        dt = self.tick

        # 盤面の固定は判断より前。あとにすると、先に動いた側の出撃が
        # 同じtickの相手の判断に見えてしまい、後手だけが得をする。
        self.snapshot()

        # 時間の節目の配布。左右対称の試合が割れないよう、互角なら誰にも入らない。
        while (self._next_drop < len(self.drops)
               and self.t >= self.drops[self._next_drop]["at_sec"]):
            drop = self.drops[self._next_drop]
            self._next_drop += 1
            self.pay_drop(drop)

        for side in self.sides:
            side.tick_income(dt)
            side.effects = [e for e in side.effects if e.until > self.t]
            side.gcd_left = max(0.0, side.gcd_left - dt)
            side.deploy_lock_left = max(0.0, side.deploy_lock_left - dt)
            was_busy = side.upgrading_left > 0
            side.upgrading_left = max(0.0, side.upgrading_left - dt)
            if was_busy and side.upgrading_left <= 0:
                # 育成が終わった瞬間。level はもう上がっている
                # （育成が始まった時点で払い済み・レベルも即座に上がる ―― 4章）ので、
                # ここでは「使えるようになった」ことだけを伝える。
                self.level_ups.append((self.t, side.index, side.level))
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
        self.apply_base_damage(dt)

        self._prune_recent()

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

        # 雷は掃除のあと。倒れた者を二度数えないため。
        if self.sudden_death:
            self.step_storm()

        self.t += dt

    def advance_of(self, side: Side) -> float:
        """自陣からどれだけ前に出ているか。押し込んでいる側を決める物差し。"""
        return max((abs(f.x - side.base_x)
                    for f in side.fighters if f.alive and f.ready), default=0.0)

    def leader(self) -> Side | None:
        """いま押し込んでいる側。互角なら None。

        **試合の結果には効かない。** 資金がここに乗っていた頃（陣地ボーナス）は
        押している側がさらに有利になっていたので外した。いまは
        `tools/balance.py` が「序盤に押し込んでいた側がそのまま勝つか」を
        測るためだけに使う。
        """
        reach = [self.advance_of(s) for s in self.sides]
        if abs(reach[0] - reach[1]) <= EPS:
            return None
        return self.sides[0] if reach[0] > reach[1] else self.sides[1]

    def pay_drop(self, drop: dict) -> None:
        """節目の配布。**必ず両者に同額。**

        以前は「そのとき前線を押し込んでいる側だけ」に入る陣地ボーナスがあった。
        押している側にさらに資金が入る形なので、一度傾いた試合はそのまま傾き
        続ける ―― 「先に押し込んだ側の勝ち」を作っていた仕組みのひとつなので
        外した。序盤に安いユニットを出す理由は、配布ではなく
        「出さないと前線を取られて拠点を削られる」という盤面そのもので作る。
        """
        amount, at = drop["amount"], drop["at_sec"]
        for side in self.sides:
            side.money = min(side.money + amount, side.money_cap)
        self.note(0, f"{at:.0f}秒の配布 — 両者に +{amount}")

    def next_drop(self) -> tuple[float, int] | None:
        """次の配布（残り秒, 額）。画面で読ませるために要る。"""
        if self._next_drop >= len(self.drops):
            return None
        drop = self.drops[self._next_drop]
        return max(0.0, drop["at_sec"] - self.t), drop["amount"]

    @property
    def sudden_death(self) -> bool:
        """雷が降り始めているか。画面と方針が見る。"""
        return self.t >= self.storm_at

    def schedule_bolt(self) -> None:
        """次の雷の落ちる場所を決めて、予告に積む。

        **落ちる位置は先に見える**（`warn_sec`）。設計書7.5の
        「大きい一撃は必ず読める」を雷にも掛ける ―― 予告なしに全滅させる
        装置だと、読み合いではなく事故になる。
        """
        lane = self.game.lane_length
        where = self.rng.unit() * lane
        # 広がるが上限がある。上限なしで測ったら、半径がレーンを覆った時点で
        # **誰も敵拠点まで歩けなくなり**、900秒まで0対0のままだった ――
        # 全部を殺す雷は押し合いを壊すのではなく、前進そのものを禁止する。
        radius = min(self.storm_radius + self.storm_growth * self.bolts_fallen,
                     self.storm_radius_max)
        # **必ず対で落ちる。** 落ちる場所は乱数だが、鏡の位置にも同時に落ちる
        # （x と レーン長−x）。1発だけだと、どちら側の半分に落ちたかで
        # 有利不利がついた ―― 完全に同じ編成どうしの試合が引き分けにならなく
        # なった時点で気づいた（test_identical_sides_draw）。
        # 対にすると盤面の左右は釣り合ったまま、線だけが欠ける。
        self.pending.append((self.t + self.storm_warn, where, radius))
        self.pending.append((self.t + self.storm_warn, lane - where, radius))
        self.note(0, f"落雷の予兆 — {where:.0f}m と {lane - where:.0f}m"
                     f"（半径{radius:.0f}m・{self.storm_warn:g}秒後）")

    def strike(self, where: float, radius: float) -> None:
        """雷を落とす。**範囲内のユニットは敵味方の区別なく必ず倒れる。**

        体力も装甲もノックバックも関係ない ―― ここだけは「ダメージ」ではなく
        「取り除く」。押し合いを壊すのが仕事なので、耐えられては意味がない。
        拠点には落ちない（`hits_bases`）: 盤面を壊すのが仕事で、勝敗を決めるのは
        仕事ではない。
        """
        killed = [0, 0]
        for side in self.sides:
            for fighter in side.fighters:
                if fighter.alive and abs(fighter.x - where) <= radius + EPS:
                    fighter.hp = 0.0
                    killed[side.index] += 1
        self.bolts_fallen += 1
        self.note(0, f"落雷 — {where:.0f}m（半径{radius:.0f}m）"
                     f"P1 {killed[0]}体 / P2 {killed[1]}体")

    def step_storm(self) -> None:
        """雷の予告と着弾。tickの終わりに1回だけ。"""
        if self.t >= self._next_bolt:
            self.schedule_bolt()
            self._next_bolt += self.storm_every
        landed = [b for b in self.pending if self.t >= b[0]]
        if landed:
            self.pending = [b for b in self.pending if self.t < b[0]]
            for _, where, radius in landed:
                self.strike(where, radius)

    def finished(self) -> bool:
        """**時間では決めない。** 拠点が落ちるまで続く。

        `hard_stop` はシミュレータが止まらなくなるのを防ぐ安全弁で、
        勝敗の仕組みではない ―― 雷は落ちるたびに範囲が広がるので、
        実際にはそこへ達する前にどこかで線が壊れる。
        """
        return (self.t >= self.game.hard_stop
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
