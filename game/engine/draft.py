"""編成フェーズ。6種選択＋2種抽選と、その抽選が疑われないための仕組み。

設計書3章。両者がロックするまで相手の commit は開かないので、
相手の編成を見てから自分の乱数を回すことが構造的にできない。
"""

from __future__ import annotations

import hashlib
import random

from .data import GameData


def commit(chosen: tuple[str, ...], deck: tuple[str, ...], trump: str,
           nonce: str) -> str:
    """編成の commit。ロックまで開かない。"""
    payload = "|".join(["/".join(sorted(chosen)), "/".join(sorted(deck)),
                        trump, nonce])
    return hashlib.sha256(payload.encode()).hexdigest()


def match_seed(commit_a: str, commit_b: str, match_id: str) -> str:
    """両者の commit から導く共通シード。片側だけでは動かせない。"""
    return hashlib.sha256(f"{commit_a}{commit_b}{match_id}".encode()).hexdigest()


def _rng(seed: str, salt: str) -> random.Random:
    stream = hashlib.sha256(f"{seed}:{salt}".encode()).digest()
    return random.Random(int.from_bytes(stream, "big"))


def stock_sequence(game: GameData, seed: str, count: int) -> list[str]:
    """呪文ストックに流れてくる札の並び。

    軽い札ほど出やすい（`stock_weight`）。重い札は「引けたら大きい手が打てる」
    機会として現れる ―― 引けなかったから負ける、にはならないよう、
    重い札は自分の持ち込み枠で確保できる（設計書5章）。

    種から決まるので、同じ試合は何度回しても同じ並びになる。
    """
    rng = _rng(seed, "stock")
    weights = game.card_rules["stock_weight"]
    pool = list(game.cards.values())
    chances = [weights.get(c.band, 1) for c in pool]
    return [rng.choices(pool, weights=chances)[0].id for _ in range(count)]


def pick_template(game: GameData, seed: str) -> list[str]:
    """その試合の抽選テンプレート。両者共通なので、引く強さが揃う。"""
    templates = game.match["random_slot_draw"]["mirrored_tier_templates"]
    return _rng(seed, "template").choice(templates)


def draw_random_slots(game: GameData, seed: str, side: str,
                      owned: list[str], chosen: tuple[str, ...],
                      template: list[str]) -> list[str]:
    """固定枠に入れていない手持ちから、テンプレートのティアに沿って引く。

    変わるのは identity であって power ではない ―― 両者は同じティア構成を引く。
    """
    rng = _rng(seed, f"slots:{side}")
    pool = [uid for uid in owned if uid not in chosen]
    drawn: list[str] = []
    for tier in template:
        candidates = [uid for uid in pool
                      if game.units[uid].tier == tier and uid not in drawn]
        if not candidates:
            # 手持ちが足りない時は共通プールから貸与する（初心者救済も兼ねる）
            candidates = [u.id for u in game.units_by_tier(tier)
                          if u.id not in chosen and u.id not in drawn]
        if not candidates:
            continue
        drawn.append(rng.choice(candidates))
    return drawn
