"""`data/*.json` を読み、そのまま使える形にする。

JSON の構造を知っているのはこのモジュールだけ。validate.py も battle.py も
ここを通すので、片方だけ直して食い違う、という事故が起きない。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@dataclass(frozen=True)
class Unit:
    id: str
    name: str
    tier: str
    cost: int
    cooldown_sec: float
    hp: int
    attack: int
    attack_interval_sec: float
    attack_windup_sec: float
    attack_band_m: tuple[float, float]
    pierce: int
    knockback: int
    speed_mps: float
    siege_mult: float
    anti_wall_mult: float = 1.0
    # 種族。戦闘の数字には効かないが、**特性（同胞・連携）がここを見る**ので、
    # 編成を種族で固めるか役割で散らすかが択になる。
    race: str = "王国軍"
    trait: str = ""             # 特性のid。触れるのは出撃コストだけ
    role: str = ""

    @property
    def near(self) -> float:
        """死角。ここより内側には攻撃が当たらない。"""
        return self.attack_band_m[0]

    @property
    def far(self) -> float:
        return self.attack_band_m[1]

    def is_ranged(self, threshold: float) -> bool:
        """遠距離か。奥が far_threshold_m を超えていれば遠距離。"""
        return self.far > threshold

    def is_rear_area(self, threshold: float, area_pierce: int) -> bool:
        """遠方範囲か。**遠くまで届く範囲攻撃には必ず死角がある** ので、
        「遠距離 かつ 範囲」はそのまま「死角持ち」を意味する。
        別のタグではなく、すでにある3つの数字の言い換え。
        """
        return self.is_ranged(threshold) and self.pierce >= area_pierce

    def is_wall(self, threshold: float) -> bool:
        """壁かどうかは対拠点倍率で決まる。拠点を割れないユニットが壁。

        別のタグを持たせない。「壁」という役割は、すでにある数字の
        言い換えでしかない。
        """
        return self.siege_mult <= threshold

    @property
    def dps(self) -> float:
        """攻撃力 ÷ 攻撃間隔。データには持たせず、必要なたびにここで出す。"""
        return self.attack / self.attack_interval_sec


@dataclass(frozen=True)
class CardEffect:
    scope: str          # own_units / enemy_units / own_deploy / enemy_economy
    stat: str           # attack / speed / attack_interval / knockback / cost / ...
    mult: float | None = None
    add: float | None = None


STAT_LABELS = {
    "attack": "攻撃力",
    "attack_interval": "攻撃間隔",
    "speed": "移動速度",
    "knockback": "ノックバック",
    "cost": "出撃コスト",
    "deploy_cooldown": "再出撃の待ち",
    "income": "収入",
}

SCOPE_LABELS = {
    "own_units": "自軍",
    "enemy_units": "敵軍",
    "own_deploy": "自分の出撃",
    "enemy_deploy": "敵の出撃",
    "own_economy": "自分の財布",
    "enemy_economy": "敵の財布",
}

# 数字がどっちに動くと何が起きるか。(stat, 上がるか) → 一言。
# ここが「わかりやすい解説」の実体で、カード側には持たせない ――
# 数字と説明を両方 data に書くと、必ずどちらかがズレる（DPS と同じ理由）。
STAT_MEANING = {
    ("attack", True): "殴りが強くなる",
    ("attack", False): "殴りが弱くなる",
    ("attack_interval", True): "手数が減る",
    ("attack_interval", False): "手数が増える",
    ("speed", True): "前線が上がる",
    ("speed", False): "足が止まる",
    ("knockback", True): "押し戻されやすくなる",
    ("knockback", False): "押し戻されにくくなる",
    ("cost", True): "出撃が高くつく",
    ("cost", False): "安く出せる",
    ("deploy_cooldown", True): "続けて出せなくなる",
    ("deploy_cooldown", False): "続けて出せる",
    ("income", True): "資金が速く貯まる",
    ("income", False): "資金が止まる",
}


@dataclass(frozen=True)
class Card:
    id: str
    name: str
    family: str
    target: str
    duration_sec: float
    cooldown_sec: float
    cast_sec: float
    apply: CardEffect
    cost: int = 0
    band: str = "軽"          # 軽 / 中 / 重。コストの帯であり、強さの帯でもある
    # 撃てる条件。自分の拠点がこの割合まで減っていないと撃てない。
    # None なら無条件。押し込まれている側だけが持てる手を作るための唯一の仕組み。
    base_hp_gate: float | None = None

    @property
    def gated(self) -> bool:
        return self.base_hp_gate is not None

    def change(self) -> str:
        """効果の数字を1行にする。「自軍の攻撃力 ×1.4」。"""
        stat = STAT_LABELS.get(self.apply.stat, self.apply.stat)
        who = SCOPE_LABELS.get(self.apply.scope, self.apply.scope)
        if self.apply.mult is not None:
            return f"{who}の{stat} ×{self.apply.mult:g}"
        return f"{who}の{stat} {self.apply.add:+g}"

    def meaning(self) -> str:
        """その数字が動くと何が起きるか。「手数が増える」。"""
        if self.apply.mult is not None:
            rises = self.apply.mult > 1.0
        else:
            rises = (self.apply.add or 0) > 0
        return STAT_MEANING.get((self.apply.stat, rises), "")

    def condition(self) -> str:
        """撃てる条件。無条件なら空。"""
        if self.base_hp_gate is None:
            return ""
        return f"自拠点 {self.base_hp_gate:.0%} 以下でだけ撃てる"

    def describe(self) -> str:
        """カードの説明文。data には書かず、毎回ここで組み立てる。"""
        parts = [f"{self.change()} を{self.duration_sec:g}秒"]
        meaning = self.meaning()
        if meaning:
            parts.append(f"―― {meaning}")
        condition = self.condition()
        if condition:
            parts.append(f"（{condition}）")
        return " ".join(parts)

    @property
    def uptime(self) -> float:
        """効いている時間の割合。持ち込み枠でどれだけ効かせ続けられるか。"""
        return self.duration_sec / self.cooldown_sec

    @property
    def upkeep(self) -> float:
        """撃ち続けた場合の毎秒あたりの資金。呪文の重さはこれで測る。

        コストが付いたので、占有率だけでは強さを測れなくなった。
        「効かせ続けるのに収入の何割を食うか」が新しい物差し。
        """
        return self.cost / self.cooldown_sec

    @property
    def power(self) -> float:
        """効果の大きさ。倍率のずれ×持続。ノックバック加算だけ別尺度。"""
        if self.apply.mult is not None:
            return abs(self.apply.mult - 1.0) * self.duration_sec
        return abs(self.apply.add or 0) * 2 * self.duration_sec / 10

    def rated_power(self, gate_bonus: float) -> float:
        """値段と釣り合っているかを見るときの大きさ。

        条件付きの札は、撃てないまま終わる試合があるぶんだけ効果を大きくしてよい。
        その差を引いてから帯に当てるので、条件付きだけが「同じ値段で強い」を
        名乗れて、しかも際限なくは強くならない。
        """
        return self.power - (gate_bonus if self.gated else 0.0)


@dataclass(frozen=True)
class Trump(Unit):
    """切り札。能力の項目はユニットとまったく同じで、寿命と召喚時間が増えるだけ。

    特別な仕組みを持たせないので、戦闘のコードはユニットと切り札を区別しない。
    """
    lifespan_sec: float = 0.0
    summon_sec: float = 0.0


@dataclass(frozen=True)
class Perk:
    id: str
    name: str
    category: str
    cost: int
    changes_flow: bool
    resolves_in: str
    visible_to_opponent: bool
    params: dict
    exclusive_with: tuple[str, ...] = ()
    note: str = ""


@dataclass(frozen=True)
class Avatar:
    id: str
    name: str
    concept: str
    look: str
    signature: str
    perks: tuple[str, ...]


# 特性の種類。**どれも出撃コストにしか効かない。**
# 戦闘中の数字に触れる種類をここに足し始めた瞬間、シミュレータが
# キャラごとの分岐だらけになって「何が効いたのか」が読めなくなる。
COST_MULT_WHEN_HURT = "cost_mult_when_hurt"
COST_MINUS_IF_LAST_SAME_RACE = "cost_minus_if_last_same_race"
COST_MINUS_PER_SAME_RACE_IN_ROSTER = "cost_minus_per_same_race_in_roster"

TRAIT_KINDS = {
    COST_MULT_WHEN_HURT,
    COST_MINUS_IF_LAST_SAME_RACE,
    COST_MINUS_PER_SAME_RACE_IN_ROSTER,
}


@dataclass(frozen=True)
class Trait:
    id: str
    name: str
    kind: str
    params: dict
    note: str = ""

    def describe(self) -> str:
        """特性の説明文。data には書かず、種類と数字から組み立てる。"""
        p = self.params
        if self.kind == COST_MULT_WHEN_HURT:
            return (f"自拠点が {p['base_hp_at_most']:.0%} 以下のあいだ、"
                    f"出撃コスト ×{p['mult']:g}")
        if self.kind == COST_MINUS_IF_LAST_SAME_RACE:
            return f"直前に出したのが同じ種族なら、出撃コスト −{p['amount']:g}"
        if self.kind == COST_MINUS_PER_SAME_RACE_IN_ROSTER:
            return f"編成の同じ種族1体につき、出撃コスト −{p['amount']:g}"
        return ""


@dataclass(frozen=True)
class GameData:
    units: dict[str, Unit]
    cards: dict[str, Card]
    trumps: dict[str, Trump]
    perks: dict[str, Perk]
    avatars: dict[str, Avatar]
    traits: dict[str, Trait]
    match: dict
    budget: dict
    trait_rules: dict

    # --- 試合設定への近道。生の辞書を各所で掘らないための入口 ---
    @property
    def lane_length(self) -> float:
        return self.match["field"]["length_m"]

    @property
    def base_hp(self) -> int:
        return self.match["avatar"]["hp"]

    @property
    def time_limit(self) -> float:
        return self.match["victory"]["time_limit_sec"]

    @property
    def economy(self) -> dict:
        return self.match["economy"]

    @property
    def levels(self) -> list[dict]:
        return self.match["economy"]["growth"]["levels"]

    @property
    def card_rules(self) -> dict:
        return self.match["cards"]

    @property
    def trump_rules(self) -> dict:
        return self.match["trump"]

    @property
    def readability(self) -> dict:
        return self.match["readability"]

    @property
    def combat(self) -> dict:
        return self.match["combat"]

    @property
    def roster_rules(self) -> dict:
        return self.match["roster"]

    @property
    def wall_threshold(self) -> float:
        return self.match["roster"]["wall_threshold"]

    @property
    def far_threshold(self) -> float:
        """ここを超えたら遠距離。"""
        return self.match["roster"]["far_threshold_m"]

    @property
    def area_pierce_min(self) -> int:
        """貫通がこれ以上なら範囲攻撃。"""
        return self.match["roster"]["area_pierce_min"]

    @property
    def max_reach(self) -> float:
        return self.match["roster"]["max_reach_m"]

    @property
    def min_types_per_match(self) -> int:
        """1試合に出せる種類の下限。これを割ると読み合いにならない。"""
        return self.match["roster"]["min_types_per_match"]

    @property
    def gate_power_bonus(self) -> float:
        return self.card_rules["gate_power_bonus"]

    @property
    def stock_slots(self) -> int:
        return self.card_rules["stock_slots"]

    @property
    def races(self) -> list[str]:
        return self.match["roster"]["races"]

    def trait_of(self, spec: Unit) -> Trait | None:
        return self.traits.get(spec.trait) if spec.trait else None

    def units_of_race(self, race: str) -> list[Unit]:
        return [u for u in self.units.values() if u.race == race]

    def rear_area_units(self) -> list[Unit]:
        """遠方範囲。死角を持つ遠距離の範囲攻撃。"""
        return [u for u in self.units.values()
                if u.is_rear_area(self.far_threshold, self.area_pierce_min)]

    def cards_in_band(self, band: str) -> list[Card]:
        return [c for c in self.cards.values() if c.band == band]

    def units_by_tier(self, tier: str) -> list[Unit]:
        return [u for u in self.units.values() if u.tier == tier]


def _read(name: str, data_dir: Path) -> dict:
    with open(data_dir / f"{name}.json", encoding="utf-8") as f:
        return json.load(f)


def load(data_dir: Path | str = DATA_DIR) -> GameData:
    data_dir = Path(data_dir)
    raw_units = _read("characters", data_dir)["characters"]
    raw_cards = _read("cards", data_dir)["cards"]
    raw_trumps = _read("trumps", data_dir)["trumps"]
    raw_perks = _read("perks", data_dir)
    raw_avatars = _read("avatars", data_dir)["avatars"]
    raw_traits = _read("traits", data_dir)
    match = _read("match", data_dir)

    units = {}
    for u in raw_units:
        units[u["id"]] = Unit(
            id=u["id"], name=u["name"], tier=u["tier"], cost=u["cost"],
            cooldown_sec=u["cooldown_sec"], hp=u["hp"], attack=u["attack"],
            attack_interval_sec=u["attack_interval_sec"],
            attack_windup_sec=u["attack_windup_sec"],
            attack_band_m=tuple(u["attack_band_m"]),
            pierce=u["pierce"], knockback=u["knockback"],
            speed_mps=u["speed_mps"], siege_mult=u["siege_mult"],
            anti_wall_mult=u["anti_wall_mult"], race=u.get("race", "王国軍"),
            trait=u.get("trait", ""), role=u.get("role", ""),
        )

    cards = {}
    for c in raw_cards:
        a = c["apply"]
        cards[c["id"]] = Card(
            id=c["id"], name=c["name"], family=c["family"], target=c["target"],
            duration_sec=c["duration_sec"], cooldown_sec=c["cooldown_sec"],
            cast_sec=c["cast_sec"], cost=c["cost"], band=c["band"],
            base_hp_gate=c.get("require", {}).get("own_base_hp_at_most"),
            apply=CardEffect(scope=a["scope"], stat=a["stat"],
                             mult=a.get("mult"), add=a.get("add")),
        )

    trumps = {}
    for t in raw_trumps:
        trumps[t["id"]] = Trump(
            id=t["id"], name=t["name"], tier="T", cost=t["cost"],
            cooldown_sec=0.0, hp=t["hp"], attack=t["attack"],
            attack_interval_sec=t["attack_interval_sec"],
            attack_windup_sec=t["attack_windup_sec"],
            attack_band_m=tuple(t["attack_band_m"]),
            pierce=t["pierce"], knockback=t["knockback"],
            speed_mps=t["speed_mps"], siege_mult=t["siege_mult"],
            anti_wall_mult=t["anti_wall_mult"], race=t.get("race", "王国軍"),
            role=t.get("role", ""),
            lifespan_sec=t["lifespan_sec"], summon_sec=t["summon_sec"],
        )

    perks = {}
    for p in raw_perks["perks"]:
        perks[p["id"]] = Perk(
            id=p["id"], name=p["name"], category=p["category"], cost=p["cost"],
            changes_flow=p["changes_flow"], resolves_in=p["resolves_in"],
            visible_to_opponent=p["visible_to_opponent"], params=p["params"],
            exclusive_with=tuple(p.get("exclusive_with", ())),
            note=p.get("note", ""),
        )

    avatars = {a["id"]: Avatar(id=a["id"], name=a["name"], concept=a["concept"],
                               look=a.get("look", ""),
                               signature=a["signature"], perks=tuple(a["perks"]))
               for a in raw_avatars}

    traits = {t["id"]: Trait(id=t["id"], name=t["name"], kind=t["kind"],
                             params=t["params"], note=t.get("note", ""))
              for t in raw_traits["traits"]}

    return GameData(units=units, cards=cards, trumps=trumps, perks=perks,
                    avatars=avatars, traits=traits, match=match,
                    budget=raw_perks["budget"],
                    trait_rules=raw_traits["rules"])
