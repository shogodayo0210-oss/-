"""試遊版。にゃんこ大戦争と同じ並びで、上が戦場・下が操作盤。

    python3 -m game.play                             # 遊ぶ
    python3 -m game.play --brought bulwark           # 持ち込む呪文を変える
    python3 -m game.play --unit grunt,archer,mortar  # 出撃ボタンを変える
    python3 -m game.play --capture shots --at 30,90  # 画面だけ書き出す

操作は5つ。**数字キー1〜8で出撃**、**0で財布を育てる**、
**Qで持ち込みの呪文**、**W/E/Rでストックの呪文**、**Tで切り札**。
Space で一時停止、Esc で終了。

呪文もユニットも切り札も、**全部おなじ資金**を奪い合う。
今出すか、呪文を撃つか、貯めて大技か、財布を育てるか ―― それが試合の背骨。

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


def make_battle(game, unit_ids: tuple[str, ...], enemy: str, match_id: str,
                brought: str = "warcry"):
    """人が side 0、engine の方針が side 1。"""
    seed = match_seed(
        commit(unit_ids, (brought,), PLAYER_TRUMP, f"{match_id}:a"),
        commit(tuple(PRESETS[enemy][1]), (PRESETS[enemy][2],),
               PRESETS[enemy][3], f"{match_id}:b"),
        match_id)

    player = Loadout(avatar=PLAYER_AVATAR, roster=unit_ids, brought=brought,
                     trump=PLAYER_TRUMP, stock_seed=f"{seed}:a")
    controller = Controller()
    battle = Battle(game, player, build(game, enemy, seed, "b"),
                    controller, POLICIES[enemy])
    return battle, controller


def _send(controller, action) -> None:
    """画面が返した操作を、そのまま待ち行列に積む。"""
    if action is None:
        return
    kind, arg = action
    if kind == "deploy":
        controller.deploy(arg)
    elif kind == "cast":
        controller.cast(arg)
    elif kind == "upgrade":
        controller.upgrade()
    elif kind == "trump":
        controller.trump()


def run_capture(game, args, unit_ids) -> int:
    """表示のいらない書き出し。絵が出ているかを機械で確かめるためのもの。"""
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    import pygame

    from .view import H, W, View

    pygame.init()
    surface = pygame.display.set_mode((W, H))
    view = View(surface, tuple(game.units[u] for u in unit_ids), game)
    out = Path(args.capture)
    out.mkdir(parents=True, exist_ok=True)

    marks = sorted(float(s) for s in args.at.split(",") if s.strip())
    battle, controller = make_battle(game, unit_ids, args.enemy, args.match_id, args.brought)
    written = []
    for mark in marks:
        while battle.t < mark and not battle.finished():
            # 財布を育てつつ、出せるものを出し、余ったら呪文を撃つ。
            # 何も映っていない絵を書き出さないための最低限で、遊び方の
            # 見本ではない（上手い打ち方はここでは示さない）。
            me = battle.sides[0]
            if controller.pending:          # 前の操作がまだ捌けていない
                battle.step()
                continue
            saving = me.level < 4 and me.upgrade_cost is not None
            if saving and me.can_upgrade() and not me.busy:
                controller.upgrade()
            elif not saving:
                for button in view.buttons:
                    if button.ready(me):
                        controller.deploy(button.spec.id)
                        break
                if not controller.pending:
                    for slot in view.spells:
                        card = me.card_of(slot.source)
                        if (card and me.castable(slot.source)
                                and me.money > card.cost * 3):
                            controller.cast(slot.source)
                            break
            elif me.money < me.upgrade_cost * 0.6:
                # 貯めきる前の余りで壁だけは切らさない
                cheap = min(view.buttons, key=lambda b: b.spec.cost)
                if cheap.ready(me):
                    controller.deploy(cheap.spec.id)
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
    # 却下が多いのはこの運転手が雑だから（出撃と詠唱を同じtickに積んで、
    # 出撃で資金が減ったぶんを見ていない）。engine の側の話ではない。
    print(f"通った操作 {len(controller.history)} 回 "
          f"（この運転手は雑なので {controller.rejected} 回は空振り）")
    return 0


def run_game(game, args, unit_ids) -> int:
    import pygame

    from .view import H, W, View

    pygame.init()
    pygame.display.set_caption("一本道の攻城戦 — 試遊版")
    surface = pygame.display.set_mode((W, H))
    clock = pygame.time.Clock()
    view = View(surface, tuple(game.units[u] for u in unit_ids), game)

    match = 0
    battle, controller = make_battle(game, unit_ids, args.enemy,
                                     f"{args.match_id}-{match}", args.brought)
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
                        game, unit_ids, args.enemy,
                        f"{args.match_id}-{match}", args.brought)
                    accumulator, paused = 0.0, False
                else:
                    _send(controller, view.action_for_key(event.key))
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                _send(controller, view.action_at(event.pos))

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
    parser.add_argument("--brought", default="warcry",
                        help="持ち込む呪文1枚")
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
