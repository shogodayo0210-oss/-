#!/usr/bin/env python3
"""作画の依頼書を書き出す。**そのまま ChatGPT に貼れる形**で。

依頼書は2つの出どころを合わせて作る。

  `data/characters.json`  体格・得物の長さ・砲身の向き・前傾の深さ ――
                          **形が数字から決まる**ところ（art/README.md 3章）
  `art/looks.json`        数字から決まらない見た目 ―― 何を着ていて、
                          何を持っていて、どんな姿勢か

**両方に同じことを書かない。** 数字が動いたら依頼書も動く、という関係にして
おかないと、絵と中身がズレる（DPS を data に持たせないのと同じ理由）。

    python3 game/tools/art_brief.py            # game/art/BRIEF.md
    python3 game/tools/art_brief.py --id oni   # 1体だけ標準出力に
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from game.engine.data import GameData, Unit, load  # noqa: E402

ART = ROOT / "game" / "art"
OUT = ART / "BRIEF.md"


def looks() -> dict:
    with open(ART / "looks.json", encoding="utf-8") as f:
        return json.load(f)


def palette() -> dict:
    with open(ART / "palette.json", encoding="utf-8") as f:
        return json.load(f)["races"]


class Scale:
    """ロースター全体の中での位置。「大きい／速い」は相対でしか言えない。"""

    def __init__(self, game: GameData):
        units = list(game.units.values())
        self.cost = sorted(u.cost for u in units)
        self.hp = sorted(u.hp for u in units)
        self.speed = sorted(u.speed_mps for u in units)
        self.dps = sorted(u.dps for u in units)
        self.speed_median = statistics.median(self.speed)

    @staticmethod
    def _rank(values: list[float], value: float) -> float:
        below = sum(1 for v in values if v < value)
        return below / max(len(values) - 1, 1)

    def word(self, values: list[float], value: float) -> str:
        r = self._rank(values, value)
        if r >= 0.85:
            return "最上位"
        if r >= 0.6:
            return "上位"
        if r >= 0.4:
            return "中位"
        if r >= 0.15:
            return "下位"
        return "最下位"


def shape_rules(spec: Unit, game: GameData, scale: Scale) -> list[str]:
    """**数字から決まる形。** art/README.md 3章の規約をそのまま文にする。"""
    rules = []
    rules.append(
        f"大きさ：{scale.word(scale.cost, spec.cost)}"
        f"（コスト {spec.cost} / 全体 {scale.cost[0]}〜{scale.cost[-1]}）。"
        "高いほどキャンバスを埋める")

    if spec.is_wall(game.wall_threshold):
        rules.append(
            f"**壁**（対拠点 {spec.siege_mult}）。横に広く低く、前に盾を構える。"
            "拠点を割る道具は持たせない")
    if spec.near > 0:
        rules.append(
            f"**死角 {spec.near:.0f}m を持つ遠方範囲。** 得物は上を向く"
            "（砲身・投擲・掲げた杖）。足元は撃てない、が形で分かること")
    elif spec.is_ranged(game.far_threshold):
        rules.append(
            f"**遠距離**（射程 {spec.far:.0f}m）。細く高く、得物が長い。"
            "長さは射程に比例させる（全体の最長は80m）")
    else:
        rules.append(f"**接近戦〜前線**（射程 {spec.far:.0f}m）。得物は短い")

    if spec.pierce >= game.area_pierce_min:
        rules.append(
            f"範囲攻撃（{spec.pierce}体まで巻き込む）。刃・爆風・火が"
            "**横に広がる**形にする")
    else:
        rules.append("単体攻撃。得物は点で当たる形（穂先・刃先・矢）")

    if spec.speed_mps > scale.speed_median:
        rules.append(
            f"速い（{spec.speed_mps} / 中央値 {scale.speed_median:.0f}）。"
            "**前傾**させ、重心を前足に乗せる")
    elif spec.speed_mps <= scale.speed[2]:
        rules.append(f"最も遅い部類（{spec.speed_mps}）。重心が低く、動く気配が無い")

    if spec.siege_mult >= 1.3:
        rules.append(f"対拠点 {spec.siege_mult}。**背中か手に攻城具**を足す")
    if spec.anti_wall_mult > 1.5:
        rules.append(f"対壁 {spec.anti_wall_mult}。**刃を厚く** ―― 壁を割る道具に見せる")
    if spec.knockback <= 1:
        rules.append("後退しない（ノックバック1）。両足で踏ん張った姿勢")
    elif spec.knockback >= 4:
        rules.append(f"よく押し戻される（ノックバック{spec.knockback}）。装甲は薄く")

    if spec.hp >= scale.hp[-6]:
        rules.append(f"体力が最上位（{spec.hp}）。厚み・装甲・質量で見せる")
    elif spec.hp <= scale.hp[5]:
        rules.append(f"体力が最下位（{spec.hp}）。**紙に見せる** ―― 装甲を描かない")
    if spec.dps >= scale.dps[-4]:
        rules.append(f"DPSが最上位（{spec.dps:.0f}）。得物を凶悪に")

    return rules


def prompt_for(spec: Unit, game: GameData, scale: Scale, look: dict,
               style: dict, races: dict, ramp: dict) -> str:
    """ChatGPT にそのまま貼る1文。"""
    race = races[spec.race]
    colors = ramp[spec.race]
    size = 96 if getattr(spec, "lifespan_sec", 0) else 48
    lines = [
        f"{size}×{size}ドットのドット絵を1枚。{style['common']}",
        "",
        f"【キャラ】{spec.name}（{spec.race}）。{look['look']}。",
        f"持ち物は{look['weapon']}。{look['pose']}。",
        "",
        f"【{spec.race}の記号】{race['identity']}。"
        + "／".join(race["motifs"]) + f"。{race['silhouette']}。",
        "",
        "【色】"
        + "・".join(f"{k}={colors[k]}" for k in
                   ("outline", "shadow", "base", "light", "accent", "dark_accent")),
        "",
        "【シルエットで必ず伝えること】",
    ]
    lines += [f"- {r}" for r in shape_rules(spec, game, scale)]
    lines += ["", f"【描かないもの】{style['negative']}"]
    return "\n".join(lines)


def section(spec: Unit, game: GameData, scale: Scale, look: dict,
            style: dict, races: dict, ramp: dict) -> str:
    kind = "切り札" if getattr(spec, "lifespan_sec", 0) else f"コスト{spec.cost}"
    head = f"### {spec.name}（`{spec.id}`）— {spec.race} / {kind}\n"
    body = [head, f"> {spec.role}\n"]
    body.append("```text")
    body.append(prompt_for(spec, game, scale, look, style, races, ramp))
    body.append("```\n")
    return "\n".join(body)


def build(game: GameData) -> str:
    art = looks()
    ramp = palette()
    style, races = art["style"], art["races"]
    scale = Scale(game)

    out = [
        "# 作画依頼書（自動生成 — 直接編集しない）",
        "",
        "`python3 game/tools/art_brief.py` が "
        "`data/characters.json` ＋ `data/trumps.json` ＋ `art/looks.json` "
        "＋ `art/palette.json` から書き出す。**数字を動かしたら生成し直す。**",
        "",
        "各キャラの ```text``` の中を、そのまま ChatGPT に貼れば1枚返ってくる。",
        "まずは1体につき待機の1コマだけ。採用が決まってから13枚に展開する。",
        "",
        f"> {style['note']}",
        "",
        "---",
        "",
        "## 0. 全体に効く指定",
        "",
        f"**共通**：{style['common']}",
        "",
        f"**描かないもの**：{style['negative']}",
        "",
        "## 1. 種族の見分け",
        "",
        "種族は**編成の材料**（設計書2.9）なので、"
        "遠くからでも一目で分かる必要がある。",
        "",
        "| 種族 | 何者か | 記号 | シルエット | 色 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name, info in races.items():
        c = ramp[name]
        out.append(f"| **{name}** | {info['identity']} | "
                   f"{'／'.join(info['motifs'])} | {info['silhouette']} | "
                   f"`{c['base']}` ＋ `{c['accent']}` |")

    out += ["", "## 2. 背景", "", "**決まりごと**", ""]
    out += [f"- {rule}" for rule in art["backgrounds"]["_rules"]]
    out += ["", "**案**", ""]
    for bg in art["backgrounds"]["list"]:
        out += [f"### {bg['name']}（`{bg['id']}`）", "",
                f"いつ使うか：{bg['when']}", "", "```text",
                f"横長の背景を1枚。{bg['prompt']}。"
                "ドット絵。3層（遠景・中景・地面）に分けて、それぞれ別レイヤーで。"
                "**中央の帯は彩度と明度を落とす** ―― ここに40体のキャラが並ぶので、"
                "背景が主張すると誰が誰だか分からなくなる。"
                "地面は水平で、20mごとの目盛りを重ねられるように模様を控える。"
                "左右の端はキャラの拠点が立つので平らに空ける。"
                "文字とロゴは入れない",
                "```", ""]

    out += ["## 3. ユニット", ""]
    by_race: dict[str, list[Unit]] = {}
    for unit in game.units.values():
        by_race.setdefault(unit.race, []).append(unit)
    for race in races:
        members = sorted(by_race.get(race, []), key=lambda u: u.cost)
        if not members:
            continue
        out += [f"## {race}（{len(members)}体）", ""]
        for unit in members:
            look = art["units"].get(unit.id)
            if look is None:
                out += [f"### {unit.name}（`{unit.id}`）", "",
                        "**looks.json に見た目が無い。** 足してから生成し直す。", ""]
                continue
            out.append(section(unit, game, scale, look, style, races, ramp))

    out += ["## 切り札（96×96）", ""]
    for trump in game.trumps.values():
        look = art["units"].get(trump.id)
        if look is None:
            continue
        out.append(section(trump, game, scale, look, style, races, ramp))

    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="art_brief")
    parser.add_argument("--id", help="1体だけ標準出力に出す")
    args = parser.parse_args(argv)

    game = load()
    art = looks()
    ramp = palette()
    scale = Scale(game)

    if args.id:
        spec = game.units.get(args.id) or game.trumps.get(args.id)
        if spec is None:
            print(f"知らないid: {args.id}", file=sys.stderr)
            return 2
        look = art["units"].get(spec.id)
        if look is None:
            print(f"{args.id} の見た目が looks.json に無い", file=sys.stderr)
            return 2
        print(prompt_for(spec, game, scale, look, art["style"],
                         art["races"], ramp))
        return 0

    text = build(game)
    OUT.write_text(text, encoding="utf-8")
    missing = [u.id for u in
               list(game.units.values()) + list(game.trumps.values())
               if u.id not in art["units"]]
    print(f"{OUT.relative_to(ROOT)} — {len(text) // 1024} KB / "
          f"{len(game.units) + len(game.trumps)}体")
    if missing:
        print("見た目が未記入: " + "・".join(missing))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
