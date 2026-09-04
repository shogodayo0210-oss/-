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
    role: str = ""

    @property
    def near(self) -> float:
        """死角。ここより内側には攻撃が当たらない。"""
        return self.attack_band_m[0]

    @property
    def far(self) -> float:
        return self.attack_band_m[1]

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


@dataclass(frozen=True)
class Card:
    id: str
    name: str
    family: str
    target: str
    duration_sec: float
    cooldown_sec: float
    cast_sec: float
    effect: str
    apply: CardEffect

    @property
    def uptime(self) -> float:
        """効いている時間の割合。コストが無いので、これが強さの物差し。"""
        return self.duration_sec / self.cooldown_sec


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
    signature: str
    perks: tuple[str, ...]


@dataclass(frozen=True)
class GameData:
    units: dict[str, Unit]
    cards: dict[str, Card]
    trumps: dict[str, Trump]
    perks: dict[str, Perk]
    avatars: dict[str, Avatar]
    match: dict
    budget: dict

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
    def wall_threshold(self) -> float:
        return self.match["roster"]["wall_threshold"]

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
            anti_wall_mult=u["anti_wall_mult"], role=u.get("role", ""),
        )

    cards = {}
    for c in raw_cards:
        a = c["apply"]
        cards[c["id"]] = Card(
            id=c["id"], name=c["name"], family=c["family"], target=c["target"],
            duration_sec=c["duration_sec"], cooldown_sec=c["cooldown_sec"],
            cast_sec=c["cast_sec"], effect=c["effect"],
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
            anti_wall_mult=t["anti_wall_mult"], role=t.get("role", ""),
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
                               signature=a["signature"], perks=tuple(a["perks"]))
               for a in raw_avatars}

    return GameData(units=units, cards=cards, trumps=trumps, perks=perks,
                    avatars=avatars, match=match, budget=raw_perks["budget"])
