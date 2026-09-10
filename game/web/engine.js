// engine/ の移植。battle.py / data.py / policy.py / human.py と同じ振る舞いをする。
//
// **数値はひとつもここに書かない。** 全部 DATA（game/data/*.json）から来る。
// Python 版が正で、この移植が合っているかは game/tools/conform.py が
// 1tickずつ突き合わせて確かめる ―― 実装が2つある以上、
// 「たぶん同じ」では意味がないので。
//
// 浮動小数点は両方とも IEEE754 の倍精度で、演算の順序も同じに揃えてある。
// 並べ替えは Python の sorted も JS の sort も安定なので、同着の順も一致する。

'use strict';

// 位置の比較に使う許容差。左右のユニットは逆向きに動くので、同じ地点でも
// 浮動小数点の下位桁が一致しない（battle.py と同じ理由・同じ値）。
const EPS = 1e-6;

// --------------------------------------------------------------- 決定論的な乱数
// **Python と JS で1ビットも違わない乱数が要る**（battle.py の Rng と同じ）。
// Math.imul と >>> 0 で32ビット演算を Python の & 0xFFFFFFFF に合わせる。
function seed32(text) {
  let h = 2166136261 >>> 0;
  for (const byte of new TextEncoder().encode(text)) {
    h = Math.imul(h ^ byte, 16777619) >>> 0;
  }
  return h || 1;
}

class Rng {
  constructor(seed) { this.state = (seed >>> 0) || 1; }

  next() {
    let x = this.state;
    x = (x ^ (x << 13)) >>> 0;
    x = (x ^ (x >>> 17)) >>> 0;
    x = (x ^ (x << 5)) >>> 0;
    this.state = x;
    return x;
  }

  // 0以上1未満。倍精度なので Python と同じ値になる。
  unit() { return this.next() / 4294967296.0; }
}

// ------------------------------------------------------------------ 二分探索
// Python の bisect と同じ意味。ソート済みの配列に対してのみ使う。
function bisectLeft(xs, x) {
  let lo = 0, hi = xs.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (xs[mid] < x) lo = mid + 1; else hi = mid;
  }
  return lo;
}

function bisectRight(xs, x) {
  let lo = 0, hi = xs.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (x < xs[mid]) hi = mid; else lo = mid + 1;
  }
  return lo;
}

// ------------------------------------------------------------------ データ
// data.py の load() にあたる。JSON の構造を知っているのはここだけ。
function makeUnit(u, extra) {
  const spec = {
    id: u.id, name: u.name, tier: u.tier, cost: u.cost,
    cooldown_sec: u.cooldown_sec, hp: u.hp, attack: u.attack,
    attack_interval_sec: u.attack_interval_sec,
    attack_windup_sec: u.attack_windup_sec,
    near: u.attack_band_m[0], far: u.attack_band_m[1],
    pierce: u.pierce, knockback: u.knockback, speed_mps: u.speed_mps,
    siege_mult: u.siege_mult, anti_wall_mult: u.anti_wall_mult,
    // 後隙と、前線起点の窓（data.py と同じ既定値）。
    attack_recover_sec: u.attack_recover_sec || 0.0,
    spread_m: u.spread_m || 0.0,
    race: u.race || '王国軍', trait: u.trait || '', role: u.role || '',
    lifespan_sec: 0, summon_sec: 0,
  };
  return Object.assign(spec, extra || {});
}

// **的になるか。** ノックバック中（硬直中）は当たり判定が消える ――
// 追い討ちが入らず、敵は足を止めないので**すり抜けられる**（battle.py と同じ）。
function isHittable(f) {
  return f.alive && f.ready && f.stun_left <= 0;
}

// 壁かどうかは対拠点倍率で決まる。別のタグは持たせない（data.py と同じ）。
function isWall(spec, threshold) {
  return spec.siege_mult <= threshold;
}

// 効果の大きさ。倍率のずれ×持続。ノックバック加算だけ別尺度（data.py と同じ）。
function cardPower(card) {
  if (card.apply.mult !== null) {
    return Math.abs(card.apply.mult - 1.0) * card.duration_sec;
  }
  return Math.abs(card.apply.add || 0) * 2 * card.duration_sec / 10;
}

function loadGame(raw) {
  const units = {};
  for (const u of raw.characters.characters) units[u.id] = makeUnit(u);

  const trumps = {};
  for (const t of raw.trumps.trumps) {
    trumps[t.id] = makeUnit(
      Object.assign({}, t, { tier: 'T', cooldown_sec: 0.0 }),
      { lifespan_sec: t.lifespan_sec, summon_sec: t.summon_sec });
  }

  const cards = {};
  for (const c of raw.cards.cards) {
    cards[c.id] = {
      id: c.id, name: c.name, family: c.family, target: c.target,
      duration_sec: c.duration_sec, cooldown_sec: c.cooldown_sec,
      cast_sec: c.cast_sec, cost: c.cost, band: c.band,
      // 拠点がこの割合まで減っていないと撃てない。無条件なら null。
      base_hp_gate: (c.require && c.require.own_base_hp_at_most !== undefined)
        ? c.require.own_base_hp_at_most : null,
      // **種族呪文。** その種族にだけ効き、編成にその種族が race_min 体
      // 居ないと撃てない（data.py と同じ）。
      race: c.race || '',
      race_min: (c.require && c.require.race_in_roster) || 0,
      apply: {
        scope: c.apply.scope, stat: c.apply.stat,
        // JSON に無いものは Python では None。ここでは null に揃える。
        mult: c.apply.mult === undefined ? null : c.apply.mult,
        add: c.apply.add === undefined ? null : c.apply.add,
      },
    };
  }

  const perks = {};
  for (const p of raw.perks.perks) perks[p.id] = p;

  // 特性。**触れるのは出撃コストだけ**（data.py と同じ約束）。
  const traits = {};
  for (const t of raw.traits.traits) traits[t.id] = t;

  const avatars = {};
  for (const a of raw.avatars.avatars) avatars[a.id] = a;

  const match = raw.match;
  return {
    units, cards, trumps, perks, avatars, traits, match,
    traitRules: raw.traits.rules,
    laneLength: match.field.length_m,
    baseHp: match.avatar.hp,
    // **時間では勝敗を決めない。** ここは雷が降り始める時刻。
    timeLimit: match.victory.sudden_death_at_sec,
    hardStop: match.victory.hard_stop_sec,
    suddenDeath: match.sudden_death,
    castsPerMatch: match.cards.casts_per_match,
    economy: match.economy,
    levels: match.economy.growth.levels,
    cardRules: match.cards,
    trumpRules: match.trump,
    readability: match.readability,
    combat: match.combat,
    wallThreshold: match.roster.wall_threshold,
    farThreshold: match.roster.far_threshold_m,
    stockSlots: match.cards.stock_slots,
  };
}

// 雷の種にする、編成の名前（battle.py の storm_seed と同じ）。
// **持ち込んだものだけで作る** ―― stock_seed ひとつに預けると、
// 欄が落ちた側で違う場所に落ちる（conform.py が実際に鳴った）。
function stormSeed(loadout) {
  const stock = loadout.stock_seed === undefined ? 'stock' : loadout.stock_seed;
  return `${loadout.avatar}:${loadout.roster.join(',')}:`
       + `${loadout.brought}:${loadout.trump}:${stock}`;
}

// ------------------------------------------------------------------ 場の1体
class Fighter {
  constructor(spec, side, x, hp, facing, summonLeft, lifespanLeft, spawnSeq) {
    this.spec = spec;
    this.side = side;
    this.x = x;
    this.hp = hp;
    this.facing = facing;
    this.windup_left = 0.0;
    this.recover_left = 0.0;
    // **後隙。** recover_left は「次の一手までの残り」で、こちらはそのうち
    // 被弾が増える前半だけ。分けてあるのは攻撃間隔（＝DPS）を動かさずに
    // 後隙の長さだけを設計値にするため。
    this.exposed_left = 0.0;
    this.stun_left = 0.0;
    this.knockbacks_done = 0;
    this.summon_left = summonLeft === undefined ? 0.0 : summonLeft;
    this.lifespan_left = lifespanLeft === undefined ? Infinity : lifespanLeft;
    // 出撃時に決まって一生変わらない通し番号（見た目専用。Side._spawnSeq）。
    this.spawn_seq = spawnSeq === undefined ? 0 : spawnSeq;
    // 見た目専用。このtickで実際に前進したか（battle.py と同じ、spawn_seq 同様
    // シミュレーションには触れない）。stepFighter が毎tick立て直す。
    this.moving = false;
  }

  get alive() { return this.hp > 0; }

  // 召喚演出が終わって、実際に戦える状態か。
  get ready() { return this.summon_left <= 0; }

  // 後隙の最中か。ここで殴ると余分に通る。
  get exposed() { return this.exposed_left > 0; }

  // 世界座標での**届く範囲**。向きで反転する。前線起点（spread_m > 0）でも
  // まずここに敵が入らないと始まらない ―― 当たる帯は strikeBand が出す。
  band() {
    const near = this.spec.near, far = this.spec.far;
    if (this.facing > 0) return [this.x + near, this.x + far];
    return [this.x - far, this.x - near];
  }
}

// ------------------------------------------------------------------ 片方の陣
class Side {
  // stockSeq は Python の stock_sequence() が返す並びをそのまま渡したもの。
  // Python の乱数（Mersenne Twister）を JS で再現するのは危ないので、
  // 並びは作らずに **同じものを持ってくる**（build_web.py が焼き込む）。
  constructor(game, loadout, index, stockSeq) {
    this.game = game;
    this.loadout = loadout;
    this.index = index;
    this.base_x = index === 0 ? 0.0 : game.laneLength;
    this.facing = index === 0 ? 1 : -1;

    this.base_hp = game.baseHp;
    // 拠点に打ち込まれた攻城の待ち行列（`Battle.applyBaseDamage`）。
    this.siege_backlog = 0.0;
    this.level = 1;
    this.money = game.economy.start;
    // 資金は連続では増えない。何秒かごとに +N という刻みで貯まる。
    // 素の間隔を使う ―― この時点ではまだ効果がひとつも乗っていない。
    this.income_left = this.levelRow.income_every_sec;

    this.fighters = [];
    // 出撃した順に振るだけの通し番号。死んだ個体は間引かれて配列が作り直される
    // ので、配列の添字は出撃順の目印にならない ―― view.js の重なり順はこれを使う。
    this._spawnSeq = 0;
    this.deploy_cd = {};
    this.gcd_left = 0.0;
    this.casting = null;
    this.cast_source = null;
    this.cast_left = 0.0;
    this.cast_started = 0.0;
    this.effects = [];

    const rules = game.cardRules;
    this.brought = loadout.brought;
    this.brought_cd = 0.0;
    this.restock_sec = rules.restock_sec;
    this._queue = stockSeq.slice();
    this._head = 0;
    this.stock = [];
    this.restock = new Array(rules.stock_slots).fill(0.0);
    for (let i = 0; i < rules.stock_slots; i++) this.stock.push(this._draw());

    this.trump_used = false;
    // **呪文は1試合3回まで**（持ち込み・ストックの合計。battle.py と同じ）。
    this.casts_left = game.castsPerMatch;
    this.deploy_lock_left = 0.0;
    this.upgrading_left = 0.0;

    // 特性が見るもの。**特性が触れるのは出撃コストだけ**（battle.py と同じ）。
    this.last_race = null;              // 直前に出したユニットの種族
    this.min_deploy_cost = game.traitRules.min_deploy_cost;
    // 編成の中の同種族の数は試合中変わらないので、ここで数えておく。
    this.kin = {};
    for (const uid of loadout.roster) {
      const spec = game.units[uid];
      let n = 0;
      for (const other of loadout.roster) {
        if (other !== uid && game.units[other].race === spec.race) n++;
      }
      this.kin[uid] = n;
    }
    // 種族呪文が見るのはこちら ―― 編成にその種族が何体入っているか。
    this.race_count = {};
    for (const uid of loadout.roster) {
      const race = game.units[uid].race;
      this.race_count[race] = (this.race_count[race] || 0) + 1;
    }

    const avatar = game.avatars[loadout.avatar];
    this.perks = new Set(avatar.perks);
    this.parry_charges = this._perkParam('parry', 'charges', 0);
    this.parry_until = -1.0;
    this.surge_charges = this._perkParam('surge', 'charges', 0);
    this.last_stand_used = false;

    if (this.perks.has('head_start')) {
      this.money += game.perks.head_start.params.start_money;
    }
  }

  // ---------------------------------------------------------------- 呪文
  // ストックに1枚流し込む。いま並んでいる札とは重ならないようにする。
  // Python は deque を popleft→append で回すので、頭を進めるのと同じ。
  _draw() {
    const n = this._queue.length;
    for (let k = 0; k < n; k++) {
      const cardId = this._queue[this._head % n];
      this._head++;
      if (this.stock.indexOf(cardId) < 0) return cardId;
    }
    return null;
  }

  cardOf(source) {
    const kind = source[0], index = source[1];
    if (kind === 'brought') return this.game.cards[this.brought];
    if (index >= 0 && index < this.stock.length && this.stock[index]) {
      return this.game.cards[this.stock[index]];
    }
    return null;
  }

  // 拠点の傷が条件の札か。傷んでいなければ、資金があっても撃てない。
  // 押し込まれている側だけが持てる手（battle.py の unlocked と同じ）。
  unlocked(card) {
    const gate = card.base_hp_gate;
    if (gate !== null && this.base_hp > this.game.baseHp * gate) return false;
    // **種族呪文。** 編成にその種族が足りていなければ、資金があっても撃てない。
    if (card.race) return (this.race_count[card.race] || 0) >= card.race_min;
    return true;
  }

  // いま撃てるか。資金・詠唱中・共通CD・育成中・個別CD・解禁を全部見る。
  castable(source) {
    if (this.casts_left <= 0) return false;      // 1試合3回を使い切った
    if (this.casting !== null || this.gcd_left > 0 || this.busy) return false;
    if (source[0] === 'brought' && this.brought_cd > 0) return false;
    const card = this.cardOf(source);
    return card !== null && this.money >= card.cost && this.unlocked(card);
  }

  sources() {
    const out = [['brought', 0]];
    for (let i = 0; i < this.stock.length; i++) out.push(['stock', i]);
    return out;
  }

  // ---------------------------------------------------------------- 特典
  _perkParam(perkId, key, fallback) {
    if (!this.perks.has(perkId)) return fallback;
    const params = this.game.perks[perkId].params;
    return key in params ? params[key] : fallback;
  }

  // ---------------------------------------------------------------- 効果
  // かかっている効果を掛けたあとの値。掛けてから足す。
  // race を渡すとユニット1体ぶんの値になる ―― **種族呪文**はその種族に
  // だけ効くので、全軍ぶん（資金・出撃コスト）とは分けて出す。
  stat(name, base, race) {
    let value = base;
    for (const e of this.effects) {
      if (e.stat !== name) continue;
      if (e.race && e.race !== race) continue;
      if (e.mult !== null) value *= e.mult;
      if (e.add !== null) value += e.add;
    }
    return value;
  }

  addEffect(effect) { this.effects.push(effect); }

  // ---------------------------------------------------------------- 資金
  get levelRow() { return this.game.levels[this.level - 1]; }
  get money_cap() { return this.levelRow.max; }
  get income_amount() { return this.levelRow.income_amount; }

  // 次に資金が入るまでの秒数。増収などのカードはここを縮める。
  get income_every() {
    return this.levelRow.income_every_sec / Math.max(this.stat('income', 1.0), 1e-6);
  }

  // 表示と検算のための実効値（毎秒いくら）。刻みの実体は上の2つ。
  get income() { return this.income_amount / this.income_every; }

  // 時間を進めて、刻みが来ていれば資金を足す。上限は超えない。
  tickIncome(dt) {
    this.income_left -= dt;
    if (this.income_left > 0) return false;
    this.money = Math.min(this.money + this.income_amount, this.money_cap);
    this.income_left += this.income_every;
    return true;
  }

  get upgrade_cost() {
    const row = this.levelRow;
    return 'upgrade_cost' in row ? row.upgrade_cost : null;
  }

  canUpgrade() {
    const cost = this.upgrade_cost;
    return cost !== null && this.money >= cost;
  }

  // レベルアップ中。設計書4.3の「育てている間は何も出せない」の実体。
  get busy() { return this.upgrading_left > 0; }

  upgrade() {
    this.money -= this.upgrade_cost;
    this.level += 1;
    this.upgrading_left = this.game.economy.growth.upgrade_sec;
    // 刻みが速くなるので、次の1回までを新しい間隔で測り直す
    this.income_left = Math.min(this.income_left, this.income_every);
  }

  // いま出すのに払う額。素の値段 → 特性 → カードの倍率、の順（battle.py と同じ）。
  unitCost(spec) {
    let base = spec.cost;
    const trait = spec.trait ? this.game.traits[spec.trait] : null;
    if (trait) {
      const params = trait.params;
      if (trait.kind === 'cost_minus_per_same_race_in_roster') {
        base -= params.amount * (this.kin[spec.id] || 0);
      } else if (trait.kind === 'cost_minus_if_last_same_race') {
        if (this.last_race === spec.race) base -= params.amount;
      } else if (trait.kind === 'cost_mult_when_hurt') {
        if (this.base_hp <= this.game.baseHp * params.base_hp_at_most) {
          base *= params.mult;
        }
      }
    }
    const value = this.stat('cost', base);
    return Math.max(this.min_deploy_cost, Math.ceil(value - 1e-9));
  }
  deployCooldown(spec) { return this.stat('deploy_cooldown', spec.cooldown_sec); }
}

// ------------------------------------------------------------------ 1試合
class Battle {
  constructor(game, a, b, policyA, policyB, stockA, stockB) {
    this.game = game;
    this.sides = [new Side(game, a, 0, stockA), new Side(game, b, 1, stockB)];
    this.policies = [policyA, policyB];
    this.tick = game.combat.tick_sec;
    this.kb_distance = game.combat.knockback_distance_m;
    this.kb_stun = game.combat.knockback_stun_sec;
    this.siege_cap = game.combat.siege_cap_dps;
    this.recover_mult = game.combat.recover_damage_mult;
    this.max_units = game.match.field.max_units_per_side;
    this.t = 0.0;
    this.drops = (game.economy.milestones || []).slice();
    this._next_drop = 0;
    // そのtickの世界の見え方。全員が同じ盤面を見て動くので、
    // 「先に処理された側が先に殴れる」という順番の有利が出ない。
    this._snap = [[], []];
    this._hittable = [[], []];
    this._damage = [];
    this._base_damage = [];
    this.events = [];

    // 画面のための直近イベント。**シミュレーションの結果ではなく、
    // 見せ方の都合だけで持っている** ―― だから conform.py の指紋には
    // 入れない（数字の一致試験にノイズを足すだけになる）。数tick分だけ
    // 覚えておいて、古いものは step() の最後で捨てる（RECENT_SEC）。
    this.base_hits = [];      // 拠点への1発 [t, side_index, amount, is_wall]
    this.level_ups = [];      // 財布の育成完了 [t, side_index, level]
    this.cast_effects = [];   // 呪文の発動 [t, target_side_index, is_buff]

    // ── サドンデスの雷（battle.py と同じ）───────────────────
    // 3分を過ぎたらレーンのどこかに落ちる。落ちた範囲のユニットは
    // 敵味方の区別なく必ず倒れる。種は両者の編成から作るので、
    // **同じ試合は必ず同じところに落ちる**。
    const bolt = game.suddenDeath;
    this.storm_at = game.timeLimit;
    this.storm_every = bolt.every_sec;
    this.storm_radius = bolt.radius_m;
    this.storm_growth = bolt.radius_growth_m;
    this.storm_radius_max = bolt.radius_max_m;
    this.storm_warn = bolt.warn_sec;
    this.rng = new Rng(seed32(`${stormSeed(a)}|${stormSeed(b)}|storm`));
    this.bolts_fallen = 0;
    this.pending = [];                 // [落ちる時刻, 位置, 半径]
    this._next_bolt = this.storm_at;
  }

  note(side, text) { this.events.push([this.t, side, text]); }

  _pruneRecent() {
    const cutoff = this.t - Battle.RECENT_SEC;
    this.base_hits = this.base_hits.filter(h => h[0] >= cutoff);
    this.level_ups = this.level_ups.filter(h => h[0] >= cutoff);
    this.cast_effects = this.cast_effects.filter(h => h[0] >= cutoff);
  }

  enemyOf(side) { return this.sides[1 - side.index]; }

  // ------------------------------------------------------------ 出撃・行動
  deploy(side, unitId) {
    const spec = this.game.units[unitId];
    if (!spec) return false;
    const cost = side.unitCost(spec);
    if (side.money < cost || (side.deploy_cd[unitId] || 0.0) > 0
        || side.deploy_lock_left > 0 || side.busy
        || side.fighters.length >= this.max_units) {
      return false;
    }
    side.money -= cost;
    side.deploy_cd[unitId] = side.deployCooldown(spec);
    side.last_race = spec.race;          // 「連携」が次に見るのはこれ
    side.fighters.push(new Fighter(spec, side.index, side.base_x, spec.hp,
                                   side.facing, undefined, undefined,
                                   side._spawnSeq++));
    return true;
  }

  summonTrump(side) {
    const spec = this.game.trumps[side.loadout.trump];
    const rules = this.game.trumpRules;
    if (side.trump_used || this.t < rules.unlock_at_sec
        || side.money < spec.cost || side.deploy_lock_left > 0 || side.busy) {
      return false;
    }
    side.money -= spec.cost;
    side.trump_used = true;
    side.fighters.push(new Fighter(spec, side.index, side.base_x, spec.hp,
                                   side.facing, spec.summon_sec,
                                   spec.lifespan_sec + spec.summon_sec,
                                   side._spawnSeq++));
    this.note(side.index, `切り札 ${spec.name} を召喚（演出 ${spec.summon_sec}秒）`);
    return true;
  }

  // 詠唱。短縮しても床は割らない（設計書7.5の契約）。
  castTime(side, card) {
    let seconds = card.cast_sec;
    if (side.perks.has('quick_cast')) {
      seconds *= this.game.perks.quick_cast.params.cast_time_mult;
    }
    return Math.max(seconds, this.game.readability.min_cast_sec);
  }

  // 詠唱に入る。**資金と札はこの時点で消える。** 見切られても戻らない。
  startCast(side, source) {
    if (!side.castable(source)) return false;
    const card = side.cardOf(source);
    side.money -= card.cost;
    // 回数も詠唱に入った時点で減る。見切られても戻らない ―― 資金と同じ。
    side.casts_left -= 1;

    const kind = source[0], index = source[1];
    if (kind === 'brought') {
      side.brought_cd = card.cooldown_sec;
    } else {
      side.stock[index] = null;
      side.restock[index] = side.restock_sec;
    }

    side.casting = card;
    side.cast_source = source;
    side.cast_left = this.castTime(side, card);
    side.cast_started = this.t;
    const where = kind === 'brought' ? '持ち込み' : `ストック${index + 1}`;
    this.note(side.index,
              `${card.name} を詠唱（${where}・${card.cost} / `
              + `${side.cast_left.toFixed(2)}秒・残り${side.casts_left}回）`);
    return true;
  }

  resolveCast(side) {
    const card = side.casting;
    side.casting = null;
    side.cast_source = null;
    const enemy = this.enemyOf(side);
    side.gcd_left = this.game.cardRules.global_cooldown_sec;

    // 見切りは「呪文を潰す」。無敵の窓が詠唱の完了を覆っていれば不発。
    if (enemy.parry_until >= this.t) {
      const reward = this.game.perks.parry.params.money_on_success;
      enemy.money = Math.min(enemy.money + reward, enemy.money_cap);
      enemy.parry_until = -1.0;
      this.note(enemy.index,
                `見切り成功 — ${card.name}（${card.cost}）を潰した（資金 +${reward}）`);
      return;
    }

    const own = card.apply.scope.startsWith('own');
    const target = own ? side : enemy;
    // 種族呪文は、その種族のユニットにだけ乗る（Side.stat が絞る）。
    target.addEffect({
      stat: card.apply.stat, mult: card.apply.mult, add: card.apply.add,
      until: this.t + card.duration_sec, source: card.id, race: card.race,
    });
    // own_* は自分を強くする＝バフ、enemy_* は相手を弱くする＝デバフ。
    this.cast_effects.push([this.t, target.index, own]);
    this.note(side.index, `${card.name} 発動（${card.duration_sec}秒）`);
  }

  useParry(side) {
    if (side.parry_charges <= 0) return false;
    const params = this.game.perks.parry.params;
    side.parry_charges -= 1;
    side.parry_until = this.t + params.invuln_sec;
    side.deploy_lock_left = params.deploy_lock_sec;
    this.note(side.index, `見切り（無敵 ${params.invuln_sec}秒）`);
    return true;
  }

  useSurge(side) {
    if (side.surge_charges <= 0) return false;
    const params = this.game.perks.surge.params;
    side.surge_charges -= 1;
    side.addEffect({
      stat: 'speed', mult: params.speed_mult, add: null,
      until: this.t + params.duration_sec, source: 'surge', race: '',
    });
    this.note(side.index,
              `突撃（速度 ×${params.speed_mult} / ${params.duration_sec}秒）`);
    return true;
  }

  // ---------------------------------------------------------------- 戦闘
  // tickの頭で盤面を固定する。全員がこれを見て動く。
  snapshot() {
    this._snap = this.sides.map(side => {
      const rows = [];
      for (const f of side.fighters) if (f.alive && f.ready) rows.push([f.x, f]);
      rows.sort((p, q) => p[0] - q[0]);      // 安定ソート（Python の sorted と同じ）
      return rows;
    });
    // **的の一覧は別に持つ。** ノックバック中は判定が消えるので、殴る側から
    // 見ると居ないのと同じ ―― 追い討ちが入らず、足も止まらない（battle.py と同じ）。
    this._hittable = this._snap.map(rows => rows.filter(pair => isHittable(pair[1])));
  }

  // そのtickの頭で場に居た側のユニット。方針もここを見る。
  live(index) { return this._snap[index].map(pair => pair[1]); }

  // 帯の中に居る**的**。ノックバック中の者はここに入らない。
  rowsBetween(side, lo, hi) {
    const rows = this._hittable[side];
    const xs = rows.map(pair => pair[0]);
    return rows.slice(bisectLeft(xs, lo - EPS), bisectRight(xs, hi + EPS));
  }

  // **実際に当たる帯。** 普通は届く範囲そのもの。spread_m を持つユニットだけ
  // 違う ―― 届く範囲の中にいる敵の一番手前を起点に、そこから奥へ窓のぶんだけ
  // 叩く。「相手の最前列から少し奥まで」という形で、安い1体を前に置いて全部
  // 止めるが通らなくなる（壁ごと後ろの列を巻き込むので）。
  strikeBand(fighter) {
    const band = fighter.band();
    if (fighter.spec.spread_m <= 0) return band;
    const rows = this.rowsBetween(1 - fighter.side, band[0], band[1]);
    if (rows.length === 0) return band;      // 誰も居ないので拠点だけが的
    const head = fighter.facing > 0 ? rows[0][0] : rows[rows.length - 1][0];
    const width = fighter.spec.spread_m;
    if (fighter.facing > 0) return [head, Math.min(band[1], head + width)];
    return [Math.max(band[0], head - width), head];
  }

  targetsInBand(fighter) {
    const band = this.strikeBand(fighter);
    const found = this.rowsBetween(1 - fighter.side, band[0], band[1]).slice();
    found.sort((p, q) => Math.abs(p[0] - fighter.x) - Math.abs(q[0] - fighter.x));
    return found.map(pair => pair[1]);
  }

  baseInBand(fighter) {
    const band = this.strikeBand(fighter);
    const baseX = this.sides[1 - fighter.side].base_x;
    return band[0] - EPS <= baseX && baseX <= band[1] + EPS;
  }

  // 攻城を、**攻城口の上限の速さで**拠点に入れる。帯が拠点に届いた者は
  // 全員が削るが、削れる速さは siege_cap_dps で止まる。上限が無かった頃は
  // 前線が破れた瞬間に毎秒11700が入り、拠点は『無傷』か『0』しか取らなかった
  // ―― 自拠点の傷で解禁される札が届く前に試合が終わる。上限を置くと
  // 拠点HP ÷ 上限 = 15秒 が設計値になる。
  // 上限は待ち行列で効かせる。tickごとに切り落とすと、一発が重い攻城
  // （攻城櫓 1.9）だけが損をして「対拠点倍率がそのまま効く」が壊れる。
  applyBaseDamage(dt) {
    const arrived = [0.0, 0.0];
    for (const pair of this._base_damage) arrived[pair[0].index] += pair[1];
    for (const side of this.sides) {
      side.siege_backlog = Math.min(side.siege_backlog + arrived[side.index],
                                    this.siege_cap);
      const taken = Math.min(side.siege_backlog, this.siege_cap * dt);
      side.siege_backlog -= taken;
      side.base_hp -= taken;
    }
  }

  applyDamage(victim, amount) {
    const side = this.sides[victim.side];
    // **後隙に入った打撃は余分に通る。** 読める大技への答えを
    // 「避ける」から「差し込む」に変えるための倍率。
    if (victim.exposed) amount *= this.recover_mult;
    victim.hp -= amount;
    if (victim.hp <= 0) return;

    const kb = side.stat('knockback', victim.spec.knockback, victim.spec.race);
    if (kb < 1) return;                            // 堅陣：後退しなくなる
    // **一撃で区切りを2つ跨いでも下がるのは1回だけ**（battle.py と同じ）。
    // 重い一撃は「削る力」、手数は「押す力」と役割が割れる。
    const segment = victim.spec.hp / kb;
    const crossed = Math.floor((victim.spec.hp - victim.hp) / segment);
    if (crossed > victim.knockbacks_done) {
      victim.knockbacks_done = crossed;
      victim.x -= victim.facing * this.kb_distance;
      victim.x = Math.max(0.0, Math.min(this.game.laneLength, victim.x));
      victim.stun_left = this.kb_stun;
      victim.windup_left = 0.0;
    }
  }

  resolveAttack(fighter) {
    const side = this.sides[fighter.side];
    const enemy = this.enemyOf(side);
    const power = side.stat('attack', fighter.spec.attack, fighter.spec.race);

    if (enemy.parry_until >= this.t) return;

    const wallLine = this.game.wallThreshold;

    // **帯が敵拠点に届いていれば、拠点には必ず当たる**（battle.py と同じ）。
    // 拠点はユニットと貫通の枠を奪い合わない ―― 混ぜていた頃は、貫通ぶんの壁が
    // 拠点の前に並んでいる限り拠点に一発も入らず、自陣に固めた側が絶対に
    // 落ちなかった。
    if (this.baseInBand(fighter)) {
      const dealt = power * fighter.spec.siege_mult;
      this._base_damage.push([enemy, dealt]);
      // 画面向け。壁（対拠点倍率が低いユニット）が殴った一撃だけ、View 側が
      // 別扱いで灰色に見せる ―― 「これは削れない」が伝わるように。
      this.base_hits.push([this.t, enemy.index, dealt, isWall(fighter.spec, wallLine)]);
    }

    for (const victim of this.targetsInBand(fighter).slice(0, fighter.spec.pierce)) {
      const bonus = isWall(victim.spec, wallLine) ? fighter.spec.anti_wall_mult : 1.0;
      this._damage.push([victim, power * bonus]);
    }
  }

  stepFighter(fighter) {
    const side = this.sides[fighter.side];
    const dt = this.tick;

    // 見た目専用のリセット。実際に進んだ場合だけ末尾の分岐が立て直す。
    fighter.moving = false;

    // **後隙は実時間で抜ける。** 押し戻されても気絶しても同じだけ流れる。
    if (fighter.exposed_left > 0) fighter.exposed_left -= dt;

    if (fighter.summon_left > 0) { fighter.summon_left -= dt; return; }
    if (fighter.stun_left > 0) { fighter.stun_left -= dt; return; }

    const intervalMult = side.stat('attack_interval', 1.0, fighter.spec.race);
    if (fighter.recover_left > 0) { fighter.recover_left -= dt; return; }
    if (fighter.windup_left > 0) {
      fighter.windup_left -= dt;
      if (fighter.windup_left <= 0) {
        this.resolveAttack(fighter);
        const cycle = fighter.spec.attack_interval_sec * intervalMult;
        const windup = fighter.spec.attack_windup_sec * intervalMult;
        fighter.recover_left = Math.max(0.0, cycle - windup);
        // 後隙は「次の一手までの残り」の前半だけ。
        fighter.exposed_left = Math.min(
          fighter.spec.attack_recover_sec * intervalMult, fighter.recover_left);
      }
      return;
    }

    if (this.targetsInBand(fighter).length > 0 || this.baseInBand(fighter)) {
      fighter.windup_left = fighter.spec.attack_windup_sec * intervalMult;
      return;
    }

    // **味方どうしは詰まらない**（battle.py と同じ）。進めるところまで進んで、
    // 敵が帯に入ったところで止まる ―― 立ち位置は射程が決める。
    const speed = side.stat('speed', fighter.spec.speed_mps, fighter.spec.race);
    const moved = fighter.x + fighter.facing * speed * dt;
    fighter.x = Math.max(0.0, Math.min(this.game.laneLength, moved));
    fighter.moving = true;
  }

  // ---------------------------------------------------------------- 進行
  step() {
    const dt = this.tick;

    // 盤面の固定は判断より前。あとにすると、先に動いた側の出撃が
    // 同じtickの相手の判断に見えてしまい、後手だけが得をする。
    this.snapshot();

    // 時間の節目の配布。左右対称の試合が割れないよう、互角なら誰にも入らない。
    while (this._next_drop < this.drops.length
           && this.t >= this.drops[this._next_drop].at_sec) {
      const drop = this.drops[this._next_drop];
      this._next_drop += 1;
      this.payDrop(drop);
    }

    for (const side of this.sides) {
      side.tickIncome(dt);
      side.effects = side.effects.filter(e => e.until > this.t);
      side.gcd_left = Math.max(0.0, side.gcd_left - dt);
      side.deploy_lock_left = Math.max(0.0, side.deploy_lock_left - dt);
      const wasBusy = side.upgrading_left > 0;
      side.upgrading_left = Math.max(0.0, side.upgrading_left - dt);
      if (wasBusy && side.upgrading_left <= 0) {
        // 育成が終わった瞬間。level はもう上がっている（育成が始まった
        // 時点で払い済み）ので、ここでは「使えるようになった」ことだけを伝える。
        this.level_ups.push([this.t, side.index, side.level]);
      }
      for (const uid of Object.keys(side.deploy_cd)) {
        side.deploy_cd[uid] = Math.max(0.0, side.deploy_cd[uid] - dt);
      }

      side.brought_cd = Math.max(0.0, side.brought_cd - dt);
      for (let i = 0; i < side.restock.length; i++) {
        if (side.stock[i] !== null && side.stock[i] !== undefined) continue;
        const left = Math.max(0.0, side.restock[i] - dt);
        side.restock[i] = left;
        if (left <= 0) side.stock[i] = side._draw();
      }

      if (side.perks.has('last_stand') && !side.last_stand_used
          && side.base_hp <= this.game.baseHp
             * this.game.perks.last_stand.params.threshold) {
        side.last_stand_used = true;
        const gain = this.game.perks.last_stand.params.money_gain;
        side.money = Math.min(side.money + gain, side.money_cap);
        this.note(side.index, `起死回生（資金 +${gain}）`);
      }
    }

    for (let i = 0; i < this.sides.length; i++) {
      this.policies[i](this, this.sides[i]);
    }

    for (const side of this.sides) {
      if (side.casting !== null) {
        side.cast_left -= dt;
        if (side.cast_left <= 0) this.resolveCast(side);
      }
    }

    this._damage.length = 0;
    this._base_damage.length = 0;
    for (const side of this.sides) {
      for (const fighter of side.fighters.slice()) {
        if (fighter.lifespan_left !== Infinity) fighter.lifespan_left -= dt;
        this.stepFighter(fighter);
      }
    }

    // 両者ぶんまとめて適用する。片方の攻撃が先に通って相手が
    // 撃ち返せない、という順番の有利をなくすため。
    for (const pair of this._damage) this.applyDamage(pair[0], pair[1]);
    this.applyBaseDamage(dt);

    this._pruneRecent();

    for (const side of this.sides) {
      const enemy = this.enemyOf(side);
      const survivors = [];
      for (const fighter of side.fighters) {
        if (!fighter.alive) {
          const reward = fighter.spec.cost * this.game.economy.kill_reward_ratio;
          enemy.money = Math.min(enemy.money + reward, enemy.money_cap);
          continue;
        }
        if (fighter.lifespan_left <= 0) {
          this.note(side.index, `${fighter.spec.name} が寿命で退場`);
          continue;
        }
        survivors.push(fighter);
      }
      side.fighters = survivors;
    }

    // 雷は掃除のあと。倒れた者を二度数えないため。
    if (this.suddenDeath) this.stepStorm();

    this.t += dt;
  }

  // 自陣からどれだけ前に出ているか。押し込んでいる側を決める物差し。
  advanceOf(side) {
    let best = 0.0;
    for (const f of side.fighters) {
      if (!f.alive || !f.ready) continue;
      const reach = Math.abs(f.x - side.base_x);
      if (reach > best) best = reach;
    }
    return best;
  }

  // いま押し込んでいる側。互角なら null。
  // いま押し込んでいる側。**試合の結果には効かない**（battle.py と同じ）。
  leader() {
    const a = this.advanceOf(this.sides[0]);
    const b = this.advanceOf(this.sides[1]);
    if (Math.abs(a - b) <= EPS) return null;
    return a > b ? this.sides[0] : this.sides[1];
  }

  // 節目の配布。**必ず両者に同額**（battle.py と同じ）。押している側だけに
  // 入る陣地ボーナスは、一度傾いた試合をそのまま傾かせ続けるので外した。
  payDrop(drop) {
    const amount = drop.amount, at = drop.at_sec;
    for (const side of this.sides) {
      side.money = Math.min(side.money + amount, side.money_cap);
    }
    this.note(0, `${at.toFixed(0)}秒の配布 — 両者に +${amount}`);
  }

  // 次の配布（残り秒, 額）。画面で読ませるために要る。
  nextDrop() {
    if (this._next_drop >= this.drops.length) return null;
    const drop = this.drops[this._next_drop];
    return [Math.max(0.0, drop.at_sec - this.t), drop.amount];
  }

  // 雷が降り始めているか。画面と方針が見る。
  get suddenDeath() { return this.t >= this.storm_at; }

  // 次の雷の落ちる場所を決めて、予告に積む。**落ちる位置は先に見える**。
  scheduleBolt() {
    const lane = this.game.laneLength;
    const where = this.rng.unit() * lane;
    // bolts_fallen は対ではなく個々の落雷を数える（1組で2ずつ増える）ので、
    // 伸びは対の数（Python 側と同じ // 2 = 整数除算）で刻む（battle.py と同じ）。
    const pairsFallen = Math.floor(this.bolts_fallen / 2);
    const radius = Math.min(
      this.storm_radius + this.storm_growth * pairsFallen,
      this.storm_radius_max);
    // **必ず対で落ちる**（battle.py と同じ）。1発だけだと、どちら側の半分に
    // 落ちたかで有利不利がつく。対にすると左右は釣り合ったまま線だけが欠ける。
    this.pending.push([this.t + this.storm_warn, where, radius]);
    this.pending.push([this.t + this.storm_warn, lane - where, radius]);
    this.note(0, `落雷の予兆 — ${where.toFixed(0)}m と ${(lane - where).toFixed(0)}m`
                 + `（半径${radius.toFixed(0)}m・${this.storm_warn}秒後）`);
  }

  // 雷を落とす。**範囲内のユニットは敵味方の区別なく必ず倒れる。**
  // 体力も装甲も関係ない ―― ここだけは「ダメージ」ではなく「取り除く」。
  strike(where, radius) {
    const killed = [0, 0];
    for (const side of this.sides) {
      for (const fighter of side.fighters) {
        if (fighter.alive && Math.abs(fighter.x - where) <= radius + EPS) {
          fighter.hp = 0.0;
          killed[side.index] += 1;
        }
      }
    }
    this.bolts_fallen += 1;
    this.note(0, `落雷 — ${where.toFixed(0)}m（半径${radius.toFixed(0)}m）`
                 + `P1 ${killed[0]}体 / P2 ${killed[1]}体`);
  }

  stepStorm() {
    if (this.t >= this._next_bolt) {
      this.scheduleBolt();
      this._next_bolt += this.storm_every;
    }
    const landed = this.pending.filter(b => this.t >= b[0]);
    if (landed.length > 0) {
      this.pending = this.pending.filter(b => this.t < b[0]);
      for (const b of landed) this.strike(b[1], b[2]);
    }
  }

  // **時間では決めない。** 拠点が落ちるまで続く。hardStop は
  // シミュレータが止まらなくなるのを防ぐ安全弁で、勝敗の仕組みではない。
  finished() {
    return this.t >= this.game.hardStop
        || this.sides.some(s => s.base_hp <= 0);
  }
}

// base_hits / level_ups / cast_effects を何秒分だけ覚えておくか
// （battle.py の Battle.RECENT_SEC と同じ値）。
Battle.RECENT_SEC = 3.0;

// ------------------------------------------------------------------ 結果
function resultOf(battle) {
  const a = battle.sides[0], b = battle.sides[1];
  const hp = [Math.max(0.0, a.base_hp), Math.max(0.0, b.base_hp)];
  let winner, reason;
  if (hp[0] <= 0 || hp[1] <= 0) {
    winner = hp[1] <= 0 ? 0 : 1;
    reason = '拠点撃破';
  } else {
    // 両拠点が残ったまま終わるのは hard_stop（安全弁）だけ ―― 時間切れという
    // 結末は無くしたので、与ダメージ割合で勝敗を付けてはいけない（battle.py と同じ）。
    winner = null; reason = '安全弁（決着せず）';
  }
  return {
    winner, reason, seconds: battle.t, base_hp: hp,
    level: [a.level, b.level], events: battle.events,
  };
}

// ------------------------------------------------------------------ 方針
// policy.py の移植。

// 自陣の近くまで敵が来ているか。
function pressure(battle, side, within) {
  return battle.live(1 - side.index)
    .some(f => Math.abs(f.x - side.base_x) <= within);
}

// 相手の詠唱に合わせる。反応時間を待ってから、窓が完了を覆う位置で押す。
function tryParry(battle, side) {
  if (side.parry_charges <= 0) return false;
  const enemy = battle.enemyOf(side);
  if (enemy.casting === null) return false;
  const reaction = battle.game.readability.human_reaction_sec;
  const window = battle.game.perks.parry.params.invuln_sec;
  if (battle.t - enemy.cast_started < reaction) return false;  // まだ見えていない
  if (enemy.cast_left > window * 0.5) return false;            // 早すぎる
  return battle.useParry(side);
}

// 呪文はユニットと同じ資金を食う。**出撃ぶんを残してから撃つ。**
function tryCard(battle, side) {
  if (side.casting !== null || side.gcd_left > 0) return false;
  const ownUnits = battle.live(side.index).length;
  const foeUnits = battle.live(1 - side.index).length;

  let cheapest = Infinity;
  for (const uid of side.loadout.roster) {
    const c = side.unitCost(battle.game.units[uid]);
    if (c < cheapest) cheapest = c;
  }
  if (cheapest === Infinity) cheapest = 0.0;
  const reserve = cheapest * 3;        // 壁を切らさないぶんは手を付けない

  let best = null, bestCard = null;
  for (const source of side.sources()) {
    if (!side.castable(source)) continue;
    const card = side.cardOf(source);
    if (side.money - card.cost < reserve) continue;
    const scope = card.apply.scope;
    if (scope.startsWith('own') && scope.endsWith('units') && ownUnits < 2) continue;
    if (scope === 'enemy_units' && foeUnits < 2) continue;
    if (bestCard === null || cardPower(card) > cardPower(bestCard)) {
      best = source; bestCard = card;
    }
  }
  return best ? battle.startCast(side, best) : false;
}

// 前に立つ者を切らさないまま、余った資金で高いものを出す（policy.py と同じ）。
// 「一番高いものを出す」だけだと、両軍とも遠距離だけの隊列になって
// 空きを挟んで撃ち合ったまま試合が終わる。
function tryDeploy(battle, side) {
  const game = battle.game;
  const line = game.farThreshold;
  const alive = side.fighters.filter(f => f.alive);
  let front = 0;
  for (const f of alive) {
    if (f.spec.far <= line) front++;
  }
  const ready = side.loadout.roster.filter(uid => (side.deploy_cd[uid] || 0.0) <= 0);
  const affordable = ready.filter(uid => side.money >= side.unitCost(game.units[uid]));

  // 同点は Python の min/max と同じく「先に出てきたほう」を採る。
  const cheapest = list => {
    let pick = list[0];
    for (const uid of list) if (game.units[uid].cost < game.units[pick].cost) pick = uid;
    return pick;
  };
  const dearest = list => {
    let pick = list[0];
    for (const uid of list) if (game.units[uid].cost > game.units[pick].cost) pick = uid;
    return pick;
  };

  const close = affordable.filter(uid => game.units[uid].far <= line);
  if (front < Math.max(2, Math.trunc(battle.max_units / 3)) && close.length > 0) {
    return battle.deploy(side, cheapest(close));
  }

  // 狙いは「財布の上限で届く一番高いもの」。届くまでは何も出さずに貯める。
  // ただし隊列の半分は前に立つ者にする ―― 付けないと両軍とも臼砲（80m）の
  // 壁になり、空きを挟んで撃ち合ったまま終わる。
  let pool = ready;
  if (front * 2 < alive.length) {
    const near = ready.filter(uid => game.units[uid].far <= line);
    if (near.length > 0) pool = near;
  }
  const reachable = pool.filter(uid => side.unitCost(game.units[uid]) <= side.money_cap);
  if (reachable.length > 0) {
    const goal = dearest(reachable);
    if (side.unitCost(game.units[goal]) > side.money) return false;
    return battle.deploy(side, goal);
  }
  if (affordable.length === 0) return false;
  return battle.deploy(side, dearest(affordable));
}

// 資金をどこまで育ててから戦うか、で性格が変わる。
function makePolicy(targetLevel, defendWithin) {
  return function (battle, side) {
    tryParry(battle, side);
    if (side.busy) return;                    // レベルアップ中は手が空かない

    const underPressure = pressure(battle, side, defendWithin);
    let alive = 0;
    for (const f of side.fighters) if (f.alive) alive++;

    if (!underPressure && side.level < targetLevel) {
      if (side.canUpgrade()) { side.upgrade(); return; }
      // 貯めている間は出撃を控える。これをしないと毎tick使い切って
      // いつまでも上のレベルに届かない。
      if (alive >= 1) return;
    }

    battle.summonTrump(side);
    tryCard(battle, side);

    if (side.surge_charges > 0 && !underPressure) {
      const front = battle.live(side.index).map(f => f.x);
      if (front.length > 0) {
        // 前線が自陣寄りで止まっているなら押し上げる
        let deepest = front[0];
        for (const x of front) {
          if (Math.abs(x - side.base_x) > Math.abs(deepest - side.base_x)) deepest = x;
        }
        if (Math.abs(deepest - side.base_x) < battle.game.laneLength * 0.4) {
          battle.useSurge(side);
        }
      }
    }

    tryDeploy(battle, side);
  };
}

// 「どこまで育ててから戦うか」と「どこまで来られたら守りに戻るか」。
// **どちらも data の尺度に合わせて置き直すもの**（policy.py と同じ値）。
const POLICIES = {
  rush: makePolicy(4, 150.0),
  balanced: makePolicy(6, 120.0),
  greed: makePolicy(8, 90.0),
};

// ------------------------------------------------------------------ 人の操作
// human.py の移植。人もAIも同じ入口（policy(battle, side)）を通る。
// 押した内容はいったん待ち行列に入り、次のtickの頭で使われるので、
// 画面のフレームレートと試合の進みが分かれている。
class Controller {
  constructor() {
    this.pending = [];
    this.history = [];
    this.rejected = 0;
    this.ticks = 0;
  }

  deploy(unitId) { this.pending.push(['deploy', unitId]); }
  cast(source) { this.pending.push(['cast', `${source[0]}:${source[1]}`]); }
  upgrade() { this.pending.push(['upgrade', '']); }
  trump() { this.pending.push(['trump', '']); }

  _run(battle, side, command) {
    const kind = command[0], arg = command[1];
    if (kind === 'deploy') return battle.deploy(side, arg);
    if (kind === 'cast') {
      const parts = arg.split(':');
      return battle.startCast(side, [parts[0], parseInt(parts[1], 10)]);
    }
    if (kind === 'upgrade') {
      if (side.busy || !side.canUpgrade()) return false;
      side.upgrade();
      return true;
    }
    if (kind === 'trump') return battle.summonTrump(side);
    return false;
  }

  asPolicy() {
    const self = this;
    return function (battle, side) {
      self.ticks += 1;
      while (self.pending.length > 0) {
        const command = self.pending.shift();
        if (self._run(battle, side, command)) {
          self.history.push([self.ticks, command[0], command[1]]);
        } else {
          // 通らなかった操作は捨てる。持ち越すと、資金が貯まった
          // 瞬間に覚えのない出撃や詠唱が走る。
          self.rejected += 1;
        }
      }
    };
  }
}

const ENGINE = {
  EPS, bisectLeft, bisectRight, loadGame, isWall, cardPower,
  Fighter, Side, Battle, resultOf, POLICIES, makePolicy, Controller,
};

if (typeof module !== 'undefined' && module.exports) module.exports = ENGINE;
if (typeof globalThis !== 'undefined') globalThis.ENGINE = ENGINE;
