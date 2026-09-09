// play/__main__.py の移植。実時間を溜めて、溜まったぶんだけ battle.step() を呼ぶ。
//
// **フレームレートと試合の進みは別物。** 画面が重くなっても試合の中身は
// 変わらない ―― engine の決定論はここで壊さない（Python 版と同じ作り）。
//
// 起動すると、まず select.js の編成画面（アバター→ユニット→切り札/呪文）を
// 見せる。「この編成で開戦」を押した時点で初めて battle を組み立てる。

'use strict';

(function () {
  const { View } = VIEW;

  const canvas = document.getElementById('screen');
  const ctx = canvas.getContext('2d', { alpha: false });
  canvas.width = VIEW.W;
  canvas.height = VIEW.H;

  const game = ENGINE.loadGame(DATA.raw);

  // 呪文ストックの並びは Python 側で引いたものを焼き込んである（build_web.py）。
  // Mersenne Twister を移植すると、そこが Python 版との食い違いの種になる。
  // 1枚1文字に畳んであるので、ここで呪文の名前に戻す。
  // ―― この並びは編成（誰の何体）ではなく「相手の方針」と試合番号だけで
  // 引いてあるので、編成画面でどのユニットを選んでも読み替えずに使える。
  const ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  const STOCKS = {};
  for (const name in DATA.stocks.matches) {
    STOCKS[name] = DATA.stocks.matches[name].map(pair => pair.map(packed => {
      const out = [];
      for (const ch of packed) out.push(DATA.stocks.cards[ALPHABET.indexOf(ch)]);
      return out;
    }));
  }
  const MATCHES = STOCKS.balanced.length;

  // 絵は編成画面と戦闘画面の両方が使うので、ここで1回だけ読み込む。
  const sprites = new VIEW.Sprites(DATA.art);
  const selectScreen = new SELECT.SelectScreen(
    ctx, game, DATA.raw, DATA.preset, DATA.art, sprites);

  let screen = 'select';         // 'select'（編成中） | 'battle'
  let loading = false;           // 「開戦」を押してから View の絵が揃うまで
  let enemy = 'balanced';
  let matchNo = -1;              // beginBattle() が最初の試合で +1 する
  let speed = 1.0;
  let paused = false;
  let battle = null;
  let controller = null;
  let view = null;
  let currentLoadout = null;     // {avatar, roster, brought, trump}
  const record = [];             // 遊んだ試合の結果（工程表 A-4 の記録用）

  function beginBattle(loadoutChoice) {
    loading = true;
    currentLoadout = loadoutChoice;
    const unitSpecs = loadoutChoice.roster.map(id => game.units[id]);
    view = new View(ctx, unitSpecs, game, DATA.art, sprites);
    view.ready().then(() => {
      loading = false;
      screen = 'battle';
      matchNo += 1;
      newBattle();
      syncPanels();
    });
  }

  function openSelect() {
    screen = 'select';
    selectScreen.step = 0;
    syncPanels();
  }

  function newBattle() {
    const pair = STOCKS[enemy][matchNo % MATCHES];
    controller = new ENGINE.Controller();
    const me = {
      avatar: currentLoadout.avatar, roster: currentLoadout.roster,
      brought: currentLoadout.brought, trump: currentLoadout.trump,
    };
    // 既定で**相手もまったく同じ持ち物**（工程表 塊A-3）。
    // 相手だけ編成という状態では、負けても何が悪いのか分からない。
    battle = new ENGINE.Battle(game, me, me, controller.asPolicy(),
                               ENGINE.POLICIES[enemy], pair[0], pair[1]);
    paused = false;
    accumulator = 0.0;
    counted = false;
    syncChrome();
  }

  function send(action) {
    if (!action) return;
    const kind = action[0], arg = action[1];
    if (kind === 'deploy') controller.deploy(arg);
    else if (kind === 'cast') controller.cast(arg);
    else if (kind === 'upgrade') controller.upgrade();
    else if (kind === 'trump') controller.trump();
  }

  // ---------------------------------------------------------------- 入力
  function canvasPoint(event) {
    const box = canvas.getBoundingClientRect();
    return [(event.clientX - box.left) * (VIEW.W / box.width),
            (event.clientY - box.top) * (VIEW.H / box.height)];
  }

  canvas.addEventListener('pointerdown', event => {
    event.preventDefault();
    const p = canvasPoint(event);
    if (screen === 'select') {
      if (loading) return;              // 開戦処理中は二重に受け付けない
      const action = selectScreen.actionAt(p[0], p[1]);
      const loadout = selectScreen.apply(action);
      if (loadout) beginBattle(loadout);
      return;
    }
    if (battle.finished()) { restart(); return; }
    send(view.actionAt(p[0], p[1]));
  });

  window.addEventListener('keydown', event => {
    const key = event.key.toLowerCase();
    if (screen === 'select') {
      if (loading) return;
      const action = selectScreen.actionForKey(key);
      if (action) {
        event.preventDefault();
        const loadout = selectScreen.apply(action);
        if (loadout) beginBattle(loadout);
      }
      return;
    }
    if (key === ' ' || event.code === 'Space') {
      event.preventDefault();
      paused = !paused;
      syncChrome();
      return;
    }
    if (key === 'r') {
      // 決着後の R は次の試合。試合中の R はストック3枠目。
      if (battle.finished()) { restart(); return; }
    }
    const action = view.actionForKey(key);
    if (action) { event.preventDefault(); send(action); }
  });

  function restart() {
    matchNo += 1;
    newBattle();
  }

  // ---------------------------------------------------------------- 操作盤
  const els = {
    bar: document.getElementById('bar'),
    cols: document.getElementById('cols'),
    enemy: document.getElementById('enemy'),
    speed: document.getElementById('speed'),
    pause: document.getElementById('pause'),
    again: document.getElementById('again'),
    reselect: document.getElementById('reselect'),
    tally: document.getElementById('tally'),
    log: document.getElementById('log'),
  };

  els.enemy.addEventListener('change', () => {
    enemy = els.enemy.value;
    if (screen === 'battle') restart();
  });
  els.speed.addEventListener('change', () => {
    speed = parseFloat(els.speed.value);
  });
  els.pause.addEventListener('click', () => { paused = !paused; syncChrome(); });
  els.again.addEventListener('click', restart);
  els.reselect.addEventListener('click', openSelect);

  function syncChrome() {
    els.pause.textContent = paused ? '再開' : '一時停止';
  }

  // 編成中は戦闘の操作盤を隠す。今どちらの画面かが一目で分かるように。
  function syncPanels() {
    const inBattle = screen === 'battle';
    if (els.bar) els.bar.hidden = !inBattle;
    if (els.cols) els.cols.hidden = !inBattle;
  }

  // 記録はこの端末の中だけに置く。どこにも送らない。
  // 読めなくても落ちない（プライベートウィンドウなど、例外を投げる環境がある）。
  const STORE = 'siege.record.v1';
  function loadRecord() {
    try {
      const saved = JSON.parse(localStorage.getItem(STORE) || '[]');
      if (Array.isArray(saved)) record.push(...saved);
    } catch (e) { /* 読めなければ空のまま始める */ }
  }
  function saveRecord() {
    try { localStorage.setItem(STORE, JSON.stringify(record.slice(-50))); }
    catch (e) { /* 書けなくても遊べる */ }
  }

  // 決着したら1行だけ残す。工程表 A-4 は「1試合ごとに終わった直後に1行書く」
  // なので、機械で書ける半分（結果と時間）はこちらで持っておく。
  let counted = false;
  function noteResult() {
    if (counted) return;
    counted = true;
    const r = ENGINE.resultOf(battle);
    const full = game.baseHp;
    record.push({
      enemy,
      win: r.winner === 0 ? '勝ち' : (r.winner === null ? '分け' : '負け'),
      seconds: r.seconds,
      dealt: (full - r.base_hp[1]) / full,
      taken: (full - r.base_hp[0]) / full,
      level: r.level[0],
    });
    saveRecord();
    renderRecord();
  }

  function renderRecord() {
    const wins = record.filter(r => r.win === '勝ち').length;
    const draws = record.filter(r => r.win === '分け').length;
    els.tally.textContent =
      `${record.length}試合  ${wins}勝 ${record.length - wins - draws}敗 ${draws}分`;
    els.log.innerHTML = '';
    record.slice().reverse().forEach((r, i) => {
      const row = document.createElement('div');
      row.className = 'row';
      row.innerHTML =
        `<b>${record.length - i}</b>` +
        `<span class="${r.win === '勝ち' ? 'w' : (r.win === '分け' ? 'd' : 'l')}">${r.win}</span>` +
        `<span>${r.enemy}</span>` +
        `<span>${r.seconds.toFixed(0)}秒</span>` +
        `<span>与 ${(r.dealt * 100).toFixed(0)}%</span>` +
        `<span>被 ${(r.taken * 100).toFixed(0)}%</span>` +
        `<span>財布 Lv${r.level}</span>`;
      els.log.appendChild(row);
    });
  }

  // ---------------------------------------------------------------- 本体
  const TICK = game.combat.tick_sec;
  let accumulator = 0.0;
  let last = 0;

  function frame(now) {
    // 実時間。0.25秒より大きく飛んだぶんは捨てる（タブを戻した後など、
    // 一気に何十tickも進むのを防ぐ）。
    const dt = last ? Math.min((now - last) / 1000.0, 0.25) : 0.0;
    last = now;

    if (screen === 'battle' && battle) {
      if (!paused && !battle.finished()) {
        accumulator += dt * speed;
        while (accumulator >= TICK && !battle.finished()) {
          battle.step();
          accumulator -= TICK;
        }
      }
      if (battle.finished()) noteResult();
      view.draw(battle, 0, paused);
    } else {
      selectScreen.draw();
    }
    requestAnimationFrame(frame);
  }

  // 絵とフォントが揃ってから始める。揃う前に描くと、文字幅が後でずれる。
  const fonts = document.fonts ? document.fonts.ready : Promise.resolve();
  loadRecord();
  renderRecord();
  syncPanels();
  Promise.all([sprites.load(), fonts]).then(() => {
    selectScreen.draw();
    requestAnimationFrame(frame);
  });
})();
