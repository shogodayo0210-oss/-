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
W, H = 1320, 792
GROUND_Y = 460          # ユニットが立つ線。旧380から拡張 ―― 戦場をもっと広く
HUD_Y = 492             # ここから下が操作盤
SPELL_Y = 498           # 呪文の段。札には効果の説明まで載せるので背を高くしてある
SUMMON_Y = 628          # 資金と召喚の段
LANE_LEFT, LANE_RIGHT = 100, W - 100

# 画面上の高さ（見た目の大きさ）をここで決める。**元絵の解像度は問わない。**
# 48pxのドット絵でも、もっと大きい塗り絵調の絵でも、読み込んだ絵の実寸に
# 合わせて高さがここに来るよう縮尺をかける ―― art/README.md 1章の
# 「画面高さのおよそ1/6」がユニット、拠点はその1.3倍という目安（旧: 48px/64pxを
# 2倍表示していたのと同じ見た目の大きさ）。元絵が変わってもレーンの密度や
# HUDの寸法を触らずに済む。
UNIT_TARGET_H = 96
AVATAR_TARGET_H = 128

# ---------------------------------------------------------------- 色
# art/palette.json と同じ出どころ。種族ごとの色はそちらが持つ。
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
BUFF = (94, 156, 224)   # 呪文フラッシュの「バフ」側。デバフは既存の RED を使い回す

# 伝言1：数字はもう合っているが、何が起きたかが画面から伝わっていなかった。
# 3つとも仮の四角・テキストでいい代わりに、**エンジン側の直近イベント
# （Battle.base_hits / level_ups / cast_effects）だけを見て描く** ――
# View 自身はフレームをまたぐ状態を持たない、という元々の約束を守るため。
TRAINING_POPUP_SEC = 1.2     # 「財布 LvUP！」を出しておく秒数
WALL_LABEL_SEC = 0.6         # 「WALL」表示を出しておく秒数
CAST_FLASH_SEC = 0.25        # 画面端フラッシュの長さ

# 日本語が出るフォントを順に探す。無ければ pygame の既定にする。
JP_FONTS = ("ipagothic", "ipapgothic", "notosanscjkjp", "notosansjp",
            "vlgothic", "takaogothic", "wenquanyizenheimono", "unifontjp")


def grid_step(lane: float) -> int:
    """目盛りの刻み。レーン長が変わっても本数がだいたい一定になるように。"""
    return max(20, int(round(lane / 8 / 20)) * 20)


def load_font(size: int, bold: bool = False) -> pygame.font.Font:
    for name in JP_FONTS:
        path = pygame.font.match_font(name, bold=bold)
        if path:
            return pygame.font.Font(path, size)
    return pygame.font.Font(None, size)


def _race_colors() -> dict[str, tuple[int, int, int]]:
    """仮絵が無いとき（切り札）に使う、種族ごとの色。"""
    with open(ART / "palette.json", encoding="utf-8") as f:
        raw = json.load(f)["races"]

    def rgb(value: str) -> tuple[int, int, int]:
        return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))

    return {name: rgb(ramp["base"]) for name, ramp in raw.items()}


def _art_scales() -> dict[str, float]:
    """art/looks.json の任意項目 `art_scale`。表示だけの縮尺の掛け目（既定1.0）。

    ゲームの数字（characters.json）には一切触れない ―― DPS と同じ理由で、
    見た目の調整と data を混ぜない。下の `_cost_scales` と掛け合わさる
    （コストなりの大きさに対する**追加の**微調整という位置づけ）。
    """
    with open(ART / "looks.json", encoding="utf-8") as f:
        raw = json.load(f)["units"]
    return {uid: entry.get("art_scale", 1.0) for uid, entry in raw.items()}


COST_SCALE_MIN, COST_SCALE_MAX = 0.7, 1.3


def _cost_scales(game) -> dict[str, float]:
    """コストが高いほど大きく見せる ―― art/README.md 3章
    「コストが高い＝大きい。キャンバスを埋める」を実際の描画に適用する。

    生の cost をそのまま比例させると、安いユニットが大半を占める分布の下では
    高コスト側だけが伸びてしまう。art_brief.py の `Scale` と同じ、
    ロースター内の**順位**（percentile）で正規化する。
    """
    units = list(game.units.values())
    costs = sorted(u.cost for u in units)
    denom = max(len(costs) - 1, 1)

    def rank(cost: int) -> float:
        below = sum(1 for c in costs if c < cost)
        return below / denom

    return {u.id: COST_SCALE_MIN + rank(u.cost) * (COST_SCALE_MAX - COST_SCALE_MIN)
            for u in units}


ANIM_STATES = ("idle", "windup", "hit", "recover")


def _anim_state(f: Fighter) -> str:
    """いまの攻撃モーションのコマ。View自身は状態を持たないので、
    毎フレーム Fighter の残り時間（battle.py）から出し直す。

    振りかぶり中は windup。当たった直後（`exposed_left`＝後隙）の頭の
    ごく短い間だけ hit、残りは recover ―― 攻撃発生・後隙のどちらも
    絵が無いユニットは idle のままで、Sprites 側が自動でそこへ落ちる。
    """
    if f.windup_left > 0:
        return "windup"
    if f.exposed_left > 0:
        recover_sec = f.spec.attack_recover_sec or f.exposed_left
        hit_sec = min(0.1, recover_sec * 0.3)
        return "hit" if f.exposed_left > max(0.0, recover_sec - hit_sec) else "recover"
    return "idle"


class Sprites:
    """PNG を読んで、向き・コマごとに使い回す。"""

    def __init__(self, game):
        self._cache: dict[tuple[str, bool, str], tuple[pygame.Surface, pygame.Rect]] = {}
        self._avatars: dict[str, pygame.Surface] = {}
        self._races = _race_colors()
        self._art_overrides = _art_scales()
        self._cost_scales = _cost_scales(game)

    @staticmethod
    def _grow(surf: pygame.Surface, target_h: int) -> pygame.Surface:
        """元絵の実寸に関わらず、高さが `target_h` に来るよう縦横同倍率で拡縮する。

        ドット絵（48px）が来ても、もっと高精細な絵が来ても同じ扱いにできる。
        滑らかな `smoothscale` を使う ―― ドット絵前提の `scale`（最近傍・
        カクカクのまま拡大）は、階調のある絵だと縁がギザギザになる。
        """
        h = surf.get_height()
        if h <= 0:
            return surf
        ratio = target_h / h
        size = (max(1, round(surf.get_width() * ratio)), target_h)
        return pygame.transform.smoothscale(surf, size)

    @staticmethod
    def _path(unit_id: str, state: str) -> Path:
        # 待機は昔からの `{id}.png`。他のコマだけ `_windup` 等の接尾辞 ――
        # 攻撃コマを持たないユニットが大半なので、待機だけは無条件に
        # 同じファイル名で読めるようにしておく（過去の絵と互換）。
        suffix = "" if state == "idle" else f"_{state}"
        return ART / "out" / "units" / f"{unit_id}{suffix}.png"

    def _entry(self, spec: Unit, flip: bool, state: str = "idle"):
        key = (spec.id, flip, state)
        if key in self._cache:
            return self._cache[key]
        path = self._path(spec.id, state)
        if path.exists():
            surf = pygame.image.load(str(path)).convert_alpha()
        elif state != "idle":
            # このコマの絵が無ければ、待機の絵をそのまま使い回す
            # （＝コマ送り機能があっても、絵が1枚だけのユニットは静止のまま）。
            entry = self._entry(spec, flip, "idle")
            self._cache[key] = entry
            return entry
        else:
            surf = self._placeholder(spec)
        scale = (self._cost_scales.get(spec.id, 1.0)
                 * self._art_overrides.get(spec.id, 1.0))
        surf = self._grow(surf, max(1, round(UNIT_TARGET_H * scale)))
        if flip:
            surf = pygame.transform.flip(surf, True, False)
        # 元絵の余白ぶんを覚えておく。絵の実体がどこから始まるかを
        # 見ないと、体力の棒が頭の遥か上に浮く。
        entry = (surf, surf.get_bounding_rect())
        self._cache[key] = entry
        return entry

    def unit(self, spec: Unit, flip: bool, state: str = "idle") -> pygame.Surface:
        return self._entry(spec, flip, state)[0]

    def unit_bbox(self, spec: Unit, flip: bool, state: str = "idle") -> pygame.Rect:
        return self._entry(spec, flip, state)[1]

    def avatar(self, avatar_id: str, flip: bool) -> pygame.Surface | None:
        key = f"{avatar_id}:{flip}"
        if key not in self._avatars:
            path = ART / "out" / "avatars" / f"{avatar_id}.png"
            if not path.exists():
                return None
            surf = self._grow(pygame.image.load(str(path)).convert_alpha(),
                              AVATAR_TARGET_H)
            self._avatars[key] = (pygame.transform.flip(surf, True, False)
                                  if flip else surf)
        return self._avatars[key]

    def _placeholder(self, spec: Unit) -> pygame.Surface:
        """切り札には仮絵が無い（art/README.md 6章では96pxの別枠）。
        絵が無いだけで落ちないように、種族色の塊で代用する。"""
        size = 72
        surf = pygame.Surface((size, size), pygame.SRCALPHA)
        body = pygame.Rect(size // 6, size // 5, size * 2 // 3, size * 4 // 5)
        pygame.draw.rect(surf, self._races.get(spec.race, MUTED), body)
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
        self.sprites = Sprites(game)
        self.f_small = load_font(15)
        self.f_body = load_font(18)
        self.f_bold = load_font(20, bold=True)
        self.f_big = load_font(34, bold=True)
        self.f_num = load_font(24, bold=True)

        # ── 呪文の段：持ち込み1枠 ＋ ストック3枠 ＋ 切り札 ──────────
        slots = game.stock_slots
        self.spells = [Spell(pygame.Rect(66, SPELL_Y + 8, 196, 108),
                             ("brought", 0), pygame.K_q, "持ち込み")]
        for i in range(slots):
            self.spells.append(Spell(
                pygame.Rect(272 + i * 206, SPELL_Y + 8, 196, 108),
                ("stock", i), pygame.K_w + i, f"ストック{i + 1}"))
        self.trump_rect = pygame.Rect(W - 158, SPELL_Y + 8, 134, 108)
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

    def _row(self, spec: Unit) -> int:
        """奥行き。攻撃範囲から出すので、後衛が後ろに立つのが形で分かる。"""
        if spec.near > 0 or spec.far > self.game.far_threshold:
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

        # 目盛り。距離感が無いと射程の帯が読めない。レーンが伸びても
        # 本数が変わらないよう、刻みはレーン長から出す（8〜9本になる）。
        lane = battle.game.lane_length
        for metre in range(0, int(lane) + 1, grid_step(lane)):
            x = self.px(metre, lane)
            pygame.draw.line(self.surface, (58, 70, 83),
                             (x, GROUND_Y - 6), (x, GROUND_Y + 6))
            self._text(f"{metre}m", self.f_small, (86, 100, 114),
                       (x, GROUND_Y + 20), center=True)

        # **落雷の予告。** 落ちる位置が1.2秒前に見える（設計書1.2）――
        # 予告なしに全滅させる装置だと、読み合いではなく事故になる。
        for lands_at, where, radius in battle.pending:
            left = self.px(where - radius, lane)
            right = self.px(where + radius, lane)
            close = 1.0 - max(0.0, lands_at - battle.t) / max(battle.storm_warn, 1e-6)
            pygame.draw.rect(self.surface, RED,
                             (left, GROUND_Y - 150, right - left, 150), 2)
            self._bar(pygame.Rect(left, GROUND_Y - 158, right - left, 5),
                      close, RED, back=(18, 22, 27))

        for side in battle.sides:
            sprite = self.sprites.avatar(side.loadout.avatar, flip=side.index == 1)
            x = self.px(side.base_x, lane)
            if sprite:
                self.surface.blit(sprite, sprite.get_rect(midbottom=(x, GROUND_Y)))
            else:
                pygame.draw.rect(self.surface, MUTED,
                                 (x - 24, GROUND_Y - 96, 48, 96))

    @staticmethod
    def _depth_key(side: int, spawn_seq: int) -> int:
        """出撃時の位置から、重なったときの前後を決める。

        `Fighter.spawn_seq` は出撃した順に振られ、一生変わらない
        （`Side._spawn_seq`、`battle.py`）。**配列の添字は使わない** ――
        死んだ個体は `Battle.step` の最後で間引かれて `side.fighters` が
        作り直されるので、添字は誰かが死ぬたびにずれる。
        これをハッシュに通すだけで、シミュレータの乱数に一切触れずに
        見た目だけの前後を作れる（毎回同じ並びに固定されるのを避けるための
        ばらけさせ。同じユニットが並んでも壁のように単調に重ならない）。
        """
        h = (spawn_seq * 2654435761 + side * 0x9E3779B1) & 0xFFFFFFFF
        return h ^ (h >> 15)

    def _fighters(self, battle: Battle) -> None:
        lane = battle.game.lane_length
        # 奥の列から描く。列の中は出撃時に決まる前後で、手前のものを後に描く
        # （＝重なった部分は手前のキャラだけが見える）。
        for row in (2, 1, 0):
            entries = [
                (self._depth_key(f.side, f.spawn_seq), f)
                for side in battle.sides
                for f in side.fighters
                if f.alive and self._row(f.spec) == row
            ]
            entries.sort(key=lambda e: e[0])
            for _, f in entries:
                self._fighter(f, lane, row)

    def _fighter(self, f: Fighter, lane: float, row: int) -> None:
        mine = f.side == 0
        flip = not mine                    # 敵は左を向く
        state = _anim_state(f)
        sprite = self.sprites.unit(f.spec, flip, state)
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

        head = rect.top + self.sprites.unit_bbox(f.spec, flip, state).top
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

        # **後隙。** 振り切った直後、動けず被弾1.5倍になる時間（設計書2.3）。
        # 振りかぶりが金なのに対して赤 ―― 金は「来るぞ」、赤は「いまなら通る」。
        # ここが見えないと、大技への答えが「振らせて差し込む」にならない。
        elif f.exposed_left > 0:
            total = max(f.spec.attack_recover_sec, 1e-6)
            self._bar(pygame.Rect(x - 22, head - 17, 44, 5),
                      f.exposed_left / total, RED, back=(18, 22, 27))

        if f.stun_left > 0:
            pygame.draw.circle(self.surface, GOLD, (x, head - 24), 3)

    # -------------------------------------------------------------- 壁の一撃
    def _base_hits(self, battle: Battle) -> None:
        """壁（対拠点倍率が低いユニット）が拠点を殴っても、削れているように
        見えてしまう。数字を灰色にして「WALL」を添えるだけで、
        「これは前に出るだけで拠点を割れない」と0.5秒で学習できる（伝言1）。
        """
        lane = battle.game.lane_length
        for t, side_index, amount, is_wall in battle.base_hits:
            if not is_wall:
                continue
            age = battle.t - t
            if age > WALL_LABEL_SEC:
                continue
            side = battle.sides[side_index]
            x = self.px(side.base_x, lane)
            # 拠点（アバター）の絵の高さに合わせる。仮絵はいずれ差し替わるので、
            # 決め打ちの高さではなく実際のスプライトから出す（無ければ
            # `_field` の代替矩形と同じ96px）。
            sprite = self.sprites.avatar(side.loadout.avatar, flip=side.index == 1)
            top = GROUND_Y - (sprite.get_height() if sprite else 96)
            rise = int(20 * (age / WALL_LABEL_SEC))
            y = top - 24 - rise
            self._text("WALL", self.f_small, MUTED, (x, y), center=True)
            self._text(f"-{amount:.0f}", self.f_body, MUTED, (x, y + 18),
                       center=True)

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

            # 攻城中は、これから入るぶんを帯の先に薄く出す。**拠点は一撃で
            # 落ちない**（攻城口の上限）ので、削られている最中が見えないと
            # 「気付いたら0」に読めてしまう。押し返す時間があることを、
            # 押し返せるうちに知らせるための表示。
            queued = min(side.siege_backlog, hp)
            if queued > 0:
                edge = pygame.Rect(
                    bar.x + int(bar.w * max(0.0, (hp - queued) / full)), bar.y,
                    max(1, int(bar.w * queued / full)), bar.h)
                pygame.draw.rect(self.surface, GOLD, edge)
                self._text("攻城中", self.f_small, GOLD,
                           (bar.centerx, bar.bottom + 8), center=True)

        # 時計は「あと何秒で雷が降り始めるか」。時間切れは無い（設計書1.2）。
        if battle.sudden_death:
            self._text("落雷", self.f_num, RED, (W // 2, 26), center=True)
            self._text(f"{int(battle.t) // 60}:{int(battle.t) % 60:02d}",
                       self.f_small, MUTED, (W // 2, 50), center=True)
            # 配布は雷が降り始めるより前に必ず終わっている
            # （economy.milestonesはsudden_death_at_secより前に終わる。
            # validate.pyのcheck_sudden_deathが縛る）ので、ここでは出さない ――
            # 出しても常に空の「残り」が上の経過時間に重なるだけになる。
            return
        left = max(0.0, battle.storm_at - battle.t)
        self._text(f"{int(left) // 60}:{int(left) % 60:02d}", self.f_num, INK,
                   (W // 2, 26), center=True)
        self._text("落雷まで", self.f_small, MUTED, (W // 2, 50), center=True)

        # 次の配布。**両者に同額**なので「誰が取るか」は無い ―― 読ませたいのは
        # 「あと何秒でいくら入るか」だけ。配布の直前に使い切っておくか、が択。
        # 「落雷まで」と行を分ける（同じ高さに描くと両方とも読めなくなる）。
        drop = battle.next_drop()
        if drop is not None:
            seconds, amount = drop
            self._text(f"両者 +{amount}  あと{seconds:.0f}秒", self.f_small,
                       MUTED, (W // 2, 68), center=True)

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

        # 状態は上の隅。下2行は**何が起きる札なのか**の説明で埋める。
        note = card.band
        tint = MUTED
        if card.gated and not side.unlocked(card):
            note, tint = card.condition(), GOLD   # 押し込まれてから開く札
        elif left > 0:
            note = f"{left:.1f}秒"
        elif side.money < card.cost:
            note = "資金不足"
        self._text(note, self.f_small, tint, (rect.right - 8, rect.y + 13),
                   right=True)

        self._text(card.name, self.f_bold, INK if ready else MUTED,
                   (rect.centerx, rect.y + 38), center=True)
        self._text(f"{card.cost}", self.f_body, GOLD if ready else RULE,
                   (rect.centerx, rect.y + 60), center=True)

        # 文言は data には無く、apply の数字から組み立てたもの
        # （data.py の change / meaning）。数字と説明を両方 data に持つと、
        # 必ずどちらかがズレるので。
        self._text(card.change(), self.f_small, INK if ready else MUTED,
                   (rect.centerx, rect.y + 82), center=True)
        self._text(f"{card.duration_sec:g}秒 ― {card.meaning()}", self.f_small,
                   MUTED, (rect.centerx, rect.y + 98), center=True)

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
                   (rect.centerx, rect.y + 38), center=True)
        self._text(f"{spec.cost}", self.f_body, GOLD if ready else RULE,
                   (rect.centerx, rect.y + 62), center=True)
        note = f"{unlock - battle.t:.0f}秒後" if locked else (
            "資金不足" if side.money < spec.cost else "1試合1回")
        self._text(note, self.f_small, MUTED,
                   (rect.centerx, rect.bottom - 10), center=True)

    # ------------------------------------------------------ 操作盤：資金と召喚
    def _summon(self, battle: Battle, side: Side) -> None:
        # 資金は整数なので、**マス目で数えられる**ように描く。
        # 棒が滑らかに伸びるのではなく1マスずつ点くので、
        # 「あと2マスで臼砲」が目で分かる。上限は財布のレベルで 6〜46 と
        # 4倍以上動くので、マスの幅は入る数から決める。
        cap = int(side.money_cap)
        have = int(side.money)
        pitch = max(7, min(30, 760 // max(cap, 1)))
        cell, gap = pitch - 4, 4
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

    # -------------------------------------------------------------- 育成の演出
    def _training(self, battle: Battle, side: Side) -> None:
        """`_summon` の隅の小さな表示だけでは、初見だと「何秒間も何もできない」
        という負の体験しか残らない。育成中は画面中央に大きく残り秒数を出し、
        終わった瞬間は「財布 LvUP！」を出す（伝言1）。
        """
        # 育成が終わった直後の tick は「busy が外れる」のと「LvUP を記録する」が
        # 同時に起きる。片方だけを出す ―― 両方出すと文字が重なる。
        just_leveled = any(idx == side.index and battle.t - t <= TRAINING_POPUP_SEC
                           for t, idx, _level in battle.level_ups)

        if side.busy and not just_leveled:
            total = max(battle.game.economy["growth"]["upgrade_sec"], 1e-6)
            done = 1.0 - side.upgrading_left / total
            self._text(f"財布を育成中…  あと{side.upgrading_left:.1f}秒",
                       self.f_bold, GOLD, (W // 2, 148), center=True)
            self._bar(pygame.Rect(W // 2 - 130, 166, 260, 8), done, GOLD,
                      back=(18, 22, 27), border=RULE)

        for t, side_index, level in battle.level_ups:
            if side_index != side.index:
                continue
            age = battle.t - t
            if age > TRAINING_POPUP_SEC:
                continue
            self._text(f"財布 Lv{level} UP！", self.f_big, GREEN,
                       (W // 2, 148), center=True)

    # -------------------------------------------------------------- 呪文のフラッシュ
    def _cast_flash(self, battle: Battle, player: int) -> None:
        """バフ／デバフは数値が変わるだけで、画面には「何も起きていない」
        ように見えていた。発動の瞬間だけ画面端をその色で光らせる
        （青＝バフ／赤＝デバフ、伝言1）。
        """
        thickness = 18
        for t, target_index, is_buff in battle.cast_effects:
            if target_index != player:
                continue
            age = battle.t - t
            if age > CAST_FLASH_SEC:
                continue
            alpha = int(170 * (1.0 - age / CAST_FLASH_SEC))
            color = (*(BUFF if is_buff else RED), alpha)
            flash = pygame.Surface((W, H), pygame.SRCALPHA)
            for rect in (
                (0, 0, W, thickness), (0, H - thickness, W, thickness),
                (0, 0, thickness, H), (W - thickness, 0, thickness, H),
            ):
                pygame.draw.rect(flash, color, rect)
            self.surface.blit(flash, (0, 0))

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
    def draw(self, battle: Battle, player: int, paused: bool = False,
             speed: float = 1.0) -> None:
        side = battle.sides[player]
        self.surface.fill(BG)
        self._field(battle)
        self._fighters(battle)
        self._base_hits(battle)
        self._header(battle, player)
        self._spells(battle, side)
        self._summon(battle, side)
        self._training(battle, side)
        self._cast_flash(battle, player)
        # 早送りは常に出す。試合が拠点撃破まで続くので、いま何倍で見ているかが
        # 分からないと「長い試合」と「速く回している」の区別がつかない。
        if speed != 1.0:
            self._text(f"×{speed:g}", self.f_bold, GOLD, (W - 26, 92), right=True)
        if battle.finished():
            self._result(battle, player)
        elif paused:
            self._text("一時停止（Space）  速さ [ ]", self.f_bold, GOLD,
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
