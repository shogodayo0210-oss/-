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
    family: u.family || '人', role: u.role || '',
    lifespan_sec: 0, summon_sec: 0,
  };
  return Object.assign(spec, extra || {});
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
      cast_sec: c.cast_sec, effect: c.effect, cost: c.cost, band: c.band,
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

  const avatars = {};
  for (const a of raw.avatars.avatars) avatars[a.id] = a;

  const match = raw.match;
  return {
    units, cards, trumps, perks, avatars, match,
    laneLength: match.field.length_m,
    baseHp: match.avatar.hp,
    timeLimit: match.victory.time_limit_sec,
    economy: match.economy,
    levels: match.economy.growth.levels,
    cardRules: match.cards,
    trumpRules: match.trump,
    readability: match.readability,
    combat: match.combat,
    wallThreshold: match.roster.wall_threshold,
    stockSlots: match.cards.stock_slots,
  };
}

// ------------------------------------------------------------------ 場の1体
class Fighter {
  constructor(spec, side, x, hp, facing, summonLeft, lifespanLeft) {
    this.spec = spec;
    this.side = side;
    this.x = x;
    this.hp = hp;
    this.facing = facing;
    this.windup_left = 0.0;
    this.recover_left = 0.0;
    this.stun_left = 0.0;
    this.knockbacks_done = 0;
    this.summon_left = summonLeft === undefined ? 0.0 : summonLeft;
    this.lifespan_left = lifespanLeft === undefined ? Infinity : lifespanLeft;
  }

  get alive() { return this.hp > 0; }

  // 召喚演出が終わって、実際に戦える状態か。
  get ready() { return this.summon_left <= 0; }

  // 世界座標での攻撃が当たる帯。向きで反転する。
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
    this.level = 1;
    this.money = game.economy.start;
    // 資金は連続では増えない。何秒かごとに +N という刻みで貯まる。
    // 素の間隔を使う ―― この時点ではまだ効果がひとつも乗っていない。
    this.income_left = this.levelRow.income_every_sec;

    this.fighters = [];
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
    this.deploy_lock_left = 0.0;
    this.upgrading_left = 0.0;

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

  // いま撃てるか。資金・詠唱中・共通CD・育成中・個別CDを全部見る。
  castable(source) {
    if (this.casting !== null || this.gcd_left > 0 || this.busy) return false;
    if (source[0] === 'brought' && this.brought_cd > 0) return false;
    const card = this.cardOf(source);
    return card !== null && this.money >= card.cost;
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
  stat(name, base) {
    let value = base;
    for (const e of this.effects) {
      if (e.stat !== name) continue;
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

  unitCost(spec) { return this.stat('cost', spec.cost); }
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
    this.spacing = game.combat.unit_spacing_m;
    this.kb_stun = game.combat.knockback_stun_sec;
    this.max_units = game.match.field.max_units_per_side;
    this.t = 0.0;
    this.drops = (game.economy.milestones || []).slice();
    this._next_drop = 0;
    // そのtickの世界の見え方。全員が同じ盤面を見て動くので、
    // 「先に処理された側が先に殴れる」という順番の有利が出ない。
    this._snap = [[], []];
    this._damage = [];
    this._base_damage = [];
    this.events = [];
  }

  note(side, text) { this.events.push([this.t, side, text]); }

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
    side.fighters.push(new Fighter(spec, side.index, side.base_x, spec.hp,
                                   side.facing));
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
                                   spec.lifespan_sec + spec.summon_sec));
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
              `${card.name} を詠唱（${where}・${card.cost} / ${side.cast_left.toFixed(2)}秒）`);
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

    const target = card.apply.scope.startsWith('own') ? side : enemy;
    target.addEffect({
      stat: card.apply.stat, mult: card.apply.mult, add: card.apply.add,
      until: this.t + card.duration_sec, source: card.id,
    });
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
      until: this.t + params.duration_sec, source: 'surge',
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
  }

  // そのtickの頭で場に居た側のユニット。方針もここを見る。
  live(index) { return this._snap[index].map(pair => pair[1]); }

  targetsInBand(fighter) {
    const band = fighter.band();
    const rows = this._snap[1 - fighter.side];
    const xs = rows.map(pair => pair[0]);
    const loI = bisectLeft(xs, band[0] - EPS);
    const hiI = bisectRight(xs, band[1] + EPS);
    const found = rows.slice(loI, hiI);
    found.sort((p, q) => Math.abs(p[0] - fighter.x) - Math.abs(q[0] - fighter.x));
    return found.map(pair => pair[1]);
  }

  baseInBand(fighter) {
    const band = fighter.band();
    const baseX = this.sides[1 - fighter.side].base_x;
    return band[0] - EPS <= baseX && baseX <= band[1] + EPS;
  }

  // 前を行く味方に詰まる位置。これが無いと全員が同じ点に重なり、
  // 攻撃範囲の設計（前線範囲・後方範囲）が意味を失う。
  advanceLimit(fighter) {
    const rows = this._snap[fighter.side];
    const xs = rows.map(pair => pair[0]);
    if (fighter.facing > 0) {
      const idx = bisectRight(xs, fighter.x + EPS);
      if (idx >= xs.length) return this.game.laneLength;
      return xs[idx] - this.spacing;
    }
    const idx = bisectLeft(xs, fighter.x - EPS) - 1;
    if (idx < 0) return 0.0;
    return xs[idx] + this.spacing;
  }

  applyDamage(victim, amount) {
    const side = this.sides[victim.side];
    victim.hp -= amount;
    if (victim.hp <= 0) return;

    const kb = side.stat('knockback', victim.spec.knockback);
    if (kb < 1) return;                            // 堅陣：後退しなくなる
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
    const power = side.stat('attack', fighter.spec.attack);

    if (enemy.parry_until >= this.t) return;

    const wallLine = this.game.wallThreshold;

    // 拠点も帯の中の「的」のひとつ。近い順に、貫通の数だけ当たる。
    // 敵ユニットが1体でも居れば拠点が絶対に安全、だと両者が安い壁を
    // 出し続ける限り拠点に永久に触れられない（実測で36試合中28が0対0）。
    const targets = this.targetsInBand(fighter)
      .map(f => [Math.abs(f.x - fighter.x), f]);
    if (this.baseInBand(fighter)) {
      targets.push([Math.abs(enemy.base_x - fighter.x), null]);
    }
    targets.sort((p, q) => p[0] - q[0]);       // 同着は先に入った敵が優先

    for (const pair of targets.slice(0, fighter.spec.pierce)) {
      const victim = pair[1];
      if (victim === null) {
        this._base_damage.push([enemy, power * fighter.spec.siege_mult]);
      } else {
        const bonus = isWall(victim.spec, wallLine) ? fighter.spec.anti_wall_mult : 1.0;
        this._damage.push([victim, power * bonus]);
      }
    }
  }

  stepFighter(fighter) {
    const side = this.sides[fighter.side];
    const dt = this.tick;

    if (fighter.summon_left > 0) { fighter.summon_left -= dt; return; }
    if (fighter.stun_left > 0) { fighter.stun_left -= dt; return; }

    const intervalMult = side.stat('attack_interval', 1.0);
    if (fighter.recover_left > 0) { fighter.recover_left -= dt; return; }
    if (fighter.windup_left > 0) {
      fighter.windup_left -= dt;
      if (fighter.windup_left <= 0) {
        this.resolveAttack(fighter);
        const cycle = fighter.spec.attack_interval_sec * intervalMult;
        const windup = fighter.spec.attack_windup_sec * intervalMult;
        fighter.recover_left = Math.max(0.0, cycle - windup);
      }
      return;
    }

    if (this.targetsInBand(fighter).length > 0 || this.baseInBand(fighter)) {
      fighter.windup_left = fighter.spec.attack_windup_sec * intervalMult;
      return;
    }

    const speed = side.stat('speed', fighter.spec.speed_mps);
    const moved = fighter.x + fighter.facing * speed * dt;
    const limit = this.advanceLimit(fighter);
    fighter.x = fighter.facing > 0 ? Math.min(moved, limit) : Math.max(moved, limit);
    fighter.x = Math.max(0.0, Math.min(this.game.laneLength, fighter.x));
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
      side.upgrading_left = Math.max(0.0, side.upgrading_left - dt);
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
    for (const pair of this._base_damage) pair[0].base_hp -= pair[1];

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
  leader() {
    const a = this.advanceOf(this.sides[0]);
    const b = this.advanceOf(this.sides[1]);
    if (Math.abs(a - b) <= EPS) return null;
    return a > b ? this.sides[0] : this.sides[1];
  }

  payDrop(drop) {
    const amount = drop.amount, at = drop.at_sec;
    if (drop.to === 'leader') {
      // **押し込んでいる側だけ**に入る。安いユニットを早く出して線を
      // 上げることが、そのまま資金として返ってくる。
      const winner = this.leader();
      if (winner === null) {
        this.note(0, `${at.toFixed(0)}秒の陣地ボーナス — 互角なので配布なし`);
        return;
      }
      winner.money = Math.min(winner.money + amount, winner.money_cap);
      this.note(winner.index,
                `${at.toFixed(0)}秒の陣地ボーナス — 押し込んでいるので +${amount}`);
      return;
    }
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

  nextDropIsContested() {
    if (this._next_drop >= this.drops.length) return false;
    return this.drops[this._next_drop].to === 'leader';
  }

  finished() {
    return this.t >= this.game.timeLimit
        || this.sides.some(s => s.base_hp <= 0);
  }
}

// ------------------------------------------------------------------ 結果
function resultOf(battle) {
  const a = battle.sides[0], b = battle.sides[1];
  const hp = [Math.max(0.0, a.base_hp), Math.max(0.0, b.base_hp)];
  let winner, reason;
  if (hp[0] <= 0 || hp[1] <= 0) {
    winner = hp[1] <= 0 ? 0 : 1;
    reason = '拠点撃破';
  } else {
    const full = battle.game.baseHp;
    const dealt = [(full - hp[1]) / full, (full - hp[0]) / full];
    if (Math.abs(dealt[0] - dealt[1]) < 1e-9) {
      winner = null; reason = '時間切れ・与ダメージ同率';
    } else {
      winner = dealt[0] > dealt[1] ? 0 : 1;
      reason = '時間切れ・与ダメージ割合';
    }
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

function tryDeploy(battle, side) {
  let alive = 0;
  for (const f of side.fighters) if (f.alive) alive++;
  const affordable = side.loadout.roster.filter(uid =>
    (side.deploy_cd[uid] || 0.0) <= 0
    && side.money >= side.unitCost(battle.game.units[uid]));
  if (affordable.length === 0) return false;
  // 壁が足りない時は一番安いものを、足りている時は一番高いものを出す。
  // 同点は Python の min/max と同じく「先に出てきたほう」を採る。
  const cheap = alive < 2;
  let pick = affordable[0];
  for (const uid of affordable) {
    const c = battle.game.units[uid].cost;
    const p = battle.game.units[pick].cost;
    if (cheap ? c < p : c > p) pick = uid;
  }
  return battle.deploy(side, pick);
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

const POLICIES = {
  rush: makePolicy(2, 50.0),
  balanced: makePolicy(4, 40.0),
  greed: makePolicy(6, 30.0),
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
