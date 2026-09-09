// 戦闘の前に置く編成画面。README 3章の「6選択＋2抽選」の簡略版で、
// ここでは**8種類まで直接選ぶ**（commit-reveal も鏡像抽選もまだやらない ――
// 大まかな形を先に置く）。
//
// 相手は `main.js` が組む対戦で**自分とまったく同じ編成をAIが操作する**
// （既存のtrialと同じ考え方）ので、ここで選んだものがそのまま両陣営の中身になる。
//
// view.js と同じ約束：Canvas に1フレーム描くだけ、盤面（選択状態）はこちらが持つ。

'use strict';

(function () {
  const W = 1140, H = 712;
  const BG = '#171c22', PANEL_2 = '#212b36';
  const INK = '#dfe6ec', MUTED = '#7d8d9c', RULE = '#2b343e';
  const ACCENT = '#3ecad9', GOLD = '#e0aa46', GREEN = '#4fa196';

  const JP = '"Zen Kaku Gothic New","Hiragino Kaku Gothic ProN","Yu Gothic",Meiryo,sans-serif';
  const F_TINY = `12px ${JP}`;
  const F_SMALL = `14px ${JP}`;
  const F_BODY = `16px ${JP}`;
  const F_BOLD = `700 18px ${JP}`;
  const F_TITLE = `900 25px ${JP}`;

  const STEPS = ['avatar', 'units', 'loadout'];
  const MAX_UNITS = 8;

  class SelectScreen {
    constructor(ctx, game, raw, preset, art, sprites) {
      this.ctx = ctx;
      this.game = game;
      this.sprites = sprites;
      this.races = art.races;

      this.avatars = raw.avatars.avatars;
      this.units = raw.characters.characters.slice()
        .sort((a, b) => a.cost - b.cost);        // 値段の安い順に並べる
      this.cards = raw.cards.cards;
      this.trumps = raw.trumps.trumps;

      const trial = preset.trial;
      this.step = 0;
      this.avatarId = trial.avatar;
      this.unitIds = new Set(trial.roster.map(u => u.id));
      this.broughtId = trial.brought;
      this.trumpId = trial.trump;

      this._rects = [];   // このフレームの当たり判定。draw() のたびに作り直す
    }

    // -------------------------------------------------------------- 状態
    toggleUnit(id) {
      if (this.unitIds.has(id)) { this.unitIds.delete(id); return; }
      if (this.unitIds.size >= MAX_UNITS) return;   // 8止まり
      this.unitIds.add(id);
    }

    loadout() {
      return {
        avatar: this.avatarId,
        roster: Array.from(this.unitIds),
        brought: this.broughtId,
        trump: this.trumpId,
      };
    }

    canAdvance() {
      if (this.step === 0) return !!this.avatarId;
      if (this.step === 1) return this.unitIds.size >= 1;
      return !!this.broughtId && !!this.trumpId;
    }

    // action は [kind, arg] の対。呼ぶ側は中身を知らなくていい（view.js と同じ形）。
    apply(action) {
      if (!action) return null;
      const kind = action[0], arg = action[1];
      if (kind === 'avatar') { this.avatarId = arg; return null; }
      if (kind === 'unit') { this.toggleUnit(arg); return null; }
      if (kind === 'trump') { this.trumpId = arg; return null; }
      if (kind === 'brought') { this.broughtId = arg; return null; }
      if (kind === 'back') { this.step = Math.max(0, this.step - 1); return null; }
      if (kind === 'next') {
        if (this.canAdvance()) this.step = Math.min(STEPS.length - 1, this.step + 1);
        return null;
      }
      if (kind === 'start') return this.canAdvance() ? this.loadout() : null;
      return null;
    }

    actionForKey(key) {
      if (key === 'escape' || key === 'backspace') return ['back'];
      if (key === 'enter') return [this.step === STEPS.length - 1 ? 'start' : 'next'];
      return null;
    }

    // -------------------------------------------------------------- 部品
    fill(rect, color) {
      this.ctx.fillStyle = color;
      this.ctx.fillRect(rect[0], rect[1], rect[2], rect[3]);
    }

    stroke(rect, color, width) {
      const ctx = this.ctx;
      ctx.strokeStyle = color;
      ctx.lineWidth = width || 1;
      const o = (width || 1) / 2;
      ctx.strokeRect(rect[0] + o, rect[1] + o, rect[2] - o * 2, rect[3] - o * 2);
    }

    text(str, font, color, x, y, align) {
      const ctx = this.ctx;
      ctx.font = font;
      ctx.fillStyle = color;
      ctx.textAlign = align || 'left';
      ctx.textBaseline = 'middle';
      ctx.fillText(str, x, y);
    }

    // 収まらなければ末尾を省略記号に落とす。日本語は分かち書きが無いので
    // 単語単位ではなく1文字ずつ削る。
    truncate(str, font, maxWidth) {
      const ctx = this.ctx;
      ctx.font = font;
      if (ctx.measureText(str).width <= maxWidth) return str;
      let s = str;
      while (s.length > 0 && ctx.measureText(s + '…').width > maxWidth) s = s.slice(0, -1);
      return s + '…';
    }

    // 最大 maxLines 行まで折り返す。収まらないぶんは最後の行を省略記号にする。
    wrapLines(str, font, maxWidth, maxLines) {
      const ctx = this.ctx;
      ctx.font = font;
      const lines = [];
      let cur = '';
      let used = 0;
      for (const ch of str) {
        if (cur && ctx.measureText(cur + ch).width > maxWidth) {
          lines.push(cur);
          used += cur.length;
          cur = ch;
          if (lines.length >= maxLines) { cur = ''; break; }
        } else {
          cur += ch;
        }
      }
      if (cur && lines.length < maxLines) { lines.push(cur); used += cur.length; }
      if (used < str.length && lines.length) {
        let last = lines[lines.length - 1];
        while (last.length && ctx.measureText(last + '…').width > maxWidth) last = last.slice(0, -1);
        lines[lines.length - 1] = last + '…';
      }
      return lines;
    }

    card(rect, selected) {
      this.fill(rect, selected ? '#20303a' : PANEL_2);
      this.stroke(rect, selected ? ACCENT : RULE, selected ? 2 : 1);
    }

    // このフレームで押せる矩形として登録する。actionAt() が最後に見る。
    hit(rect, action) { this._rects.push({ rect, action }); }

    // -------------------------------------------------------------- 見出し
    header() {
      this.fill([0, 0, W, 78], '#1b232c');
      this.fill([0, 78, W, 1], RULE);
      const titles = ['① アバターを選ぶ', '② 出撃ユニットを選ぶ', '③ 切り札と持ち込み呪文'];
      const subs = [
        'アバターは拠点そのもの。ダメージはここに入ります（数字には影響しません）。',
        `出撃できる種類を選びます（最大${MAX_UNITS}種・いま${this.unitIds.size}/${MAX_UNITS}）。` +
        '相手はあなたとまったく同じ編成をAIが操作します。',
        '切り札は1体・1試合1回。持ち込み呪文は最初から使える1枚です。',
      ];
      this.text(titles[this.step], F_TITLE, INK, 32, 30, 'left');
      this.text(subs[this.step], F_SMALL, MUTED, 32, 58, 'left');

      for (let i = 0; i < STEPS.length; i++) {
        const x = W - 32 - (STEPS.length - 1 - i) * 24;
        this.ctx.beginPath();
        this.ctx.fillStyle = i === this.step ? ACCENT : (i < this.step ? GREEN : RULE);
        this.ctx.arc(x, 39, 5, 0, Math.PI * 2);
        this.ctx.fill();
      }
    }

    // -------------------------------------------------------------- ①
    drawAvatars() {
      const cols = 4, gap = 18, left = 32, top = 100;
      const cw = Math.floor((W - left * 2 - gap * (cols - 1)) / cols);
      const ch = 152;
      this.avatars.forEach((a, i) => {
        const col = i % cols, row = Math.floor(i / cols);
        const x = left + col * (cw + gap), y = top + row * (ch + gap);
        const rect = [x, y, cw, ch];
        const selected = a.id === this.avatarId;
        this.card(rect, selected);
        this.hit(rect, ['avatar', a.id]);

        const img = this.sprites.avatar(a.id);
        if (img && img.complete && img.naturalWidth) {
          this.ctx.imageSmoothingEnabled = false;
          const w = img.naturalWidth * 2, h = img.naturalHeight * 2;
          this.ctx.drawImage(img, x + 12, y + ch - 12 - h, w, h);
        }

        this.text(a.name, F_BOLD, selected ? ACCENT : INK, x + cw - 12, y + 20, 'right');
        this.text(a.look, F_TINY, GOLD, x + cw - 12, y + 40, 'right');
        const lines = this.wrapLines(a.concept || '', F_TINY, cw - 24, 3);
        lines.forEach((line, li) => this.text(line, F_TINY, MUTED, x + 12, y + 62 + li * 16, 'left'));
      });
    }

    // -------------------------------------------------------------- ②
    drawUnits() {
      const cols = 7, gap = 6, left = 27, top = 96, ch = 76;
      const cw = Math.floor((W - left * 2 - gap * (cols - 1)) / cols);
      this.units.forEach((u, i) => {
        const col = i % cols, row = Math.floor(i / cols);
        const x = left + col * (cw + gap), y = top + row * (ch + gap);
        const rect = [x, y, cw, ch];
        const selected = this.unitIds.has(u.id);
        this.card(rect, selected);
        this.hit(rect, ['unit', u.id]);

        const raceColor = this.races[u.race] || MUTED;
        this.text(String(u.cost), F_SMALL, selected ? GOLD : MUTED, x + 8, y + 14, 'left');
        this.text(u.tier, F_TINY, MUTED, x + cw - 10, y + 14, 'right');
        this.text(this.truncate(u.name, F_BOLD, cw - 16), F_BOLD,
                  selected ? ACCENT : INK, x + cw / 2, y + ch / 2 + 4, 'center');
        this.fill([x + 8, y + ch - 15, 8, 8], raceColor);
        this.text(this.truncate(u.race, F_TINY, cw - 24), F_TINY, MUTED, x + 20, y + ch - 10, 'left');
      });
    }

    // -------------------------------------------------------------- ③
    drawLoadout() {
      // 切り札（3体だけなので縦に並べる）
      const tx = 32, ttop = 100, tw = 260, th = 150, tgap = 16;
      this.text('切り札', F_SMALL, MUTED, tx, ttop - 16, 'left');
      this.trumps.forEach((t, i) => {
        const y = ttop + i * (th + tgap);
        const rect = [tx, y, tw, th];
        const selected = t.id === this.trumpId;
        this.card(rect, selected);
        this.hit(rect, ['trump', t.id]);
        this.text(t.name, F_BOLD, selected ? ACCENT : INK, tx + 14, y + 24, 'left');
        this.text(String(t.cost), F_BODY, selected ? GOLD : MUTED, tx + tw - 14, y + 24, 'right');
        const lines = this.wrapLines(t.role || '', F_TINY, tw - 28, 4);
        lines.forEach((line, li) => this.text(line, F_TINY, MUTED, tx + 14, y + 50 + li * 16, 'left'));
      });

      // 持ち込み呪文（38枚あるので細かい格子）
      const cx = 320, ctop = 100, ccols = 6, cgap = 8, cch = 64;
      const ccw = Math.floor((W - cx - 32 - cgap * (ccols - 1)) / ccols);
      this.text('持ち込み呪文（1枚）', F_SMALL, MUTED, cx, ctop - 16, 'left');
      this.cards.forEach((c, i) => {
        const col = i % ccols, row = Math.floor(i / ccols);
        const x = cx + col * (ccw + cgap), y = ctop + row * (cch + cgap);
        const rect = [x, y, ccw, cch];
        const selected = c.id === this.broughtId;
        this.card(rect, selected);
        this.hit(rect, ['brought', c.id]);
        this.text(this.truncate(c.name, F_SMALL, ccw - 16), F_SMALL,
                  selected ? ACCENT : INK, x + ccw / 2, y + 20, 'center');
        this.text(String(c.cost), F_TINY, selected ? GOLD : MUTED, x + 8, y + cch - 12, 'left');
        this.text(c.band || '', F_TINY, MUTED, x + ccw - 8, y + cch - 12, 'right');
      });
    }

    // -------------------------------------------------------------- 下段
    footer() {
      const y = H - 56, h = 40;

      const backRect = [32, y, 140, h];
      const canBack = this.step > 0;
      this.card(backRect, false);
      this.stroke(backRect, canBack ? MUTED : RULE, 1);
      this.text('戻る', F_BODY, canBack ? INK : RULE, 32 + 70, y + h / 2, 'center');
      if (canBack) this.hit(backRect, ['back']);

      const ready = this.canAdvance();
      const last = this.step === STEPS.length - 1;
      const label = last ? 'この編成で開戦' : '次へ';
      const nrect = [W - 32 - 220, y, 220, h];
      this.fill(nrect, ready ? '#1a2828' : '#181f27');
      this.stroke(nrect, ready ? GREEN : RULE, 2);
      this.text(label, F_BOLD, ready ? GREEN : MUTED, nrect[0] + 110, y + h / 2, 'center');
      if (ready) this.hit(nrect, [last ? 'start' : 'next']);
    }

    // -------------------------------------------------------------- 1フレーム
    draw() {
      this._rects = [];
      this.fill([0, 0, W, H], BG);
      this.header();
      if (this.step === 0) this.drawAvatars();
      else if (this.step === 1) this.drawUnits();
      else this.drawLoadout();
      this.footer();
    }

    actionAt(x, y) {
      for (const { rect, action } of this._rects) {
        if (x >= rect[0] && x < rect[0] + rect[2] && y >= rect[1] && y < rect[1] + rect[3]) {
          return action;
        }
      }
      return null;
    }
  }

  const SELECT = { SelectScreen, MAX_UNITS };
  if (typeof module !== 'undefined' && module.exports) module.exports = SELECT;
  if (typeof globalThis !== 'undefined') globalThis.SELECT = SELECT;
})();
