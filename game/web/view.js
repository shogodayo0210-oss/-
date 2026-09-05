// play/view.py の移植。Canvas に1フレーム描くだけで、盤面は書き換えない。
//
// engine.js は画面のことを何ひとつ知らない。ここが唯一その二つを繋ぐ場所で、
// **逆向きの依存は作らない** ―― Python 版と同じ約束。
//
// 寸法・色・並びは view.py と同じ数字を使っている。片方だけ動かすと
// 「手元で見た絵」と「Webで見た絵」が別物になるので。

'use strict';

// ---------------------------------------------------------------- 画面の寸法
// にゃんこ大戦争と同じ並び ―― 上が戦場、下が操作盤。
const W = 1140, H = 712;
const GROUND_Y = 400;          // ユニットが立つ線
const HUD_Y = 434;             // ここから下が操作盤
const SPELL_Y = 440;           // 呪文の段
const SUMMON_Y = 548;          // 資金と召喚の段
const LANE_LEFT = 100, LANE_RIGHT = W - 100;
const SCALE = 2;               // 仮絵は48px。等倍だと画面に対して小さすぎる

// ---------------------------------------------------------------- 色
// art/palette.json と同じ出どころ。機械=水色、人=金、精霊=青緑、獣=橙。
const BG = '#171c22';
const SKY = '#1e2731';
const GROUND = '#252f3a';
const INK = '#dfe6ec';
const MUTED = '#7d8d9c';
const RULE = '#2b343e';
const PANEL = '#1b232c';
const ACCENT = '#3ecad9';
const GOLD = '#e0aa46';
const GREEN = '#4fa196';
const RED = '#e2622f';

const JP = '"Zen Kaku Gothic New","Hiragino Kaku Gothic ProN","Yu Gothic",Meiryo,sans-serif';
const F_SMALL = `15px ${JP}`;
const F_BODY = `18px ${JP}`;
const F_BOLD = `700 20px ${JP}`;
const F_BIG = `900 34px ${JP}`;
const F_NUM = `700 24px ${JP}`;

// ---------------------------------------------------------------- 絵
// PNG は data: URI で焼き込んである（build_web.py）。向きごとに使い回す。
class Sprites {
  constructor(art) {
    this.art = art;                 // {units:{id:dataURI}, avatars:{...}, bbox:{id:top}}
    this._cache = new Map();
    this._ready = false;
  }

  // 画像の読み込みが終わるまで待つ。終わるまでは色の塊で代用する。
  load() {
    const jobs = [];
    const take = (kind, id, src) => {
      const img = new Image();
      const done = new Promise(res => { img.onload = res; img.onerror = res; });
      img.src = src;
      this._cache.set(`${kind}:${id}`, img);
      jobs.push(done);
    };
    for (const id in this.art.units) take('unit', id, this.art.units[id]);
    for (const id in this.art.avatars) take('avatar', id, this.art.avatars[id]);
    return Promise.all(jobs).then(() => { this._ready = true; });
  }

  unit(id) { return this._cache.get(`unit:${id}`); }
  avatar(id) { return this._cache.get(`avatar:${id}`); }

  // 48×48 の余白ぶん。絵の実体がどこから始まるかを見ないと、
  // 体力の棒が頭の遥か上に浮く。
  bboxTop(id) {
    const top = this.art.bbox[id];
    return (top === undefined ? 0 : top) * SCALE;
  }
}

// ---------------------------------------------------------------- 画面
class View {
  constructor(ctx, roster, game, art) {
    this.ctx = ctx;
    this.game = game;
    this.sprites = new Sprites(art);
    this.families = art.families;

    // ── 呪文の段：持ち込み1枠 ＋ ストック3枠 ＋ 切り札 ──────────
    const slots = game.stockSlots;
    this.spells = [{
      rect: [66, SPELL_Y + 8, 158, 92], source: ['brought', 0],
      key: 'q', label: '持ち込み',
    }];
    const stockKeys = ['w', 'e', 'r'];
    for (let i = 0; i < slots; i++) {
      this.spells.push({
        rect: [240 + i * 168, SPELL_Y + 8, 158, 92], source: ['stock', i],
        key: stockKeys[i] || null, label: `ストック${i + 1}`,
      });
    }
    this.trumpRect = [W - 182, SPELL_Y + 8, 158, 92];

    // ── 召喚の段：財布 ＋ 出撃ボタン ─────────────────────────
    this.upgradeRect = [24, SUMMON_Y + 44, 118, 100];
    const span = W - 24 - 158;
    const width = Math.min(114, Math.floor(span / Math.max(roster.length, 1)) - 8);
    this.buttons = roster.map((spec, i) => ({
      rect: [158 + i * (width + 8), SUMMON_Y + 44, width, 100],
      spec, key: String(i + 1), label: String(i + 1),
    }));
  }

  ready() { return this.sprites.load(); }

  // -------------------------------------------------------------- 座標
  px(xM, laneLength) {
    const span = LANE_RIGHT - LANE_LEFT;
    return Math.trunc(LANE_LEFT + (xM / laneLength) * span);
  }

  // 奥行き。攻撃範囲から出すので、後衛が後ろに立つのが形で分かる。
  static row(spec) {
    if (spec.near > 0 || spec.far > 50) return 2;
    if (spec.far > 20) return 1;
    return 0;
  }

  // -------------------------------------------------------------- 部品
  fill(rect, color) {
    this.ctx.fillStyle = color;
    this.ctx.fillRect(rect[0], rect[1], rect[2], rect[3]);
  }

  stroke(rect, color, width) {
    this.ctx.strokeStyle = color;
    this.ctx.lineWidth = width || 1;
    // 1px の線をぼかさないよう半ピクセルずらす
    const o = (width || 1) / 2;
    this.ctx.strokeRect(rect[0] + o, rect[1] + o, rect[2] - o * 2, rect[3] - o * 2);
  }

  text(str, font, color, x, y, align) {
    const ctx = this.ctx;
    ctx.font = font;
    ctx.fillStyle = color;
    ctx.textAlign = align || 'left';
    ctx.textBaseline = 'middle';
    ctx.fillText(str, x, y);
  }

  bar(rect, ratio, color, back, border) {
    this.fill(rect, back || RULE);
    const w = Math.trunc(rect[2] * Math.max(0.0, Math.min(1.0, ratio)));
    if (w > 0) this.fill([rect[0], rect[1], w, rect[3]], color);
    if (border) this.stroke(rect, border, 1);
  }

  // -------------------------------------------------------------- 場
  field(battle) {
    const ctx = this.ctx;
    this.fill([0, 0, W, GROUND_Y], SKY);
    this.fill([0, GROUND_Y, W, HUD_Y - GROUND_Y], GROUND);
    this.fill([0, GROUND_Y, W, 1], RULE);

    // 20mごとの目盛り。距離感が無いと射程の帯が読めない。
    const lane = battle.game.laneLength;
    for (let metre = 0; metre <= lane; metre += 20) {
      const x = this.px(metre, lane);
      this.fill([x, GROUND_Y - 6, 1, 12], '#3a4653');
      this.text(`${metre}m`, F_SMALL, '#566472', x, GROUND_Y + 20, 'center');
    }

    for (const side of battle.sides) {
      const img = this.sprites.avatar(side.loadout.avatar);
      const x = this.px(side.base_x, lane);
      if (img && img.complete && img.naturalWidth) {
        const w = img.naturalWidth * SCALE, h = img.naturalHeight * SCALE;
        this.blit(img, x - w / 2, GROUND_Y - h, w, h, side.index === 1);
      } else {
        this.fill([x - 24, GROUND_Y - 96, 48, 96], MUTED);
      }
    }
  }

  // 仮絵をドットのまま拡大して置く。flip のときだけ左右を返す。
  blit(img, x, y, w, h, flip) {
    const ctx = this.ctx;
    ctx.imageSmoothingEnabled = false;
    if (flip) {
      ctx.save();
      ctx.translate(x + w, y);
      ctx.scale(-1, 1);
      ctx.drawImage(img, 0, 0, w, h);
      ctx.restore();
    } else {
      ctx.drawImage(img, x, y, w, h);
    }
  }

  fighters(battle) {
    const lane = battle.game.laneLength;
    // 奥の列から描く。前に立つものが手前に重なる。
    for (const row of [2, 1, 0]) {
      for (const side of battle.sides) {
        for (const f of side.fighters) {
          if (!f.alive || View.row(f.spec) !== row) continue;
          this.fighter(f, lane, row);
        }
      }
    }
  }

  fighter(f, lane, row) {
    const ctx = this.ctx;
    const mine = f.side === 0;
    const flip = !mine;                    // 敵は左を向く
    const img = this.sprites.unit(f.spec.id);
    const lift = row * 14;
    const x = this.px(f.x, lane);
    const feet = GROUND_Y - lift;
    const team = mine ? GREEN : RED;
    const w = (img && img.naturalWidth ? img.naturalWidth : 48) * SCALE;
    const h = (img && img.naturalHeight ? img.naturalHeight : 48) * SCALE;
    const top = feet - h;

    // 足元の楕円1枚。にゃんこ大戦争のやり方をそのまま採る。
    // 影を陣営の色で塗ると、同じ絵でもどちら側かが一目で分かる。
    ctx.save();
    ctx.globalAlpha = 0.28;
    ctx.fillStyle = team;
    ctx.beginPath();
    ctx.ellipse(x, feet - 2, w / 2, 7, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.globalAlpha = 0.6;
    ctx.strokeStyle = team;
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.restore();

    if (img && img.complete && img.naturalWidth) {
      ctx.save();
      if (f.summon_left > 0) ctx.globalAlpha = 0.35;   // 召喚演出のあいだは半透明
      this.blit(img, x - w / 2, top, w, h, flip);
      ctx.restore();
    } else {
      this.fill([x - 14, feet - 40, 28, 40],
                this.families[f.spec.family] || MUTED);
    }

    const head = top + this.sprites.bboxTop(f.spec.id);
    if (f.hp < f.spec.hp) {
      this.bar([x - 22, head - 9, 44, 4], f.hp / f.spec.hp, team, '#12161b');
    }

    // 振りかぶり。設計書7.5の「大きい一撃は発生0.6秒以上」を画面に出す。
    // ここが見えないと、見切りの読み合いが嘘になる。
    if (f.windup_left > 0) {
      const total = Math.max(f.spec.attack_windup_sec, 1e-6);
      this.bar([x - 22, head - 17, 44, 5], 1.0 - f.windup_left / total,
               GOLD, '#12161b');
    }

    if (f.stun_left > 0) {
      ctx.fillStyle = GOLD;
      ctx.beginPath();
      ctx.arc(x, head - 24, 3, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  // -------------------------------------------------------------- 拠点HP
  header(battle, player) {
    this.fill([0, 0, W, 68], PANEL);
    this.fill([0, 68, W, 1], RULE);
    const full = battle.game.baseHp;

    for (const side of battle.sides) {
      const mine = side.index === player;
      const hp = Math.max(0.0, side.base_hp);
      const avatar = battle.game.avatars[side.loadout.avatar];
      const name = `${mine ? '自陣' : '敵陣'}  ${avatar.name}`;
      const color = mine ? GREEN : RED;
      const shown = Math.round(hp).toLocaleString('en-US');

      let bar;
      if (mine) {
        bar = [26, 32, 330, 20];
        this.text(name, F_SMALL, MUTED, 26, 18);
        this.text(shown, F_BODY, INK, bar[0] + bar[2] + 12, 42);
      } else {
        bar = [W - 356, 32, 330, 20];
        this.text(name, F_SMALL, MUTED, W - 26, 18, 'right');
        this.text(shown, F_BODY, INK, bar[0] - 12, 42, 'right');
      }
      this.bar(bar, hp / full, color, RULE, RULE);
    }

    const left = Math.max(0.0, battle.game.timeLimit - battle.t);
    const mm = Math.trunc(left) / 60 | 0;
    const ss = String(Math.trunc(left) % 60).padStart(2, '0');
    this.text(`${mm}:${ss}`, F_NUM, INK, W / 2, 26, 'center');

    // 次の配布。陣地ボーナスは**いま押し込んでいる側だけ**に入るので、
    // 誰が取りそうかを出す ―― これが見えないと、取りに行く判断ができない。
    const drop = battle.nextDrop();
    if (drop === null) {
      this.text('残り', F_SMALL, MUTED, W / 2, 50, 'center');
      return;
    }
    const seconds = drop[0], amount = drop[1];
    if (battle.nextDropIsContested()) {
      const lead = battle.leader();
      let who, tint;
      if (lead === null) { who = '互角'; tint = MUTED; }
      else if (lead.index === player) { who = '自分が優勢'; tint = GREEN; }
      else { who = '相手が優勢'; tint = RED; }
      this.text(`陣地 +${amount}  あと${seconds.toFixed(0)}秒`, F_SMALL, GOLD,
                W / 2, 48, 'center');
      this.text(who, F_SMALL, tint, W / 2, 64, 'center');
    } else {
      this.text(`両者 +${amount}  あと${seconds.toFixed(0)}秒`, F_SMALL, MUTED,
                W / 2, 52, 'center');
    }
  }

  // ---------------------------------------------------------- 操作盤：呪文
  spellRow(battle, side) {
    this.fill([0, HUD_Y, W, H - HUD_Y], PANEL);
    this.fill([0, HUD_Y, W, 1], RULE);
    this.text('呪文', F_SMALL, MUTED, 22, SPELL_Y + 44);
    for (const slot of this.spells) this.spell(slot, battle, side);
    this.trump(battle, side);
  }

  spell(slot, battle, side) {
    const rect = slot.rect;
    const card = side.cardOf(slot.source);
    const ready = side.castable(slot.source);
    const kind = slot.source[0], index = slot.source[1];
    const cx = rect[0] + rect[2] / 2;

    this.fill(rect, ready ? '#212b36' : '#181f27');

    // 空きストックは下から補充されていく。持ち込みは自分のクールタイム。
    let left = 0.0, total = 0.0;
    if (kind === 'stock' && !side.stock[index]) {
      left = side.restock[index]; total = side.restock_sec;
    } else if (kind === 'brought') {
      left = side.brought_cd; total = this.game.cards[side.brought].cooldown_sec;
    }
    if (left > 0) {
      const h = Math.trunc(rect[3] * Math.min(1.0, left / Math.max(total, 1e-6)));
      this.fill([rect[0], rect[1] + rect[3] - h, rect[2], h], '#121a1e');
    }

    const edge = kind === 'brought' ? GOLD : (ready ? ACCENT : RULE);
    this.stroke(rect, edge, 2);
    this.text(slot.label, F_SMALL, edge, rect[0] + 8, rect[1] + 13);

    if (card === null) {
      this.text('補充中', F_BODY, MUTED, cx, rect[1] + rect[3] / 2, 'center');
      this.text(`${left.toFixed(1)}秒`, F_SMALL, MUTED, cx,
                rect[1] + rect[3] - 14, 'center');
      return;
    }

    this.text(card.name, F_BOLD, ready ? INK : MUTED, cx, rect[1] + 38, 'center');
    this.text(String(card.cost), F_BODY, ready ? GOLD : RULE, cx,
              rect[1] + 62, 'center');
    let note = card.band;
    if (left > 0) note = `${left.toFixed(1)}秒`;
    else if (side.money < card.cost) note = '資金不足';
    this.text(note, F_SMALL, MUTED, cx, rect[1] + rect[3] - 10, 'center');
  }

  trump(battle, side) {
    const rect = this.trumpRect;
    const spec = this.game.trumps[side.loadout.trump];
    const unlock = this.game.trumpRules.unlock_at_sec;
    const locked = battle.t < unlock;
    const ready = !side.trump_used && !locked && side.money >= spec.cost
                  && !side.busy;
    const cx = rect[0] + rect[2] / 2;

    this.fill(rect, ready ? '#241e16' : '#181f27');
    this.stroke(rect, ready ? GOLD : RULE, 2);
    this.text('切り札', F_SMALL, ready ? GOLD : MUTED, rect[0] + 8, rect[1] + 13);
    if (side.trump_used) {
      this.text('使用済み', F_BODY, MUTED, cx, rect[1] + rect[3] / 2, 'center');
      return;
    }
    this.text(spec.name, F_BOLD, ready ? INK : MUTED, cx, rect[1] + 38, 'center');
    this.text(String(spec.cost), F_BODY, ready ? GOLD : RULE, cx,
              rect[1] + 62, 'center');
    const note = locked ? `${(unlock - battle.t).toFixed(0)}秒後`
      : (side.money < spec.cost ? '資金不足' : '1試合1回');
    this.text(note, F_SMALL, MUTED, cx, rect[1] + rect[3] - 10, 'center');
  }

  // ------------------------------------------------------ 操作盤：資金と召喚
  summonRow(battle, side) {
    // 資金は1〜14の整数なので、**マス目で数えられる**ように描く。
    // 棒が滑らかに伸びるのではなく1マスずつ点くので、
    // 「あと2マスで臼砲」が目で分かる。
    const cap = Math.trunc(side.money_cap);
    const have = Math.trunc(side.money);
    const cell = 26, gap = 4;
    for (let i = 0; i < cap; i++) {
      const box = [24 + i * (cell + gap), SUMMON_Y, cell, 26];
      this.fill(box, i < have ? GOLD : '#1e262f');
      this.stroke(box, RULE, 1);
    }

    const right = 24 + cap * (cell + gap);
    this.text(`${have} / ${cap}`, F_NUM, INK, right + 12, SUMMON_Y + 13);
    this.text(`財布 Lv${side.level}   ${side.income_amount.toFixed(0)} / `
              + `${side.income_every.toFixed(1)}秒`,
              F_SMALL, MUTED, right + 88, SUMMON_Y + 13);
    if (side.busy) {
      this.text(`育成中 ${side.upgrading_left.toFixed(1)}秒 — 何も出せない`,
                F_SMALL, RED, right + 250, SUMMON_Y + 13);
    }

    this.upgrade(side);
    for (const button of this.buttons) this.button(button, side);
  }

  upgrade(side) {
    const rect = this.upgradeRect;
    const cost = side.upgrade_cost;
    const ready = cost !== null && side.canUpgrade() && !side.busy;
    const cx = rect[0] + rect[2] / 2;

    this.fill(rect, ready ? '#1a2828' : '#181f27');
    this.stroke(rect, ready ? GREEN : RULE, 2);
    this.text('0', F_SMALL, ready ? GREEN : MUTED, rect[0] + 8, rect[1] + 13);
    this.text('財布', F_BOLD, ready ? INK : MUTED, cx, rect[1] + 38, 'center');
    if (cost === null) {
      this.text('最大', F_BODY, MUTED, cx, rect[1] + 62, 'center');
      return;
    }
    this.text(String(cost), F_BODY, ready ? GREEN : RULE, cx, rect[1] + 62, 'center');
    this.text(`Lv${side.level + 1} へ`, F_SMALL, MUTED, cx,
              rect[1] + rect[3] - 13, 'center');
  }

  button(button, side) {
    const rect = button.rect;
    const cd = side.deploy_cd[button.spec.id] || 0.0;
    const cost = side.unitCost(button.spec);
    const overCap = cost > side.money_cap;        // 財布のレベルが足りない
    const blocked = this.blockedBy(button, side);
    const ready = blocked === null && cd <= 0;
    const cx = rect[0] + rect[2] / 2;

    this.fill(rect, ready ? '#212b36' : '#181f27');
    if (cd > 0) {                    // 再出撃までを下から塗り戻す
      const total = Math.max(side.deployCooldown(button.spec), 1e-6);
      const h = Math.trunc(rect[3] * Math.min(1.0, cd / total));
      this.fill([rect[0], rect[1] + rect[3] - h, rect[2], h], '#121a1e');
    }

    const edge = overCap ? RED : (ready ? ACCENT : RULE);
    this.stroke(rect, edge, 2);
    this.text(button.label, F_SMALL, edge, rect[0] + 8, rect[1] + 13);
    this.text(button.spec.name, F_BOLD, ready ? INK : MUTED, cx,
              rect[1] + 38, 'center');
    this.text(cost.toFixed(0), F_BODY, ready ? GOLD : RULE, cx,
              rect[1] + 62, 'center');

    let note = '';
    if (overCap) note = '財布 Lv不足';
    else if (cd > 0) note = `${cd.toFixed(1)}秒`;
    else note = blocked || '';
    if (note) {
      this.text(note, F_SMALL, overCap ? RED : MUTED, cx,
                rect[1] + rect[3] - 13, 'center');
    }
  }

  // 押せない理由。押せるなら null（view.py の Button.blocked_by と同じ）。
  blockedBy(button, side) {
    if (side.busy) return '育成中';
    if (side.deploy_lock_left > 0) return '硬直';
    if ((side.deploy_cd[button.spec.id] || 0.0) > 0) return null;
    if (side.money < side.unitCost(button.spec)) return '資金不足';
    return null;
  }

  // -------------------------------------------------------------- 決着
  result(battle, player) {
    const ctx = this.ctx;
    ctx.save();
    ctx.fillStyle = 'rgba(10,14,18,0.75)';
    ctx.fillRect(0, 0, W, HUD_Y);
    ctx.restore();

    const r = ENGINE.resultOf(battle);
    let headline, color;
    if (r.winner === null) { headline = '引き分け'; color = MUTED; }
    else if (r.winner === player) { headline = '勝ち'; color = ACCENT; }
    else { headline = '負け'; color = RED; }

    this.text(headline, F_BIG, color, W / 2, 190, 'center');
    this.text(r.reason, F_BODY, INK, W / 2, 232, 'center');
    this.text(`${r.seconds.toFixed(0)}秒`, F_SMALL, MUTED, W / 2, 258, 'center');
    this.text('R でもう1回', F_SMALL, MUTED, W / 2, 296, 'center');
  }

  // -------------------------------------------------------------- 1フレーム
  draw(battle, player, paused) {
    this.fill([0, 0, W, H], BG);
    this.field(battle);
    this.fighters(battle);
    this.header(battle, player);
    this.spellRow(battle, battle.sides[player]);
    this.summonRow(battle, battle.sides[player]);
    if (battle.finished()) this.result(battle, player);
    else if (paused) {
      this.text('一時停止（Space）', F_BOLD, GOLD, W / 2, 120, 'center');
    }
  }

  // ------------------------------------------------------------ 当たり判定
  // クリックとキーを同じ「操作」に畳んで返す。呼ぶ側は中身を知らなくていい。
  static hit(rect, x, y) {
    return x >= rect[0] && x < rect[0] + rect[2]
        && y >= rect[1] && y < rect[1] + rect[3];
  }

  actionAt(x, y) {
    if (View.hit(this.upgradeRect, x, y)) return ['upgrade', null];
    if (View.hit(this.trumpRect, x, y)) return ['trump', null];
    for (const slot of this.spells) {
      if (View.hit(slot.rect, x, y)) return ['cast', slot.source];
    }
    for (const button of this.buttons) {
      if (View.hit(button.rect, x, y)) return ['deploy', button.spec.id];
    }
    return null;
  }

  actionForKey(key) {
    if (key === '0') return ['upgrade', null];
    if (key === 't') return ['trump', null];
    for (const slot of this.spells) {
      if (slot.key === key) return ['cast', slot.source];
    }
    for (const button of this.buttons) {
      if (button.key === key) return ['deploy', button.spec.id];
    }
    return null;
  }
}

const VIEW = { View, Sprites, W, H, HUD_Y, GROUND_Y };
if (typeof module !== 'undefined' && module.exports) module.exports = VIEW;
if (typeof globalThis !== 'undefined') globalThis.VIEW = VIEW;
