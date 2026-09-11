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
const W = 1320, H = 792;
const GROUND_Y = 460;          // ユニットが立つ線。旧380から拡張 ―― 戦場をもっと広く
const HUD_Y = 492;             // ここから下が操作盤
const SPELL_Y = 498;           // 呪文の段。札には効果の説明まで載せるので背が高い
const SUMMON_Y = 628;          // 資金と召喚の段
const LANE_LEFT = 100, LANE_RIGHT = W - 100;
// 画面上の高さ（見た目の大きさ）をここで決める。**元絵の解像度は問わない。**
// view.py と同じ考え方 ―― 読み込んだ絵の実寸に合わせて、高さがここに来る
// よう縦横同倍率で縮尺をかける。
const UNIT_TARGET_H = 96;
const AVATAR_TARGET_H = 128;

// ---------------------------------------------------------------- 色
// art/palette.json と同じ出どころ。種族ごとの色はそちらが持つ。
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
const BUFF = '#5e9ce0';   // 呪文フラッシュの「バフ」側。デバフは既存の RED を使い回す

// 伝言1：数字はもう合っているが、何が起きたかが画面から伝わっていなかった。
// 3つとも仮の四角・テキストでいい代わりに、**エンジン側の直近イベント
// （battle.base_hits / level_ups / cast_effects）だけを見て描く** ――
// view.py と同じやり方（フレームをまたぐ状態は View 側に持たない）。
const TRAINING_POPUP_SEC = 1.2;   // 「財布 LvUP！」を出しておく秒数
const WALL_LABEL_SEC = 0.6;       // 「WALL」表示を出しておく秒数
const CAST_FLASH_SEC = 0.25;      // 画面端フラッシュの長さ

// 伝言2：**ノックバックが目で分からなかった**（設計書2.11・14章）。
// 後退は20m ―― 画面では93px。同じ93pxが巨兵には7.1秒で斥候鼠には2.1秒なので、
// 位置が変わったことだけでは事件の大きさが伝わらない。**どこから下がったか**（跡）と、
// **判定が消えていること**（Fighter.hittable）の2つを描く。view.py と同じ数字。
const KB_TRAIL_ALPHA = 0.65;      // 下がった跡の濃さ。硬直の残り時間ぶん薄くなる
const KB_TRAIL_H = 34;            // 跡の高さ（足元から）
const KB_GHOST_ALPHA = 0.43;      // 硬直中の本体。透けているのが「的ではない」の意

const JP = '"Zen Kaku Gothic New","Hiragino Kaku Gothic ProN","Yu Gothic",Meiryo,sans-serif';
const F_SMALL = `15px ${JP}`;
const F_BODY = `18px ${JP}`;
const F_BOLD = `700 20px ${JP}`;
const F_BIG = `900 34px ${JP}`;
const F_NUM = `700 24px ${JP}`;

// 目盛りの刻み。レーン長が変わっても本数がだいたい一定になるように。
function gridStep(lane) {
  return Math.max(20, Math.round(lane / 8 / 20) * 20);
}

// 数字を Python の :g と同じ見た目に（8.0 → 8）。
function fmt(x) {
  return String(Number(x));
}

// ---- カードの説明。data には持たせず、apply の数字から組み立てる ----
// data.py の STAT_LABELS / SCOPE_LABELS / STAT_MEANING と同じ表。
const STAT_LABELS = {
  attack: '攻撃力', attack_interval: '攻撃間隔', speed: '移動速度',
  knockback: 'ノックバック', cost: '出撃コスト',
  deploy_cooldown: '再出撃の待ち', income: '収入',
};
const SCOPE_LABELS = {
  own_units: '自軍', enemy_units: '敵軍', own_deploy: '自分の出撃',
  enemy_deploy: '敵の出撃', own_economy: '自分の財布',
  enemy_economy: '敵の財布',
};
const STAT_MEANING = {
  'attack:up': '殴りが強くなる', 'attack:down': '殴りが弱くなる',
  'attack_interval:up': '手数が減る', 'attack_interval:down': '手数が増える',
  'speed:up': '前線が上がる', 'speed:down': '足が止まる',
  'knockback:up': '押し戻されやすくなる',
  'knockback:down': '押し戻されにくくなる',
  'cost:up': '出撃が高くつく', 'cost:down': '安く出せる',
  'deploy_cooldown:up': '続けて出せなくなる',
  'deploy_cooldown:down': '続けて出せる',
  'income:up': '資金が速く貯まる', 'income:down': '資金が止まる',
};

function cardChange(card) {
  const stat = STAT_LABELS[card.apply.stat] || card.apply.stat;
  let who = SCOPE_LABELS[card.apply.scope] || card.apply.scope;
  if (card.race) who = `自軍の${card.race}`;
  if (card.apply.mult !== null) return `${who}の${stat} ×${fmt(card.apply.mult)}`;
  const add = card.apply.add || 0;
  return `${who}の${stat} ${add > 0 ? '+' : ''}${fmt(add)}`;
}

function cardMeaning(card) {
  const rises = card.apply.mult !== null
    ? card.apply.mult > 1.0 : (card.apply.add || 0) > 0;
  return STAT_MEANING[`${card.apply.stat}:${rises ? 'up' : 'down'}`] || '';
}

// data.py の Card.condition() と同じ。撃てる条件を1行にする。
function cardCondition(card) {
  const parts = [];
  if (card.base_hp_gate !== null) {
    parts.push(`自拠点 ${Math.round(card.base_hp_gate * 100)}% 以下`);
  }
  if (card.race) parts.push(`編成に${card.race}が${card.race_min}体以上`);
  return parts.length ? parts.join('・') + 'でだけ撃てる' : '';
}

const COST_SCALE_MIN = 0.7, COST_SCALE_MAX = 1.3;

// コストが高いほど大きく見せる ―― art/README.md 3章「コストが高い＝大きい。
// キャンバスを埋める」を実際の描画にも適用する。生の cost をそのまま比例
// させると安いユニットが大半を占める分布の下で高コスト側だけが伸びるので、
// ロースター内の順位（percentile）で正規化する（view.py と同じ考え方）。
function costScales(game) {
  const units = Object.values(game.units);
  const costs = units.map(u => u.cost).sort((a, b) => a - b);
  const denom = Math.max(costs.length - 1, 1);
  const rank = cost => costs.filter(c => c < cost).length / denom;
  const out = {};
  for (const u of units) {
    out[u.id] = COST_SCALE_MIN + rank(u.cost) * (COST_SCALE_MAX - COST_SCALE_MIN);
  }
  return out;
}

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

  // 元絵の余白ぶん（元絵のピクセル単位で焼き込んである）。絵の実体が
  // どこから始まるかを見ないと、体力の棒が頭の遥か上に浮く。表示は
  // 元絵の実寸に合わせた縮尺で行うので、ここも同じ縮尺（呼び出し側が
  // 実際に描画に使った高さ＝コストの掛け目込み）をかけ直す。
  bboxTop(id, targetH) {
    const top = this.art.bbox[id];
    if (top === undefined) return 0;
    const img = this.unit(id);
    const h = img && img.naturalHeight ? img.naturalHeight : targetH;
    return top * (targetH / h);
  }
}

// ---------------------------------------------------------------- 画面
class View {
  // sprites を渡すと（select.js が読み込み済みのものを使い回す場合など）
  // 二重に読み込まない。渡さなければ従来どおり自分で読み込む。
  constructor(ctx, roster, game, art, sprites) {
    this.ctx = ctx;
    this.game = game;
    this.sprites = sprites || new Sprites(art);
    this.races = art.races;
    this.costScales = costScales(game);

    // ── 呪文の段：持ち込み1枠 ＋ ストック3枠 ＋ 切り札 ──────────
    const slots = game.stockSlots;
    this.spells = [{
      rect: [66, SPELL_Y + 8, 196, 108], source: ['brought', 0],
      key: 'q', label: '持ち込み',
    }];
    const stockKeys = ['w', 'e', 'r'];
    for (let i = 0; i < slots; i++) {
      this.spells.push({
        rect: [272 + i * 206, SPELL_Y + 8, 196, 108], source: ['stock', i],
        key: stockKeys[i] || null, label: `ストック${i + 1}`,
      });
    }
    this.trumpRect = [W - 158, SPELL_Y + 8, 134, 108];

    // ── 召喚の段：財布 ＋ 出撃ボタン ─────────────────────────
    this.upgradeRect = [24, SUMMON_Y + 44, 118, 100];
    const span = W - 24 - 158;
    const width = Math.min(114, Math.floor(span / Math.max(roster.length, 1)) - 8);
    this.buttons = roster.map((spec, i) => ({
      rect: [158 + i * (width + 8), SUMMON_Y + 44, width, 100],
      spec, key: String(i + 1), label: String(i + 1),
    }));
  }

  ready() { return this.sprites._ready ? Promise.resolve() : this.sprites.load(); }

  // -------------------------------------------------------------- 座標
  px(xM, laneLength) {
    const span = LANE_RIGHT - LANE_LEFT;
    return Math.trunc(LANE_LEFT + (xM / laneLength) * span);
  }

  // 奥行き。攻撃範囲から出すので、後衛が後ろに立つのが形で分かる。
  row(spec) {
    if (spec.near > 0 || spec.far > this.game.farThreshold) return 2;
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

    // 目盛り。距離感が無いと射程の帯が読めない。レーンが伸びても
    // 本数が変わらないよう、刻みはレーン長から出す（view.py と同じ）。
    const lane = battle.game.laneLength;
    for (let metre = 0; metre <= lane; metre += gridStep(lane)) {
      const x = this.px(metre, lane);
      this.fill([x, GROUND_Y - 6, 1, 12], '#3a4653');
      this.text(`${metre}m`, F_SMALL, '#566472', x, GROUND_Y + 20, 'center');
    }

    // **落雷の予告。** 落ちる位置が1.2秒前に見える（view.py と同じ）。
    for (const bolt of battle.pending) {
      const l = this.px(bolt[1] - bolt[2], lane);
      const r = this.px(bolt[1] + bolt[2], lane);
      const close = 1.0 - Math.max(0.0, bolt[0] - battle.t)
                          / Math.max(battle.storm_warn, 1e-6);
      this.stroke([l, GROUND_Y - 150, r - l, 150], RED, 2);
      this.bar([l, GROUND_Y - 158, r - l, 5], close, RED, '#12161b');
    }

    for (const side of battle.sides) {
      const img = this.sprites.avatar(side.loadout.avatar);
      const x = this.px(side.base_x, lane);
      if (img && img.complete && img.naturalWidth) {
        const [w, h] = View.scaledSize(img, AVATAR_TARGET_H);
        this.blit(img, x - w / 2, GROUND_Y - h, w, h, side.index === 1);
      } else {
        this.fill([x - AVATAR_TARGET_H / 4, GROUND_Y - AVATAR_TARGET_H,
                   AVATAR_TARGET_H / 2, AVATAR_TARGET_H], MUTED);
      }
    }
  }

  // 元絵の実寸に関わらず、高さが targetH に来るよう縦横同倍率で拡縮した
  // ときの [幅, 高さ] を返す。view.py の _grow と同じ考え方。
  static scaledSize(img, targetH) {
    const h = img && img.naturalHeight ? img.naturalHeight : targetH;
    const w = img && img.naturalWidth ? img.naturalWidth : targetH;
    const ratio = targetH / h;
    return [Math.round(w * ratio), targetH];
  }

  // 絵を置く。flip のときだけ左右を返す。塗り絵調の絵を前提に滑らかに
  // 拡縮する（ドット絵前提の最近傍拡大はやめた ―― 縁がギザギザになるため）。
  blit(img, x, y, w, h, flip) {
    const ctx = this.ctx;
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
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

  // 出撃時の位置から、重なったときの前後を決める。`Fighter.spawn_seq` は
  // 出撃した順に振られ、一生変わらない（`Side._spawnSeq`、engine.js）。
  // **配列の添字は使わない** ―― 死んだ個体は間引かれて `side.fighters` が
  // 作り直されるので、添字は誰かが死ぬたびにずれる。これをハッシュに通す
  // だけで、シミュレータの乱数に一切触れずに見た目だけの前後を作れる
  // （view.py と同じ）。
  static depthKey(side, spawnSeq) {
    let h = (Math.imul(spawnSeq, 2654435761) + Math.imul(side, 0x9E3779B1)) >>> 0;
    return (h ^ (h >>> 15)) >>> 0;
  }

  fighters(battle) {
    const lane = battle.game.laneLength;
    // 奥の列から描く。列の中は出撃時に決まる前後で、手前のものを後に描く
    // （＝重なった部分は手前のキャラだけが見える）。
    for (const row of [2, 1, 0]) {
      const entries = [];
      for (const side of battle.sides) {
        for (const f of side.fighters) {
          if (f.alive && this.row(f.spec) === row) {
            entries.push([View.depthKey(f.side, f.spawn_seq), f]);
          }
        }
      }
      entries.sort((a, b) => a[0] - b[0]);
      for (const [, f] of entries) this.fighter(f, lane, row, battle);
    }
  }

  fighter(f, lane, row, battle) {
    const ctx = this.ctx;
    const mine = f.side === 0;
    const flip = !mine;                    // 敵は左を向く
    const img = this.sprites.unit(f.spec.id);
    const lift = row * 14;
    const x = this.px(f.x, lane);
    const feet = GROUND_Y - lift;
    const team = mine ? GREEN : RED;
    const scale = this.costScales[f.spec.id] || 1.0;
    const [w, h] = View.scaledSize(img, UNIT_TARGET_H * scale);
    const top = feet - h;
    const stunned = f.stun_left > 0;       // 下がった直後。判定が消えている

    // 下がった跡は本体より先に描く（下に敷く）。
    if (stunned) this.knockback(f, lane, x, feet, battle);

    // 足元の楕円1枚。にゃんこ大戦争のやり方をそのまま採る。
    // 影を陣営の色で塗ると、同じ絵でもどちら側かが一目で分かる。
    // **硬直中は塗らずに輪郭だけにする** ―― 塗り＝「ここに立っている的」、
    // 輪郭だけ＝「居るが、的ではない」（view.py と同じ）。
    ctx.save();
    ctx.beginPath();
    ctx.ellipse(x, feet - 2, w / 2, 7, 0, 0, Math.PI * 2);
    if (!stunned) {
      ctx.globalAlpha = 0.28;
      ctx.fillStyle = team;
      ctx.fill();
    }
    ctx.globalAlpha = 0.6;
    ctx.strokeStyle = stunned ? ACCENT : team;
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.restore();

    if (img && img.complete && img.naturalWidth) {
      ctx.save();
      if (f.summon_left > 0) ctx.globalAlpha = 0.35;   // 召喚演出のあいだは半透明
      else if (stunned) ctx.globalAlpha = KB_GHOST_ALPHA;   // 硬直中は的ではない
      this.blit(img, x - w / 2, top, w, h, flip);
      ctx.restore();
    } else {
      this.fill([x - 14, feet - 40, 28, 40],
                this.races[f.spec.race] || MUTED);
    }

    const head = top + this.sprites.bboxTop(f.spec.id, UNIT_TARGET_H * scale);
    if (f.hp < f.spec.hp) {
      this.hpBar([x - 22, head - 9, 44, 4], f, team, battle);
    }

    // 振りかぶり。設計書7.5の「大きい一撃は発生0.6秒以上」を画面に出す。
    // ここが見えないと、見切りの読み合いが嘘になる。
    if (f.windup_left > 0) {
      const total = Math.max(f.spec.attack_windup_sec, 1e-6);
      this.bar([x - 22, head - 17, 44, 5], 1.0 - f.windup_left / total,
               GOLD, '#12161b');
    } else if (f.exposed_left > 0) {
      // **後隙。** 金は「来るぞ」、赤は「いまなら通る」（設計書2.3）。
      const total = Math.max(f.spec.attack_recover_sec, 1e-6);
      this.bar([x - 22, head - 17, 44, 5], f.exposed_left / total,
               RED, '#12161b');
    }

    // **「いま無敵」。** 硬直中の0.4秒は殴られず、敵の足も止めない。
    // 足元の輪郭と半透明だけだと「そういう絵柄」にも見えるので言い切る。
    if (stunned) {
      this.text('無敵', F_SMALL, ACCENT, x, head - 28, 'center');
    }
  }

  // 体力の棒。**ノックバックの区切りを線で入れる。**
  //
  // 後退は「体力を kb 個に割った区切りを跨いだ瞬間」に起きる（設計書2.11）。
  // つまりこの線は *次にどこで下がるか* の予定表そのもの。`kb` は呪文の
  // かかった後の実効値なので、死守・踏破（ノックバック×0）が効いている
  // あいだは線が消える ―― 「いま押し戻せない相手」が形で分かる。
  hpBar(rect, f, team, battle) {
    this.bar(rect, f.hp / f.spec.hp, team, '#12161b');
    const side = battle.sides[f.side];
    const kb = side.stat('knockback', f.spec.knockback, f.spec.race);
    if (kb < 2) return;      // 1回＝跨ぐのは死ぬときだけ。線を引く意味が無い
    for (let i = 1; i < Math.trunc(kb); i++) {
      const at = rect[0] + Math.trunc(rect[2] * i / kb);
      this.fill([at, rect[1], 1, rect[3]], '#12161b');
    }
  }

  // **「いま下がった」を出す。**
  //
  // 後退そのものは20m ―― 画面では93px。位置の変化だけでは、それが7.1秒ぶん
  // なのか2.1秒ぶんなのか分からないので、**どこから下がったか**を跡で残す。跡の長さが
  // そのまま失った20mで、硬直の0.4秒のあいだ薄れながら消える。
  //
  // **View がフレームをまたぐ状態を持たない**という約束は守っている ――
  // 起点は `x + 向き × 後退距離` として盤面から出る。硬直中は動かないので、
  // この値は硬直のあいだ固定される。
  knockback(f, lane, x, feet, battle) {
    const ctx = this.ctx;
    const origin = this.px(
      Math.max(0.0, Math.min(lane, f.x + f.facing * battle.kb_distance)), lane);
    const fade = Math.max(0.0, Math.min(1.0, f.stun_left / Math.max(battle.kb_stun, 1e-6)));
    const left = Math.min(origin, x), right = Math.max(origin, x);
    const width = Math.max(2, right - left);
    const topY = feet - KB_TRAIL_H - 2;

    ctx.save();
    ctx.strokeStyle = ACCENT;
    // 横線を数本。密集していても「後ろに引かれた」向きだけは読める。
    ctx.globalAlpha = KB_TRAIL_ALPHA * fade * 0.5;
    ctx.lineWidth = 1;
    for (const y of [10, 18, 26]) {
      ctx.beginPath();
      ctx.moveTo(left, topY + y + 0.5);
      ctx.lineTo(left + width - 1, topY + y + 0.5);
      ctx.stroke();
    }
    // 起点の印 ―― 「ここに居た」。跡の端に立てる。
    ctx.globalAlpha = KB_TRAIL_ALPHA * fade;
    ctx.lineWidth = 2;
    const tick = (origin <= x ? left : left + width - 1) + 0.5;
    ctx.beginPath();
    ctx.moveTo(tick, topY + 2);
    ctx.lineTo(tick, topY + KB_TRAIL_H - 2);
    ctx.stroke();
    ctx.restore();
  }

  // -------------------------------------------------------------- 壁の一撃
  // 壁（対拠点倍率が低いユニット）が拠点を殴っても、削れているように見えて
  // しまう。数字を灰色にして「WALL」を添えるだけで、「これは前に出るだけ
  // で拠点を割れない」と0.5秒で学習できる（伝言1）。
  baseHits(battle) {
    const lane = battle.game.laneLength;
    for (const [t, sideIndex, amount, isWall] of battle.base_hits) {
      if (!isWall) continue;
      const age = battle.t - t;
      if (age > WALL_LABEL_SEC) continue;
      const side = battle.sides[sideIndex];
      const x = this.px(side.base_x, lane);
      // 拠点（アバター）の絵の高さに合わせる。仮絵はいずれ差し替わるので、
      // 決め打ちの高さではなく実際のスプライトから出す（無ければ
      // `field` の代替矩形と同じ96px）。
      const img = this.sprites.avatar(side.loadout.avatar);
      const h = (img && img.complete && img.naturalWidth)
        ? View.scaledSize(img, AVATAR_TARGET_H)[1] : AVATAR_TARGET_H;
      const top = GROUND_Y - h;
      const rise = Math.trunc(20 * (age / WALL_LABEL_SEC));
      const y = top - 24 - rise;
      this.text('WALL', F_SMALL, MUTED, x, y, 'center');
      this.text(`-${amount.toFixed(0)}`, F_BODY, MUTED, x, y + 18, 'center');
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

      // 攻城中は、これから入るぶんを帯の先に出す。**拠点は一撃で落ちない**
      // （攻城口の上限）ので、削られている最中が見えないと「気付いたら0」に
      // 読めてしまう。押し返す時間があることを、押し返せるうちに知らせる。
      const queued = Math.min(side.siege_backlog, hp);
      if (queued > 0) {
        this.fill([bar[0] + Math.trunc(bar[2] * Math.max(0.0, (hp - queued) / full)),
                   bar[1], Math.max(1, Math.trunc(bar[2] * queued / full)), bar[3]],
                  GOLD);
        this.text('攻城中', F_SMALL, GOLD,
                  bar[0] + bar[2] / 2, bar[1] + bar[3] + 8, 'center');
      }
    }

    // 時計は「あと何秒で雷が降り始めるか」。時間切れは無い（設計書1.2）。
    if (battle.suddenDeath) {
      this.text('落雷', F_NUM, RED, W / 2, 26, 'center');
      const em = Math.trunc(battle.t) / 60 | 0;
      const es = String(Math.trunc(battle.t) % 60).padStart(2, '0');
      this.text(`${em}:${es}`, F_SMALL, MUTED, W / 2, 50, 'center');
      // 配布は雷が降り始めるより前に必ず終わっている（validate.py の
      // check_sudden_death が縛る）ので、ここでは出さない ―― 出しても
      // 常に空の「残り」が上の経過時間に重なるだけになる（view.py と同じ）。
      return;
    }
    const left = Math.max(0.0, battle.storm_at - battle.t);
    const mm = Math.trunc(left) / 60 | 0;
    const ss = String(Math.trunc(left) % 60).padStart(2, '0');
    this.text(`${mm}:${ss}`, F_NUM, INK, W / 2, 26, 'center');
    this.text('落雷まで', F_SMALL, MUTED, W / 2, 50, 'center');

    // 次の配布。**両者に同額**なので「誰が取るか」は無い ―― 読ませたいのは
    // 「あと何秒でいくら入るか」だけ（view.py と同じ）。
    // 「落雷まで」と行を分ける（同じ高さに描くと両方とも読めなくなる）。
    const drop = battle.nextDrop();
    if (drop !== null) {
      this.text(`両者 +${drop[1]}  あと${drop[0].toFixed(0)}秒`, F_SMALL, MUTED,
                W / 2, 68, 'center');
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

    // 状態は上の隅。下2行は**何が起きる札なのか**の説明で埋める。
    let note = card.band, tint = MUTED;
    if (card.base_hp_gate !== null && !side.unlocked(card)) {
      note = cardCondition(card); tint = GOLD;   // 押し込まれてから開く札
    } else if (left > 0) note = `${left.toFixed(1)}秒`;
    else if (side.money < card.cost) note = '資金不足';
    this.text(note, F_SMALL, tint, rect[0] + rect[2] - 8, rect[1] + 13, 'right');

    this.text(card.name, F_BOLD, ready ? INK : MUTED, cx, rect[1] + 38, 'center');
    this.text(String(card.cost), F_BODY, ready ? GOLD : RULE, cx,
              rect[1] + 60, 'center');

    // 文言は data には無く、apply の数字から組み立てたもの
    // （cardChange / cardMeaning）。
    this.text(cardChange(card), F_SMALL, ready ? INK : MUTED, cx,
              rect[1] + 82, 'center');
    this.text(`${fmt(card.duration_sec)}秒 ― ${cardMeaning(card)}`, F_SMALL,
              MUTED, cx, rect[1] + 98, 'center');
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
    // 資金は整数なので、**マス目で数えられる**ように描く。
    // 棒が滑らかに伸びるのではなく1マスずつ点くので、
    // 「あと2マスで臼砲」が目で分かる。上限は財布のレベルで4倍以上動くので、
    // マスの幅は入る数から決める（view.py と同じ式）。
    const cap = Math.trunc(side.money_cap);
    const have = Math.trunc(side.money);
    const pitch = Math.max(7, Math.min(30, Math.trunc(760 / Math.max(cap, 1))));
    const cell = pitch - 4, gap = 4;
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

  // -------------------------------------------------------------- 育成の演出
  // `summonRow` の隅の小さな表示だけでは、初見だと「何秒間も何もできない」と
  // いう負の体験しか残らない。育成中は画面中央に大きく残り秒数を出し、
  // 終わった瞬間は「財布 LvUP！」を出す（伝言1）。
  training(battle, side) {
    // 育成が終わった直後の tick は「busy が外れる」のと「LvUP を記録する」が
    // 同時に起きる。片方だけを出す ―― 両方出すと文字が重なる。
    const justLeveled = battle.level_ups.some(([t, idx]) =>
      idx === side.index && battle.t - t <= TRAINING_POPUP_SEC);

    if (side.busy && !justLeveled) {
      const total = Math.max(battle.game.economy.growth.upgrade_sec, 1e-6);
      const done = 1.0 - side.upgrading_left / total;
      this.text(`財布を育成中…  あと${side.upgrading_left.toFixed(1)}秒`,
                F_BOLD, GOLD, W / 2, 148, 'center');
      this.bar([W / 2 - 130, 166, 260, 8], done, GOLD, '#12161b', RULE);
    }

    for (const [t, sideIndex, level] of battle.level_ups) {
      if (sideIndex !== side.index) continue;
      const age = battle.t - t;
      if (age > TRAINING_POPUP_SEC) continue;
      this.text(`財布 Lv${level} UP！`, F_BIG, GREEN, W / 2, 148, 'center');
    }
  }

  // -------------------------------------------------------------- 呪文のフラッシュ
  // バフ／デバフは数値が変わるだけで、画面には「何も起きていない」ように
  // 見えていた。発動の瞬間だけ画面端をその色で光らせる
  // （青＝バフ／赤＝デバフ、伝言1）。
  castFlash(battle, player) {
    const ctx = this.ctx;
    const thickness = 18;
    for (const [t, targetIndex, isBuff] of battle.cast_effects) {
      if (targetIndex !== player) continue;
      const age = battle.t - t;
      if (age > CAST_FLASH_SEC) continue;
      ctx.save();
      ctx.globalAlpha = 0.67 * (1.0 - age / CAST_FLASH_SEC);   // 170/255
      ctx.fillStyle = isBuff ? BUFF : RED;
      ctx.fillRect(0, 0, W, thickness);
      ctx.fillRect(0, H - thickness, W, thickness);
      ctx.fillRect(0, 0, thickness, H);
      ctx.fillRect(W - thickness, 0, thickness, H);
      ctx.restore();
    }
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
    this.baseHits(battle);
    this.header(battle, player);
    this.spellRow(battle, battle.sides[player]);
    this.summonRow(battle, battle.sides[player]);
    this.training(battle, battle.sides[player]);
    this.castFlash(battle, player);
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
