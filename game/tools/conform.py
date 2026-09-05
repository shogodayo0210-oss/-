"""Python の engine と JS の移植が、1tickずつ同じ盤面になるかを確かめる。

実装が2つある以上、「たぶん同じ」では意味がない。工程表で TypeScript 移植を
消したときの理由も**一致試験の重さ**だったので、移植を足すならこれも足す。

比べ方は**ビット単位**。浮動小数点をそのまま8バイトの16進で突き合わせるので、
下位1桁の食い違いも見逃さない ―― 「1e-16 の差で左右対称の試合が割れる」のを
一度踏んでいるから、丸めた比較はしない。

    $ python3 game/tools/conform.py            # 既定の12試合
    $ python3 game/tools/conform.py --matches 40
"""

from __future__ import annotations

import argparse
import json
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from game.engine.battle import Battle, Loadout          # noqa: E402
from game.engine.data import DATA_DIR, load             # noqa: E402
from game.engine.draft import commit, match_seed, stock_sequence  # noqa: E402
from game.engine.policy import POLICIES                 # noqa: E402
from game.engine.presets import PRESETS, build, trial_six  # noqa: E402

WEB = ROOT / "game" / "web"
SAMPLE_EVERY = 10          # 何tickごとに指紋を取るか（0.5秒ごと）


def bits(value) -> str:
    """float をそのまま8バイトの16進に。丸めないので下位1桁も見える。"""
    return struct.pack(">d", float(value)).hex()


def fingerprint(battle: Battle) -> list[str]:
    """その瞬間の盤面を、比較できる文字列の列にする。"""
    out = [bits(battle.t)]
    for side in battle.sides:
        out += [
            bits(side.money), str(side.level), bits(side.base_hp),
            bits(side.income_left), bits(side.gcd_left), bits(side.brought_cd),
            bits(side.upgrading_left), bits(side.deploy_lock_left),
            str(side.parry_charges), str(side.surge_charges),
            str(len(side.effects)), str(side.trump_used),
            "|".join(c or "-" for c in side.stock),
            "|".join(bits(r) for r in side.restock),
            side.casting.id if side.casting else "-",
            bits(side.cast_left), bits(side.parry_until),
            "|".join(f"{uid}={bits(cd)}" for uid, cd in sorted(side.deploy_cd.items())),
        ]
        for f in side.fighters:
            out.append("/".join([
                f.spec.id, bits(f.x), bits(f.hp), bits(f.windup_left),
                bits(f.recover_left), bits(f.stun_left), str(f.knockbacks_done),
                bits(f.summon_left),
                "inf" if f.lifespan_left == float("inf") else bits(f.lifespan_left),
            ]))
        out.append("--")
    return out


def setup(game, enemy: str, match_id: str, mirror: bool) -> dict:
    """1試合ぶんの持ち物を決める。乱数はここ（Python側）でだけ回す。

    JS には**引いた結果**だけを渡す。Mersenne Twister を移植すると、
    そこが新しい食い違いの種になるので、乱数は移植しない。
    """
    trial = trial_six()
    unit_ids = tuple(u["id"] for u in trial["roster"])
    brought, avatar, trump = trial["brought"], trial["avatar"], trial["trump"]

    seed = match_seed(
        commit(unit_ids, (brought,), trump, f"{match_id}:a"),
        commit(tuple(PRESETS[enemy][1]), (PRESETS[enemy][2]),
               PRESETS[enemy][3], f"{match_id}:b"),
        match_id)

    player = Loadout(avatar=avatar, roster=unit_ids, brought=brought,
                     trump=trump, stock_seed=f"{seed}:a")
    if mirror:
        foe = Loadout(avatar=avatar, roster=unit_ids, brought=brought,
                      trump=trump, stock_seed=f"{seed}:b")
    else:
        foe = build(game, enemy, seed, "b")

    return {
        "match_id": match_id, "enemy": enemy, "mirror": mirror,
        "a": {"avatar": player.avatar, "roster": list(player.roster),
              "brought": player.brought, "trump": player.trump,
              "stock": stock_sequence(game, player.stock_seed, 96)},
        "b": {"avatar": foe.avatar, "roster": list(foe.roster),
              "brought": foe.brought, "trump": foe.trump,
              "stock": stock_sequence(game, foe.stock_seed, 96)},
    }


def loadout_of(spec: dict) -> Loadout:
    return Loadout(avatar=spec["avatar"], roster=tuple(spec["roster"]),
                   brought=spec["brought"], trump=spec["trump"])


def run_python(game, plan: dict, policy_a: str) -> list[list[str]]:
    battle = Battle(game, loadout_of(plan["a"]), loadout_of(plan["b"]),
                    POLICIES[policy_a], POLICIES[plan["enemy"]])
    # 乱数で引いた並びを、JS に渡すのと同じものに差し替える。
    for side, key in zip(battle.sides, ("a", "b")):
        side._queue.clear()
        side._queue.extend(plan[key]["stock"])
        side.stock = []
        side.restock = [0.0] * game.stock_slots
        for _ in range(game.stock_slots):
            side.stock.append(side._draw())

    frames, ticks = [fingerprint(battle)], 0
    while not battle.finished():
        battle.step()
        ticks += 1
        if ticks % SAMPLE_EVERY == 0:
            frames.append(fingerprint(battle))
    frames.append(fingerprint(battle))
    return frames


DRIVER = r"""
const fs = require('fs');
const ENGINE = require(process.argv[2]);
const raw = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const jobs = JSON.parse(fs.readFileSync(process.argv[4], 'utf8'));
const game = ENGINE.loadGame(raw);

function bits(x) {
  const buf = new ArrayBuffer(8);
  new DataView(buf).setFloat64(0, Number(x));
  return Array.from(new Uint8Array(buf))
    .map(b => b.toString(16).padStart(2, '0')).join('');
}

function fingerprint(battle) {
  const out = [bits(battle.t)];
  for (const side of battle.sides) {
    const cds = Object.keys(side.deploy_cd).sort()
      .map(uid => `${uid}=${bits(side.deploy_cd[uid])}`).join('|');
    out.push(
      bits(side.money), String(side.level), bits(side.base_hp),
      bits(side.income_left), bits(side.gcd_left), bits(side.brought_cd),
      bits(side.upgrading_left), bits(side.deploy_lock_left),
      String(side.parry_charges), String(side.surge_charges),
      String(side.effects.length), side.trump_used ? 'True' : 'False',
      side.stock.map(c => c || '-').join('|'),
      side.restock.map(bits).join('|'),
      side.casting ? side.casting.id : '-',
      bits(side.cast_left), bits(side.parry_until), cds);
    for (const f of side.fighters) {
      out.push([
        f.spec.id, bits(f.x), bits(f.hp), bits(f.windup_left),
        bits(f.recover_left), bits(f.stun_left), String(f.knockbacks_done),
        bits(f.summon_left),
        f.lifespan_left === Infinity ? 'inf' : bits(f.lifespan_left),
      ].join('/'));
    }
    out.push('--');
  }
  return out;
}

const SAMPLE_EVERY = jobs.sample_every;
const results = [];
for (const job of jobs.plans) {
  const mk = spec => ({
    avatar: spec.avatar, roster: spec.roster,
    brought: spec.brought, trump: spec.trump,
  });
  const battle = new ENGINE.Battle(
    game, mk(job.plan.a), mk(job.plan.b),
    ENGINE.POLICIES[job.policy_a], ENGINE.POLICIES[job.plan.enemy],
    job.plan.a.stock, job.plan.b.stock);
  const frames = [fingerprint(battle)];
  let ticks = 0;
  while (!battle.finished()) {
    battle.step();
    ticks += 1;
    if (ticks % SAMPLE_EVERY === 0) frames.push(fingerprint(battle));
  }
  frames.push(fingerprint(battle));
  results.push(frames);
}
process.stdout.write(JSON.stringify(results));
"""


def raw_data(data_dir: Path = DATA_DIR) -> dict:
    names = ("characters", "cards", "trumps", "perks", "avatars", "match")
    out = {}
    for name in names:
        with open(data_dir / f"{name}.json", encoding="utf-8") as f:
            out[name] = json.load(f)
    return out


def compare(name: str, py: list[list[str]], js: list[list[str]]) -> str | None:
    """食い違った最初の場所を返す。合っていれば None。"""
    if len(py) != len(js):
        return f"{name}: 指紋の数が違う（Python {len(py)} / JS {len(js)}）"
    for i, (pf, jf) in enumerate(zip(py, js)):
        if pf == jf:
            continue
        seconds = i * SAMPLE_EVERY * 0.05
        if len(pf) != len(jf):
            return (f"{name}: {seconds:.2f}秒 で項目数が違う"
                    f"（Python {len(pf)} / JS {len(jf)}）")
        for k, (a, b) in enumerate(zip(pf, jf)):
            if a != b:
                return (f"{name}: {seconds:.2f}秒 の {k}番目が違う\n"
                        f"      Python: {a}\n      JS    : {b}")
    return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="conform")
    parser.add_argument("--matches", type=int, default=12)
    args = parser.parse_args(argv)

    game = load()
    names = sorted(POLICIES)
    plans = []
    for i in range(args.matches):
        policy_a = names[i % len(names)]
        enemy = names[(i // len(names)) % len(names)]
        mirror = (i % 2 == 0)
        plan = setup(game, enemy, f"conform-{i}", mirror)
        plans.append({"policy_a": policy_a, "plan": plan})

    print(f"{len(plans)}試合を Python と JS の両方で回して、"
          f"{SAMPLE_EVERY * 0.05:.2f}秒ごとに盤面を突き合わせる")

    py_frames = [run_python(game, job["plan"], job["policy_a"]) for job in plans]

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "driver.js").write_text(DRIVER, encoding="utf-8")
        (tmp / "raw.json").write_text(json.dumps(raw_data()), encoding="utf-8")
        (tmp / "jobs.json").write_text(
            json.dumps({"plans": plans, "sample_every": SAMPLE_EVERY}),
            encoding="utf-8")
        proc = subprocess.run(
            ["node", str(tmp / "driver.js"), str(WEB / "engine.js"),
             str(tmp / "raw.json"), str(tmp / "jobs.json")],
            capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        return 1
    js_frames = json.loads(proc.stdout)

    bad = []
    for job, py, js in zip(plans, py_frames, js_frames):
        label = (f"{job['policy_a']} vs {job['plan']['enemy']}"
                 f"{'（同じ6種）' if job['plan']['mirror'] else '（見本編成）'}"
                 f" {job['plan']['match_id']}")
        problem = compare(label, py, js)
        if problem:
            bad.append(problem)
        else:
            print(f"  一致  {label}  ―― 指紋 {len(py)}点")

    if bad:
        print()
        for line in bad:
            print("NG  " + line)
        return 1
    total = sum(len(f) for f in py_frames)
    print(f"\nOK  {len(plans)}試合 / 指紋 {total}点 がビット単位で一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
