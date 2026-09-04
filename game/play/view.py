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
# にゃんこ大戦争と同じ並び ―― 上が戦場、下が操作盤。
# 操作盤は2段：**呪文を選ぶところ**と、**キャラを召喚するところ**。
W, H = 1140, 712
GROUND_Y = 400          # ユニットが立つ線
HUD_Y = 434             # ここから下が操作盤
SPELL_Y = 440           # 呪文の段
SUMMON_Y = 548          # 資金と召喚の段
LANE_LEFT, LANE_RIGHT = 100, W - 100

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


class Spell:
    """呪文の枠1つ。持ち込み1枠＋ストック3枠。"""

    def __init__(self, rect: pygame.Rect, source: tuple[str, int],
                 hotkey: int, label: str):
        self.rect = rect
        self.source = source
        self.hotkey = hotkey
        self.label = label


class View:
    """1フレーム描く。状態は持たない（フォントと絵の使い回しだけ）。"""

    def __init__(self, surface: pygame.Surface, roster: tuple[Unit, ...], game):
        self.surface = surface
        self.game = game
        self.sprites = Sprites()
        self.f_small = load_font(15)
        self.f_body = load_font(18)
        self.f_bold = load_font(20, bold=True)
        self.f_big = load_font(34, bold=True)
        self.f_num = load_font(24, bold=True)

        # ── 呪文の段：持ち込み1枠 ＋ ストック3枠 ＋ 切り札 ──────────
        slots = game.stock_slots
        self.spells = [Spell(pygame.Rect(66, SPELL_Y + 8, 158, 92),
                             ("brought", 0), pygame.K_q, "持ち込み")]
        for i in range(slots):
            self.spells.append(Spell(
                pygame.Rect(240 + i * 168, SPELL_Y + 8, 158, 92),
                ("stock", i), pygame.K_w + i, f"ストック{i + 1}"))
        self.trump_rect = pygame.Rect(W - 182, SPELL_Y + 8, 158, 92)
        self.trump_key = pygame.K_t

        # ── 召喚の段：財布 ＋ 出撃ボタン ─────────────────────────
        self.upgrade_rect = pygame.Rect(24, SUMMON_Y + 44, 118, 100)
        self.upgrade_key = pygame.K_0
        span = W - 24 - 158
        width = min(114, span // max(len(roster), 1) - 8)
        self.buttons = [
            Button(pygame.Rect(158 + i * (width + 8), SUMMON_Y + 44, width, 100),
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
                   (W // 2, 26), center=True)

        # 次の配布。陣地ボーナスは**いま押し込んでいる側だけ**に入るので、
        # 誰が取りそうかを出す ―― これが見えないと、取りに行く判断ができない。
        drop = battle.next_drop()
        if drop is None:
            self._text("残り", self.f_small, MUTED, (W // 2, 50), center=True)
            return
        seconds, amount = drop
        if battle.next_drop_is_contested():
            lead = battle.leader()
            if lead is None:
                who, tint = "互角", MUTED
            elif lead.index == player:
                who, tint = "自分が優勢", GREEN
            else:
                who, tint = "相手が優勢", RED
            self._text(f"陣地 +{amount}  あと{seconds:.0f}秒", self.f_small, GOLD,
                       (W // 2, 48), center=True)
            self._text(who, self.f_small, tint, (W // 2, 64), center=True)
        else:
            self._text(f"両者 +{amount}  あと{seconds:.0f}秒", self.f_small, MUTED,
                       (W // 2, 52), center=True)

    # ---------------------------------------------------------- 操作盤：呪文
    def _spells(self, battle: Battle, side: Side) -> None:
        pygame.draw.rect(self.surface, PANEL, (0, HUD_Y, W, H - HUD_Y))
        pygame.draw.line(self.surface, RULE, (0, HUD_Y), (W, HUD_Y))
        self._text("呪文", self.f_small, MUTED, (22, SPELL_Y + 44))

        for slot in self.spells:
            self._spell(slot, battle, side)
        self._trump(battle, side)

    def _spell(self, slot: "Spell", battle: Battle, side: Side) -> None:
        rect = slot.rect
        card = side.card_of(slot.source)
        ready = side.castable(slot.source)
        kind, index = slot.source

        pygame.draw.rect(self.surface, (33, 43, 54) if ready else (24, 31, 39), rect)

        # 空きストックは下から補充されていく。持ち込みは自分のクールタイム。
        left = total = 0.0
        if kind == "stock" and side.stock[index] is None:
            left, total = side.restock[index], side.restock_sec
        elif kind == "brought":
            left, total = side.brought_cd, self.game.cards[side.brought].cooldown_sec
        if left > 0:
            h = int(rect.h * min(1.0, left / max(total, 1e-6)))
            pygame.draw.rect(self.surface, (18, 24, 30),
                             (rect.x, rect.bottom - h, rect.w, h))

        edge = GOLD if kind == "brought" else (ACCENT if ready else RULE)
        pygame.draw.rect(self.surface, edge, rect, 2)
        self._text(slot.label, self.f_small, edge, (rect.x + 8, rect.y + 13))

        if card is None:
            self._text("補充中", self.f_body, MUTED, (rect.centerx, rect.centery),
                       center=True)
            self._text(f"{left:.1f}秒", self.f_small, MUTED,
                       (rect.centerx, rect.bottom - 14), center=True)
            return

        self._text(card.name, self.f_bold, INK if ready else MUTED,
                   (rect.centerx, rect.y + 40), center=True)
        self._text(f"{card.cost}", self.f_body, GOLD if ready else RULE,
                   (rect.centerx, rect.y + 66), center=True)
        note = card.band
        if left > 0:
            note = f"{left:.1f}秒"
        elif side.money < card.cost:
            note = "資金不足"
        self._text(note, self.f_small, MUTED,
                   (rect.centerx, rect.bottom - 14), center=True)

    def _trump(self, battle: Battle, side: Side) -> None:
        rect = self.trump_rect
        spec = self.game.trumps[side.loadout.trump]
        unlock = self.game.trump_rules["unlock_at_sec"]
        locked = battle.t < unlock
        ready = (not side.trump_used and not locked
                 and side.money >= spec.cost and not side.busy)

        pygame.draw.rect(self.surface, (36, 30, 22) if ready else (24, 31, 39), rect)
        pygame.draw.rect(self.surface, GOLD if ready else RULE, rect, 2)
        self._text("切り札", self.f_small, GOLD if ready else MUTED,
                   (rect.x + 8, rect.y + 13))
        if side.trump_used:
            self._text("使用済み", self.f_body, MUTED,
                       (rect.centerx, rect.centery), center=True)
            return
        self._text(spec.name, self.f_bold, INK if ready else MUTED,
                   (rect.centerx, rect.y + 40), center=True)
        self._text(f"{spec.cost}", self.f_body, GOLD if ready else RULE,
                   (rect.centerx, rect.y + 66), center=True)
        note = f"{unlock - battle.t:.0f}秒後" if locked else (
            "資金不足" if side.money < spec.cost else "1試合1回")
        self._text(note, self.f_small, MUTED,
                   (rect.centerx, rect.bottom - 14), center=True)

    # ------------------------------------------------------ 操作盤：資金と召喚
    def _summon(self, battle: Battle, side: Side) -> None:
        # 資金は1〜14の整数なので、**マス目で数えられる**ように描く。
        # 棒が滑らかに伸びるのではなく1マスずつ点くので、
        # 「あと2マスで臼砲」が目で分かる。
        cap = int(side.money_cap)
        have = int(side.money)
        cell, gap = 26, 4
        for i in range(cap):
            box = pygame.Rect(24 + i * (cell + gap), SUMMON_Y, cell, 26)
            if i < have:
                pygame.draw.rect(self.surface, GOLD, box)
            else:
                pygame.draw.rect(self.surface, (30, 38, 47), box)
            pygame.draw.rect(self.surface, RULE, box, 1)

        right = 24 + cap * (cell + gap)
        self._text(f"{have} / {cap}", self.f_num, INK, (right + 12, SUMMON_Y + 13))
        self._text(f"財布 Lv{side.level}   {side.income_amount:.0f} / "
                   f"{side.income_every:.1f}秒",
                   self.f_small, MUTED, (right + 88, SUMMON_Y + 13))
        if side.busy:
            self._text(f"育成中 {side.upgrading_left:.1f}秒 — 何も出せない",
                       self.f_small, RED, (right + 250, SUMMON_Y + 13))

        self._upgrade(side)
        for button in self.buttons:
            self._button(button, side)

    def _upgrade(self, side: Side) -> None:
        rect = self.upgrade_rect
        cost = side.upgrade_cost
        ready = cost is not None and side.can_upgrade() and not side.busy

        pygame.draw.rect(self.surface, (26, 40, 40) if ready else (24, 31, 39), rect)
        pygame.draw.rect(self.surface, GREEN if ready else RULE, rect, 2)
        self._text("0", self.f_small, GREEN if ready else MUTED,
                   (rect.x + 8, rect.y + 13))
        self._text("財布", self.f_bold, INK if ready else MUTED,
                   (rect.centerx, rect.y + 38), center=True)
        if cost is None:
            self._text("最大", self.f_body, MUTED,
                       (rect.centerx, rect.y + 62), center=True)
            return
        self._text(f"{cost}", self.f_body, GREEN if ready else RULE,
                   (rect.centerx, rect.y + 62), center=True)
        self._text(f"Lv{side.level + 1} へ", self.f_small, MUTED,
                   (rect.centerx, rect.bottom - 13), center=True)

    def _button(self, button: "Button", side: Side) -> None:
        rect = button.rect
        cd = side.deploy_cd.get(button.spec.id, 0.0)
        cost = side.unit_cost(button.spec)
        over_cap = cost > side.money_cap          # 財布のレベルが足りない
        ready = button.ready(side)

        pygame.draw.rect(self.surface, (33, 43, 54) if ready else (24, 31, 39), rect)
        if cd > 0:                    # 再出撃までを下から塗り戻す
            total = max(side.deploy_cooldown(button.spec), 1e-6)
            h = int(rect.h * min(1.0, cd / total))
            pygame.draw.rect(self.surface, (18, 24, 30),
                             (rect.x, rect.bottom - h, rect.w, h))

        edge = RED if over_cap else (ACCENT if ready else RULE)
        pygame.draw.rect(self.surface, edge, rect, 2)
        self._text(button.label, self.f_small, edge, (rect.x + 8, rect.y + 13))
        self._text(button.spec.name, self.f_bold, INK if ready else MUTED,
                   (rect.centerx, rect.y + 38), center=True)
        self._text(f"{cost:.0f}", self.f_body, GOLD if ready else RULE,
                   (rect.centerx, rect.y + 62), center=True)

        if over_cap:
            note = "財布 Lv不足"
        elif cd > 0:
            note = f"{cd:.1f}秒"
        else:
            note = button.blocked_by(side) or ""
        if note:
            self._text(note, self.f_small, RED if over_cap else MUTED,
                       (rect.centerx, rect.bottom - 13), center=True)

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
        side = battle.sides[player]
        self.surface.fill(BG)
        self._field(battle)
        self._fighters(battle)
        self._header(battle, player)
        self._spells(battle, side)
        self._summon(battle, side)
        if battle.finished():
            self._result(battle, player)
        elif paused:
            self._text("一時停止（Space）", self.f_bold, GOLD,
                       (W // 2, 120), center=True)

    # ------------------------------------------------------------ 当たり判定
    # クリックとキーを同じ「操作」に畳んで返す。__main__ は中身を知らなくていい。
    def action_at(self, pos: tuple[int, int]):
        if self.upgrade_rect.collidepoint(pos):
            return ("upgrade", None)
        if self.trump_rect.collidepoint(pos):
            return ("trump", None)
        for slot in self.spells:
            if slot.rect.collidepoint(pos):
                return ("cast", slot.source)
        for button in self.buttons:
            if button.rect.collidepoint(pos):
                return ("deploy", button.spec.id)
        return None

    def action_for_key(self, key: int):
        if key == self.upgrade_key:
            return ("upgrade", None)
        if key == self.trump_key:
            return ("trump", None)
        for slot in self.spells:
            if slot.hotkey == key:
                return ("cast", slot.source)
        for button in self.buttons:
            if button.hotkey == key:
                return ("deploy", button.spec.id)
        return None
