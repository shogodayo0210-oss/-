"""人の操作を、engine が期待する「方針」の形に変える。

`Battle` は毎tick `policy(battle, side)` を呼ぶだけなので、**人もAIも
同じ入口を通る。** シミュレータ側には手を入れていない。

押した内容はいったん待ち行列に入り、次のtickの頭で使われる。画面の
フレームレートと試合の進みが分かれているので、描画が重くなっても
試合の中身は変わらない ―― engine の決定論（設計書8章）はここで壊さない。

通った操作は `history` に残る。いまは使い道が無いが、これが
**そのままリプレイと通信対戦の入力列**になる（工程表 第3期）。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Command:
    kind: str
    arg: str


@dataclass
class Controller:
    """試遊版のプレイヤー。いまは出撃しかできない。"""

    pending: deque = field(default_factory=deque)
    history: list[tuple[int, str, str]] = field(default_factory=list)
    rejected: int = 0
    ticks: int = 0

    def deploy(self, unit_id: str) -> None:
        self.pending.append(Command("deploy", unit_id))

    def __call__(self, battle, side) -> None:
        self.ticks += 1
        while self.pending:
            command = self.pending.popleft()
            if command.kind == "deploy" and battle.deploy(side, command.arg):
                self.history.append((self.ticks, command.kind, command.arg))
            else:
                # 出せなかった操作は捨てる。持ち越すと、資金が貯まった
                # 瞬間に覚えのない出撃が走る。
                self.rejected += 1
