"""画面に出す。

`engine/` は数字しか持っておらず、画面のことを何ひとつ知らない。
ここが唯一その二つを繋ぐ場所で、**逆向きの依存は作らない** ――
engine が pygame を import することは無いし、描画の都合で盤面を触ることもない。
このモジュールは Battle を読むだけで、書き換えない。

絵は `art/out/` の仮絵をそのまま使う。本番の絵に差し替えても、
ファイル名が同じならここは変わらない。
"""

from __future__ import annotations

import json
from pathlib import Path

import pygame

from ..engine.battle import Battle, Fighter, Side
from ..engine.data import Unit

ART = Path(__file__).resolve().parent.parent / "art"

# ---------------------------------------------------------------- 画面の寸法
W, H = 1000, 580
GROUND_Y = 392          # ユニットが立つ線
HUD_Y = 426             # ここから下が操作盤
LANE_LEFT, LANE_RIGHT = 92, W - 92

UNIT_PX = 48            # art/README.md 1章の実寸
AVATAR_PX = 64
# 等倍だと画面に対して小さすぎる。art/README.md 1章の「等倍〜2倍、
# 画面高さのおよそ1/6」に合わせて2倍で出す。補間しない scale を使うので
# ドットは潰れない。
SCALE = 2

# ---------------------------------------------------------------- 色
# art/palette.json と同じ出どころ。機械=水色、人=金、精霊=青緑、獣=橙。
BG = (23, 28, 34)       # palette.json の sheet.background
SKY = (30, 39, 49)
GROUND = (37, 47, 58)
INK = (223, 230, 236)
MUTED = (125, 141, 156)
RULE = (43, 52, 62)
PANEL = (27, 35, 44)
ACCENT = (62, 202, 217)
GOLD = (224, 170, 70)
GREEN = (79, 161, 150)
RED = (226, 98, 47)

# 日本語が出るフォントを順に探す。無ければ pygame の既定にする。
JP_FONTS = ("ipagothic", "ipapgothic", "notosanscjkjp", "notosansjp",
            "vlgothic", "takaogothic", "wenquanyizenheimono", "unifontjp")


def load_font(size: int, bold: bool = False) -> pygame.font.Font:
    for name in JP_FONTS:
        path = pygame.font.match_font(name, bold=bold)
        if path:
            return pygame.font.Font(path, size)
    return pygame.font.Font(None, size)


def _family_colors() -> dict[str, tuple[int, int, int]]:
    """仮絵が無いとき（切り札）に使う、系統ごとの色。"""
    with open(ART / "palette.json", encoding="utf-8") as f:
        raw = json.load(f)["families"]

    def rgb(value: str) -> tuple[int, int, int]:
        return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))

    return {name: rgb(ramp["base"]) for name, ramp in raw.items()}


class Sprites:
    """PNG を読んで、向きごとに使い回す。"""

    def __init__(self):
        self._cache: dict[tuple[str, bool], tuple[pygame.Surface, pygame.Rect]] = {}
        self._avatars: dict[str, pygame.Surface] = {}
        self._families = _family_colors()

    @staticmethod
    def _grow(surf: pygame.Surface) -> pygame.Surface:
        return pygame.transform.scale(
            surf, (surf.get_width() * SCALE, surf.get_height() * SCALE))

    def _entry(self, spec: Unit, flip: bool):
        key = (spec.id, flip)
        if key not in self._cache:
            path = ART / "out" / "units" / f"{spec.id}.png"
            surf = (pygame.image.load(str(path)).convert_alpha()
                    if path.exists() else self._placeholder(spec))
            surf = self._grow(surf)
            if flip:
                surf = pygame.transform.flip(surf, True, False)
            # 48×48 の余白ぶんを覚えておく。絵の実体がどこから始まるかを
            # 見ないと、体力の棒が頭の遥か上に浮く。
            self._cache[key] = (surf, surf.get_bounding_rect())
        return self._cache[key]

    def unit(self, spec: Unit, flip: bool) -> pygame.Surface:
        return self._entry(spec, flip)[0]

    def unit_bbox(self, spec: Unit, flip: bool) -> pygame.Rect:
        return self._entry(spec, flip)[1]

    def avatar(self, avatar_id: str, flip: bool) -> pygame.Surface | None:
        key = f"{avatar_id}:{flip}"
        if key not in self._avatars:
            path = ART / "out" / "avatars" / f"{avatar_id}.png"
            if not path.exists():
                return None
            surf = self._grow(pygame.image.load(str(path)).convert_alpha())
            self._avatars[key] = (pygame.transform.flip(surf, True, False)
                                  if flip else surf)
        return self._avatars[key]

    def _placeholder(self, spec: Unit) -> pygame.Surface:
        """切り札には仮絵が無い（art/README.md 6章では96pxの別枠）。
        絵が無いだけで落ちないように、系統色の塊で代用する。"""
        size = 72
        surf = pygame.Surface((size, size), pygame.SRCALPHA)
        body = pygame.Rect(size // 6, size // 5, size * 2 // 3, size * 4 // 5)
        pygame.draw.rect(surf, self._families.get(spec.family, MUTED), body)
        pygame.draw.rect(surf, GOLD, body, 2)
        return surf


class Button:
    """出撃ボタン1つ。押せるかどうかは毎フレーム盤面から出す。"""

    def __init__(self, rect: pygame.Rect, spec: Unit, hotkey: int, label: str):
        self.rect = rect
        self.spec = spec
        self.hotkey = hotkey
        self.label = label

    def blocked_by(self, side: Side) -> str | None:
        """押せない理由。押せるなら None。"""
        if side.busy:
            return "育成中"
        if side.deploy_lock_left > 0:
            return "硬直"
        if side.deploy_cd.get(self.spec.id, 0.0) > 0:
            return None            # 残り時間はボタンの上に出す
        if side.money < side.unit_cost(self.spec):
            return "資金不足"
        return None

    def ready(self, side: Side) -> bool:
        return (self.blocked_by(side) is None
                and side.deploy_cd.get(self.spec.id, 0.0) <= 0)


class View:
    """1フレーム描く。状態は持たない（フォントと絵の使い回しだけ）。"""

    def __init__(self, surface: pygame.Surface, roster: tuple[Unit, ...]):
        self.surface = surface
        self.sprites = Sprites()
        self.f_small = load_font(15)
        self.f_body = load_font(18)
        self.f_bold = load_font(20, bold=True)
        self.f_big = load_font(34, bold=True)
        self.f_num = load_font(24, bold=True)

        self.buttons = [
            Button(pygame.Rect(W - 46 - (len(roster) - i) * 116, HUD_Y + 22, 104, 106),
                   spec, pygame.K_1 + i, str(i + 1))
            for i, spec in enumerate(roster)
        ]

    # -------------------------------------------------------------- 座標
    def px(self, x_m: float, lane_length: float) -> int:
        """レーン上の位置（m）を画面の x に。"""
        span = LANE_RIGHT - LANE_LEFT
        return int(LANE_LEFT + (x_m / lane_length) * span)

    @staticmethod
    def _row(spec: Unit) -> int:
        """奥行き。攻撃範囲から出すので、後衛が後ろに立つのが形で分かる。"""
        if spec.near > 0 or spec.far > 50:
            return 2
        if spec.far > 20:
            return 1
        return 0

    # -------------------------------------------------------------- 部品
    def _text(self, text, font, color, pos, center=False, right=False):
        surf = font.render(text, True, color)
        rect = surf.get_rect()
        if center:
            rect.center = pos
        elif right:
            rect.midright = pos
        else:
            rect.midleft = pos
        self.surface.blit(surf, rect)
        return rect

    def _bar(self, rect, ratio, color, back=RULE, border=None):
        pygame.draw.rect(self.surface, back, rect)
        filled = pygame.Rect(rect.x, rect.y, int(rect.w * max(0.0, min(1.0, ratio))),
                             rect.h)
        if filled.w > 0:
            pygame.draw.rect(self.surface, color, filled)
        if border:
            pygame.draw.rect(self.surface, border, rect, 1)

    # -------------------------------------------------------------- 場
    def _field(self, battle: Battle) -> None:
        pygame.draw.rect(self.surface, SKY, (0, 0, W, GROUND_Y))
        pygame.draw.rect(self.surface, GROUND, (0, GROUND_Y, W, HUD_Y - GROUND_Y))
        pygame.draw.line(self.surface, RULE, (0, GROUND_Y), (W, GROUND_Y))

        # 20mごとの目盛り。距離感が無いと射程の帯が読めない。
        lane = battle.game.lane_length
        for metre in range(0, int(lane) + 1, 20):
            x = self.px(metre, lane)
            pygame.draw.line(self.surface, (58, 70, 83),
                             (x, GROUND_Y - 6), (x, GROUND_Y + 6))
            self._text(f"{metre}m", self.f_small, (86, 100, 114),
                       (x, GROUND_Y + 20), center=True)

        for side in battle.sides:
            sprite = self.sprites.avatar(side.loadout.avatar, flip=side.index == 1)
            x = self.px(side.base_x, lane)
            if sprite:
                self.surface.blit(sprite, sprite.get_rect(midbottom=(x, GROUND_Y)))
            else:
                pygame.draw.rect(self.surface, MUTED,
                                 (x - 24, GROUND_Y - 96, 48, 96))

    def _fighters(self, battle: Battle) -> None:
        lane = battle.game.lane_length
        # 奥の列から描く。前に立つものが手前に重なる。
        for row in (2, 1, 0):
            for side in battle.sides:
                for f in side.fighters:
                    if not f.alive or self._row(f.spec) != row:
                        continue
                    self._fighter(f, lane, row)

    def _fighter(self, f: Fighter, lane: float, row: int) -> None:
        mine = f.side == 0
        flip = not mine                    # 敵は左を向く
        sprite = self.sprites.unit(f.spec, flip)
        lift = row * 14
        x = self.px(f.x, lane)
        feet = GROUND_Y - lift
        rect = sprite.get_rect(midbottom=(x, feet))
        team = GREEN if mine else RED

        # 足元の楕円1枚。にゃんこ大戦争のやり方をそのまま採る（art/README.md 0章）。
        # 影を陣営の色で塗ると、同じ絵でもどちら側かが一目で分かる。
        shadow = pygame.Surface((sprite.get_width(), 14), pygame.SRCALPHA)
        pygame.draw.ellipse(shadow, (*team, 70), shadow.get_rect())
        pygame.draw.ellipse(shadow, (*team, 150), shadow.get_rect(), 2)
        self.surface.blit(shadow, shadow.get_rect(center=(x, feet - 2)))

        if f.summon_left > 0:                      # 召喚演出のあいだは半透明
            sprite = sprite.copy()
            sprite.set_alpha(90)
        self.surface.blit(sprite, rect)

        head = rect.top + self.sprites.unit_bbox(f.spec, flip).top
        if f.hp < f.spec.hp:
            self._bar(pygame.Rect(x - 22, head - 9, 44, 4),
                      f.hp / f.spec.hp, team, back=(18, 22, 27))

        # 振りかぶり。設計書7.5の「大きい一撃は発生0.6秒以上」を画面に出す。
        # ここが見えないと、見切りの読み合いが嘘になる（art/README.md 4章）。
        if f.windup_left > 0:
            total = max(f.spec.attack_windup_sec, 1e-6)
            done = 1.0 - f.windup_left / total
            self._bar(pygame.Rect(x - 22, head - 17, 44, 5), done, GOLD,
                      back=(18, 22, 27))

        if f.stun_left > 0:
            pygame.draw.circle(self.surface, GOLD, (x, head - 24), 3)

    # -------------------------------------------------------------- 拠点HP
    def _header(self, battle: Battle, player: int) -> None:
        pygame.draw.rect(self.surface, PANEL, (0, 0, W, 68))
        pygame.draw.line(self.surface, RULE, (0, 68), (W, 68))
        full = battle.game.base_hp

        for side in battle.sides:
            mine = side.index == player
            hp = max(0.0, side.base_hp)
            avatar = battle.game.avatars[side.loadout.avatar]
            name = f"{'自陣' if mine else '敵陣'}  {avatar.name}"
            color = GREEN if mine else RED

            if mine:
                bar = pygame.Rect(26, 32, 330, 20)
                self._text(name, self.f_small, MUTED, (26, 18))
                self._text(f"{hp:,.0f}", self.f_body, INK, (bar.right + 12, 42))
            else:
                bar = pygame.Rect(W - 356, 32, 330, 20)
                self._text(name, self.f_small, MUTED, (W - 26, 18), right=True)
                self._text(f"{hp:,.0f}", self.f_body, INK, (bar.left - 12, 42),
                           right=True)
            self._bar(bar, hp / full, color, border=RULE)

        left = max(0.0, battle.game.time_limit - battle.t)
        self._text(f"{int(left) // 60}:{int(left) % 60:02d}", self.f_num, INK,
                   (W // 2, 34), center=True)
        self._text("残り", self.f_small, MUTED, (W // 2, 55), center=True)

    # -------------------------------------------------------------- 操作盤
    def _hud(self, battle: Battle, side: Side) -> None:
        pygame.draw.rect(self.surface, PANEL, (0, HUD_Y, W, H - HUD_Y))
        pygame.draw.line(self.surface, RULE, (0, HUD_Y), (W, HUD_Y))

        cap = side.money_cap
        bar = pygame.Rect(34, HUD_Y + 46, 440, 30)
        self._text(f"資金  Lv{side.level}", self.f_small, MUTED, (34, HUD_Y + 26))
        self._bar(bar, side.money / cap, GOLD, border=RULE)

        # 出せる線。ここを越えたら押せる、が棒の上で分かる。
        for button in self.buttons:
            cost = side.unit_cost(button.spec)
            if cost <= cap:
                x = bar.x + int(bar.w * cost / cap)
                pygame.draw.line(self.surface, INK, (x, bar.y - 4),
                                 (x, bar.bottom + 4))

        self._text(f"{side.money:,.0f} / {cap:,.0f}", self.f_body, INK,
                   (bar.right + 14, bar.centery))
        self._text(f"毎秒 +{side.income:.0f}", self.f_small, MUTED,
                   (34, bar.bottom + 18))

        for button in self.buttons:
            self._button(button, side)

    def _button(self, button: Button, side: Side) -> None:
        rect = button.rect
        cd = side.deploy_cd.get(button.spec.id, 0.0)
        reason = button.blocked_by(side)
        ready = button.ready(side)

        pygame.draw.rect(self.surface, (33, 43, 54) if ready else (24, 31, 39), rect)

        if cd > 0:                    # 再出撃までを下から塗り戻す
            total = max(side.deploy_cooldown(button.spec), 1e-6)
            h = int(rect.h * min(1.0, cd / total))
            pygame.draw.rect(self.surface, (18, 24, 30),
                             (rect.x, rect.bottom - h, rect.w, h))

        pygame.draw.rect(self.surface, ACCENT if ready else RULE, rect, 2)
        self._text(button.label, self.f_small, ACCENT if ready else MUTED,
                   (rect.x + 9, rect.y + 14))
        self._text(button.spec.name, self.f_bold, INK if ready else MUTED,
                   (rect.centerx, rect.y + 42), center=True)
        self._text(f"{button.spec.cost}", self.f_body, GOLD if ready else RULE,
                   (rect.centerx, rect.y + 68), center=True)

        status = f"{cd:.1f}秒" if cd > 0 else (reason or "")
        if status:
            self._text(status, self.f_small, MUTED,
                       (rect.centerx, rect.bottom - 15), center=True)

    # -------------------------------------------------------------- 決着
    def _result(self, battle: Battle, player: int) -> None:
        veil = pygame.Surface((W, HUD_Y), pygame.SRCALPHA)
        veil.fill((10, 14, 18, 190))
        self.surface.blit(veil, (0, 0))

        from ..engine.battle import Result
        result = Result.of(battle)
        if result.winner is None:
            headline, color = "引き分け", MUTED
        elif result.winner == player:
            headline, color = "勝ち", ACCENT
        else:
            headline, color = "負け", RED

        self._text(headline, self.f_big, color, (W // 2, 190), center=True)
        self._text(result.reason, self.f_body, INK, (W // 2, 232), center=True)
        self._text(f"{result.seconds:.0f}秒", self.f_small, MUTED,
                   (W // 2, 258), center=True)
        self._text("R でもう1回  /  Esc で終了", self.f_small, MUTED,
                   (W // 2, 296), center=True)

    # -------------------------------------------------------------- 1フレーム
    def draw(self, battle: Battle, player: int, paused: bool = False) -> None:
        self.surface.fill(BG)
        self._field(battle)
        self._fighters(battle)
        self._header(battle, player)
        self._hud(battle, battle.sides[player])
        if battle.finished():
            self._result(battle, player)
        elif paused:
            self._text("一時停止（Space）", self.f_bold, GOLD,
                       (W // 2, 120), center=True)

    def button_at(self, pos: tuple[int, int]) -> Button | None:
        for button in self.buttons:
            if button.rect.collidepoint(pos):
                return button
        return None

    def button_for_key(self, key: int) -> Button | None:
        for button in self.buttons:
            if button.hotkey == key:
                return button
        return None
