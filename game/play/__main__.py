"""試遊版。工程表 第1期の1〜3（描画・出撃ボタン・資金バーと拠点HP）。

    python3 -m game.play                        # 遊ぶ
    python3 -m game.play --unit archer          # 別のユニットで
    python3 -m game.play --unit grunt,archer    # ボタンを増やす
    python3 -m game.play --capture shots --at 5,30,90   # 画面だけ書き出す

**まだ「押したら出る」までしか無い。** カード・切り札・見切り・成長・
編成フェーズは入っていない（工程表 第2期）。相手だけは engine の方針が
本気で動かしてくるので、この段階では勝てなくてよい ―― ここで見たいのは
「触れるか」と「読めるか」であって、勝敗ではない。

固定タイムステップは engine のまま。実時間を溜めて、溜まったぶんだけ
`battle.step()` を呼ぶ。フレームレートが揺れても試合の中身は動かない。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from ..engine.battle import Battle, Loadout
from ..engine.data import load
from ..engine.draft import commit, match_seed
from ..engine.policy import POLICIES
from ..engine.presets import PRESETS, build
from .human import Controller

# 特典が戦闘に効かないアバターを選んである。この段階で見たいのは
# 戦闘そのものなので、拠点側から効く隠し味を入れない。
PLAYER_AVATAR = "scout"
PLAYER_TRUMP = "colossus"          # 出せないが Loadout に要る


def make_battle(game, unit_ids: tuple[str, ...], enemy: str, match_id: str):
    """人が side 0、engine の方針が side 1。"""
    seed = match_seed(
        commit(unit_ids, (), PLAYER_TRUMP, f"{match_id}:a"),
        commit(tuple(PRESETS[enemy][1]), tuple(PRESETS[enemy][2]),
               PRESETS[enemy][3], f"{match_id}:b"),
        match_id)

    player = Loadout(avatar=PLAYER_AVATAR, roster=unit_ids, deck=(),
                     trump=PLAYER_TRUMP)
    controller = Controller()
    battle = Battle(game, player, build(game, enemy, seed, "b"),
                    controller, POLICIES[enemy])
    return battle, controller


def run_capture(game, args, unit_ids) -> int:
    """表示のいらない書き出し。絵が出ているかを機械で確かめるためのもの。"""
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    import pygame

    from .view import H, W, View

    pygame.init()
    surface = pygame.display.set_mode((W, H))
    view = View(surface, tuple(game.units[u] for u in unit_ids))
    out = Path(args.capture)
    out.mkdir(parents=True, exist_ok=True)

    marks = sorted(float(s) for s in args.at.split(",") if s.strip())
    battle, controller = make_battle(game, unit_ids, args.enemy, args.match_id)
    written = []
    for mark in marks:
        while battle.t < mark and not battle.finished():
            # 出せるものを1tickに1体だけ出す。何も映っていない絵を
            # 書き出さないための最低限で、遊び方の見本ではない。
            for button in view.buttons:
                if button.ready(battle.sides[0]):
                    controller.deploy(button.spec.id)
                    break
            battle.step()
        view.draw(battle, player=0)
        path = out / f"t{int(battle.t):03d}.png"
        pygame.image.save(surface, str(path))
        written.append(path)
        if battle.finished():
            break

    pygame.quit()
    for path in written:
        print(path)
    print(f"出撃 {len(controller.history)} 回 / 却下 {controller.rejected} 回")
    return 0


def run_game(game, args, unit_ids) -> int:
    import pygame

    from .view import H, W, View

    pygame.init()
    pygame.display.set_caption("一本道の攻城戦 — 試遊版")
    surface = pygame.display.set_mode((W, H))
    clock = pygame.time.Clock()
    view = View(surface, tuple(game.units[u] for u in unit_ids))

    match = 0
    battle, controller = make_battle(game, unit_ids, args.enemy,
                                     f"{args.match_id}-{match}")
    tick = game.combat["tick_sec"]
    accumulator = 0.0
    paused = False
    running = True

    while running:
        # 実時間。0.25秒より大きく飛んだぶんは捨てる（窓を動かした後など、
        # 一気に何十tickも進むのを防ぐ）。
        dt = min(clock.tick(args.fps) / 1000.0, 0.25)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_SPACE:
                    paused = not paused
                elif event.key == pygame.K_r:
                    match += 1
                    battle, controller = make_battle(
                        game, unit_ids, args.enemy, f"{args.match_id}-{match}")
                    accumulator, paused = 0.0, False
                else:
                    button = view.button_for_key(event.key)
                    if button:
                        controller.deploy(button.spec.id)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                button = view.button_at(event.pos)
                if button:
                    controller.deploy(button.spec.id)

        if not paused and not battle.finished():
            accumulator += dt * args.speed
            while accumulator >= tick and not battle.finished():
                battle.step()
                accumulator -= tick

        view.draw(battle, player=0, paused=paused)
        pygame.display.flip()

    pygame.quit()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="game.play")
    parser.add_argument("--unit", default="grunt",
                        help="出撃ボタンにするユニット（カンマ区切り）")
    parser.add_argument("--enemy", default="balanced", choices=sorted(POLICIES))
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--match-id", default="play")
    parser.add_argument("--capture", metavar="DIR",
                        help="遊ばずに画面だけ書き出す（表示不要）")
    parser.add_argument("--at", default="5,30,90",
                        help="--capture で書き出す時刻（秒・カンマ区切り）")
    args = parser.parse_args(argv)

    game = load()
    unit_ids = tuple(u.strip() for u in args.unit.split(",") if u.strip())
    unknown = [u for u in unit_ids if u not in game.units]
    if unknown:
        print(f"知らないユニット: {'・'.join(unknown)}", file=sys.stderr)
        print(f"使えるのは: {'・'.join(sorted(game.units))}", file=sys.stderr)
        return 2
    if not unit_ids:
        print("--unit が空", file=sys.stderr)
        return 2

    try:
        import pygame  # noqa: F401
    except ModuleNotFoundError:
        print("pygame が要る:  pip install -r game/requirements.txt",
              file=sys.stderr)
        return 1

    if args.capture:
        return run_capture(game, args, unit_ids)
    return run_game(game, args, unit_ids)


if __name__ == "__main__":
    raise SystemExit(main())
