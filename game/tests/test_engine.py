"""シミュレータと data の回帰テスト。

    python3 -m unittest discover -s game/tests -t .
"""

import unittest

from game.engine.battle import Battle, Effect, Fighter, Loadout, Result
from game.engine.data import load
from game.engine.draft import draw_random_slots, match_seed, pick_template
from game.engine.policy import POLICIES
from game.engine.presets import trial_roster
from game.tools import validate


GAME = load()


def loadout(avatar="bulwark", roster=("grunt", "shieldman", "archer"),
            brought="warcry", trump="colossus", stock_seed="t"):
    return Loadout(avatar=avatar, roster=tuple(roster), brought=brought,
                   trump=trump, stock_seed=stock_seed)


def battle(a=None, b=None, policy="balanced", money=None):
    a = a or loadout()
    b = b or loadout()
    bt = Battle(GAME, a, b, POLICIES[policy], POLICIES[policy])
    if money is not None:                 # 呪文は資金を食うので、試験では持たせる
        for side in bt.sides:
            side.money = money
    return bt


class TestSymmetry(unittest.TestCase):
    """左右対称の試合は引き分けで終わる。

    ここが割れていた不具合を2つ潰してある：
      1) tick内で先に処理される側が先に殴れていた（同時解決にした）
      2) 位置の比較が浮動小数点の下位桁に左右され、「前の味方に詰まるか」の
         判定が 1e-16 の差でひっくり返っていた（許容差を入れた）
    どちらも「片方の側が有利」という形でバランスの数字を汚す。
    """

    def test_identical_sides_draw(self):
        for name in ("rush", "balanced", "greed"):
            with self.subTest(policy=name):
                same = loadout(roster=("grunt", "spear", "shieldman", "archer"))
                result = battle(same, same, policy=name).run()
                self.assertIsNone(result.winner)
                self.assertEqual(result.base_hp[0], result.base_hp[1])


class TestDeterminism(unittest.TestCase):
    def test_same_input_same_match(self):
        first = battle().run()
        second = battle().run()
        self.assertEqual(first.seconds, second.seconds)
        self.assertEqual(first.base_hp, second.base_hp)
        self.assertEqual(len(first.events), len(second.events))

    def test_seed_comes_from_both_commits(self):
        one = match_seed("a", "b", "m")
        self.assertEqual(one, match_seed("a", "b", "m"))
        self.assertNotEqual(one, match_seed("b", "a", "m"))
        self.assertNotEqual(one, match_seed("a", "b", "m2"))


class TestAttackBand(unittest.TestCase):
    """攻撃範囲は帯。死角の内側には当たらない。"""

    def setUp(self):
        self.bt = battle()
        self.mortar = GAME.units["mortar"]      # [42, 80]
        self.grunt = GAME.units["grunt"]        # [0, 12]

    def place(self, spec, side, x):
        fighter = Fighter(spec=spec, side=side, x=x, hp=float(spec.hp),
                          facing=1 if side == 0 else -1)
        self.bt.sides[side].fighters.append(fighter)
        return fighter

    def test_blind_spot_blocks_close_targets(self):
        shooter = self.place(self.mortar, 0, 0.0)
        self.place(self.grunt, 1, 20.0)         # 死角42mの内側
        self.bt.snapshot()
        self.assertEqual(self.bt.targets_in_band(shooter), [])

    def test_band_hits_beyond_the_blind_spot(self):
        shooter = self.place(self.mortar, 0, 0.0)
        far = self.place(self.grunt, 1, 60.0)   # 帯[42,80]の中
        self.bt.snapshot()
        self.assertEqual(self.bt.targets_in_band(shooter), [far])

    def test_pierce_limits_how_many_are_hit(self):
        shooter = self.place(GAME.units["sweeper"], 0, 0.0)   # 貫通6
        for i in range(9):
            self.place(self.grunt, 1, 10.0 + i)
        self.bt.snapshot()
        found = self.bt.targets_in_band(shooter)
        self.assertEqual(len(found[: shooter.spec.pierce]), 6)
        self.assertGreater(len(found), 6)       # 押せば通る


class TestWalls(unittest.TestCase):
    """壁は別のタグではなく「拠点を割れないユニット」。壁特攻はその的を叩く。"""

    def setUp(self):
        self.line = GAME.wall_threshold

    def test_wall_is_defined_by_siege_mult(self):
        self.assertTrue(GAME.units["grunt"].is_wall(self.line))
        self.assertTrue(GAME.units["shieldman"].is_wall(self.line))
        self.assertFalse(GAME.units["twin"].is_wall(self.line))
        self.assertFalse(GAME.units["mortar"].is_wall(self.line))

    def test_walls_hit_softly(self):
        median = sorted(u.dps for u in GAME.units.values())[len(GAME.units) // 2]
        for unit in GAME.units.values():
            if unit.is_wall(self.line):
                self.assertLessEqual(unit.dps, median, unit.name)

    def test_anti_wall_bonus_applies_only_to_walls(self):
        bt = battle()
        sweeper = GAME.units["sweeper"]          # 対壁 2.2
        wall = GAME.units["grunt"]
        other = GAME.units["twin"]

        attacker = Fighter(spec=sweeper, side=0, x=0.0, hp=float(sweeper.hp), facing=1)
        bt.sides[0].fighters.append(attacker)
        victims = [
            Fighter(spec=wall, side=1, x=10.0, hp=float(wall.hp), facing=-1),
            Fighter(spec=other, side=1, x=20.0, hp=float(other.hp), facing=-1),
        ]
        bt.sides[1].fighters.extend(victims)
        bt.snapshot()
        bt.resolve_attack(attacker)

        dealt = {v.spec.id: amount for v, amount in bt._damage}
        self.assertAlmostEqual(dealt["grunt"], sweeper.attack * sweeper.anti_wall_mult)
        self.assertAlmostEqual(dealt["twin"], sweeper.attack)

    def test_someone_can_break_walls(self):
        breakers = [u for u in GAME.units.values() if u.anti_wall_mult > 1.5]
        self.assertTrue(breakers, "壁を崩す答えが1体も無いと、壁を並べるだけで前線が保たれる")
        for unit in breakers:
            self.assertLessEqual(unit.far, GAME.far_threshold,
                                 f"{unit.name}: 壁特攻は接近戦の役割に限る")


class TestParry(unittest.TestCase):
    """見切りは相手のカードを潰す。0.3秒の窓が詠唱の完了を覆えば不発になる。"""

    def test_parry_cancels_the_card(self):
        bt = battle(loadout(avatar="bulwark"), loadout(avatar="scout"), money=3000)
        defender, attacker = bt.sides
        bt.start_cast(attacker, ("brought", 0))
        bt.use_parry(defender)
        bt.resolve_cast(attacker)
        self.assertEqual(attacker.effects, [])
        self.assertGreater(attacker.brought_cd, 0)

    def test_card_lands_without_a_parry(self):
        bt = battle(loadout(avatar="scout"), loadout(avatar="scout"), money=3000)
        attacker = bt.sides[1]
        bt.start_cast(attacker, ("brought", 0))
        bt.resolve_cast(attacker)
        self.assertEqual(len(attacker.effects), 1)
        self.assertEqual(attacker.effects[0].stat, "attack")


class TestCardsTouchUnitStats(unittest.TestCase):
    """カードはユニットが持っている数字を触るだけ。専用の仕組みを持たない。"""

    def test_knockback_immunity(self):
        bt = battle(loadout(brought="bulwark"), loadout(), money=3000)
        side = bt.sides[0]
        spec = GAME.units["grunt"]
        fighter = Fighter(spec=spec, side=0, x=50.0, hp=float(spec.hp), facing=1)
        side.fighters.append(fighter)
        bt.start_cast(side, ("brought", 0))
        side.cast_left = 0
        bt.resolve_cast(side)
        bt.apply_damage(fighter, spec.hp * 0.9)
        self.assertEqual(fighter.x, 50.0)          # 堅陣：後退しない

    def test_deploy_cost_discount(self):
        """徴発はコストを掛け算で下げる。**額は整数に切り上げる。**

        安いユニットで測ると切り上げに埋もれる（兵卒1の7割は0.7→1）ので、
        差が桁で見える高いユニットで測る。
        """
        import math
        bt = battle(loadout(brought="levy", roster=("grunt", "titan")),
                    loadout(), money=3000)
        side = bt.sides[0]
        spec = GAME.units["titan"]
        full = side.unit_cost(spec)
        bt.start_cast(side, ("brought", 0))
        side.cast_left = 0
        bt.resolve_cast(side)
        self.assertEqual(side.unit_cost(spec), math.ceil(full * 0.7 - 1e-9))
        self.assertLess(side.unit_cost(spec), full)


class TestNoStrictUpgrade(unittest.TestCase):
    """コストが高いというだけで、安いユニットの上位互換にはならない。"""

    HIGHER = (("体力", lambda u: u.hp), ("DPS", lambda u: u.dps),
              ("射程", lambda u: u.far), ("速度", lambda u: u.speed_mps),
              ("対拠点", lambda u: u.siege_mult),
              ("対壁", lambda u: u.anti_wall_mult), ("貫通", lambda u: u.pierce))
    LOWER = (("ノックバック", lambda u: u.knockback),
             ("攻撃発生", lambda u: u.attack_windup_sec),
             ("死角", lambda u: u.near))

    def test_cheap_units_win_on_price(self):
        """上位互換は居てよい。差別化は**コストの差**で付ける。

        双剣1体ぶんの資金で兵卒は5体出せて、体力の合計では上回る ――
        これが成り立っていれば、全項目で負けていても安い側に役目がある。
        成り立たないなら、その安いキャラは存在する意味を失う。
        """
        units = list(GAME.units.values())
        for poor in units:
            for rich in units:
                if poor.cost >= rich.cost:
                    continue
                dominates = (all(f(rich) >= f(poor) for _, f in self.HIGHER)
                             and all(f(rich) <= f(poor) for _, f in self.LOWER))
                if not dominates:
                    continue
                n = rich.cost / poor.cost
                self.assertTrue(
                    poor.hp * n > rich.hp or poor.dps * n > rich.dps,
                    f"{rich.name}({rich.cost}) は {poor.name}({poor.cost}) の"
                    f"全項目で上回る上に、同じ資金ぶん{n:.0f}体でも届かない")

    def test_someone_needs_protecting(self):
        """高コストの高火力・高射程が、安い壁より脆いこと。
        これが無いと壁に仕事が無く、前線を取る意味も薄れる。"""
        units = list(GAME.units.values())
        import statistics
        rich_line = statistics.median(u.cost for u in units)
        toughest_cheap = max(u.hp for u in units if u.cost <= 2)
        fragile = [u for u in units
                   if u.cost >= rich_line and u.hp < toughest_cheap
                   and u.far > GAME.far_threshold]
        self.assertTrue(fragile,
                        f"安い壁（体力{toughest_cheap}）より脆い高コストの遠距離が居ない")


class TestGatedCards(unittest.TestCase):
    """拠点が削られてから開く札。**押し込まれている側だけが持てる手。**"""

    def test_gate_blocks_while_healthy(self):
        bt = battle(loadout(brought="backwater"), loadout(), money=3000)
        side = bt.sides[0]
        card = GAME.cards["backwater"]
        self.assertTrue(card.gated)
        self.assertFalse(side.unlocked(card))
        self.assertFalse(bt.start_cast(side, ("brought", 0)))

    def test_gate_opens_once_the_base_is_hurt(self):
        bt = battle(loadout(brought="backwater"), loadout(), money=3000)
        side = bt.sides[0]
        card = GAME.cards["backwater"]
        side.base_hp = GAME.base_hp * card.base_hp_gate
        self.assertTrue(side.unlocked(card))
        self.assertTrue(bt.start_cast(side, ("brought", 0)))

    def test_someone_can_come_back(self):
        gated = [c for c in GAME.cards.values() if c.gated]
        self.assertTrue(gated, "押し込まれた側だけが持てる札が1枚も無い")
        for card in gated:
            self.assertEqual(card.target, "own")

    def test_the_gate_stays_open_long_enough_to_use(self):
        """解禁されてから拠点が落ちるまでに、札を撃ち切る時間があること。

        攻城口の上限が無かった頃は、前線が破れた瞬間に毎秒11700が入り、
        拠点HPは1秒たらずで消えた。解禁から決着までの猶予は実測2〜8秒で、
        詠唱0.8秒＋効果8秒の札はどうやっても間に合わない ―― **傷ついた
        拠点という状態が存在しないと、この札は存在しないのと同じ。**
        """
        assault = GAME.base_hp / GAME.combat["siege_cap_dps"]
        for card in [c for c in GAME.cards.values() if c.gated]:
            self.assertGreaterEqual(assault, card.cast_sec + card.duration_sec,
                                    card.name)


class TestRecovery(unittest.TestCase):
    """後隙。**振りかぶりが長いほど長く、その間は余分に殴られる。**"""

    def test_recovery_follows_the_windup(self):
        for spec in list(GAME.units.values()) + list(GAME.trumps.values()):
            self.assertLessEqual(
                spec.attack_windup_sec + spec.attack_recover_sec,
                spec.attack_interval_sec + 1e-9, spec.name)

    def test_the_big_swings_have_the_big_openings(self):
        """1発が大きいものほど後隙が長い。大技を振らせて差し込む択の土台。"""
        big = max(GAME.units.values(), key=lambda u: u.attack)
        small = min(GAME.units.values(), key=lambda u: u.attack)
        self.assertGreater(big.attack_recover_sec, small.attack_recover_sec)

    def test_a_hit_in_the_opening_lands_harder(self):
        bt = battle()
        spec = GAME.units["oni"]
        victim = Fighter(spec=spec, side=1, x=100.0, hp=float(spec.hp), facing=-1)
        bt.sides[1].fighters = [victim]
        bt.apply_damage(victim, 1000.0)
        plain = spec.hp - victim.hp

        victim.hp = float(spec.hp)
        victim.exposed_left = 0.3
        bt.apply_damage(victim, 1000.0)
        opened = spec.hp - victim.hp
        self.assertAlmostEqual(opened / plain, GAME.combat["recover_damage_mult"])


class TestSpawnSeq(unittest.TestCase):
    """出撃順の通し番号（`Fighter.spawn_seq`）は、他の個体が死んでもずれない。

    `Battle.step` は最後に死んだ個体を間引いて `side.fighters` を作り直す
    （生存者だけの配列を新しく作る）ので、配列の添字をそのまま「出撃順」
    として使うと、誰かが死ぬたびに残った個体の番号がずれる ―― 見た目の
    重なり順（view.py/view.js）がそこでガクつく不具合になっていた。
    """

    def test_spawn_seq_survives_pruning_of_earlier_deaths(self):
        bt = battle(money=1000)
        side = bt.sides[0]
        # 同じユニットは再出撃CDに引っかかるので、3種を1体ずつ出す。
        for unit_id in ("grunt", "shieldman", "archer"):
            self.assertTrue(bt.deploy(side, unit_id))
        self.assertEqual([f.spawn_seq for f in side.fighters], [0, 1, 2])

        side.fighters[0].hp = 0.0          # 最初に出した1体だけ倒す
        bt.step()

        self.assertEqual(len(side.fighters), 2)
        self.assertEqual([f.spawn_seq for f in side.fighters], [1, 2])


class TestKnockbackIntangibility(unittest.TestCase):
    """**ノックバック中は当たり判定が消える。**

    下がっている0.4秒は的にならないので、殴られないし、敵の足も止めない
    ―― 押し戻した相手をすり抜けて前線が進む。
    回数の多いキャラ（双剣・狂戦士・亡霊将＝4回）は、以前は下がるたびに
    無防備な0.4秒を差し出していた。
    """

    def pair(self, uid="twin", gap=5.0):
        bt = battle()
        spec = GAME.units[uid]
        victim = Fighter(spec=spec, side=1, x=100.0, hp=float(spec.hp), facing=-1)
        bt.sides[1].fighters = [victim]
        attacker = Fighter(spec=GAME.units["grunt"], side=0, x=100.0 - gap,
                           hp=1e9, facing=1)
        bt.sides[0].fighters = [attacker]
        return bt, attacker, victim

    def test_a_knocked_back_unit_is_not_a_target(self):
        bt, attacker, victim = self.pair()
        bt.snapshot()
        self.assertEqual(bt.targets_in_band(attacker), [victim])
        victim.stun_left = GAME.combat["knockback_stun_sec"]
        bt.snapshot()
        self.assertEqual(bt.targets_in_band(attacker), [])

    def test_it_still_counts_on_the_field(self):
        """判定が消えるだけで、場から居なくなるわけではない。"""
        bt, _, victim = self.pair()
        victim.stun_left = 0.4
        bt.snapshot()
        self.assertEqual(bt.live(1), [victim])

    def test_the_enemy_walks_through_instead_of_stopping(self):
        """**すり抜け。** 的が消えれば足は止まらない。"""
        def advance(stunned):
            bt, attacker, victim = self.pair(gap=5.0)
            victim.stun_left = 0.4 if stunned else 0.0
            start = attacker.x
            for _ in range(4):
                bt.snapshot()
                bt.step_fighter(attacker)
            return attacker.x - start

        self.assertEqual(advance(stunned=False), 0.0)      # 止まって殴る
        self.assertGreater(advance(stunned=True), 0.0)     # 通り抜ける

    def test_the_hit_that_knocks_back_still_lands(self):
        """判定が消えるのは*次の*tickから。当てた一撃は無効にならない。"""
        bt, _, victim = self.pair()
        spec = victim.spec
        bt.apply_damage(victim, spec.hp / spec.knockback + 1)
        self.assertLess(victim.hp, spec.hp)
        self.assertGreater(victim.stun_left, 0)

    def test_one_hit_pushes_once_even_across_two_segments(self):
        """**一撃で区切りを2つ跨いでも、下がるのは1回だけ。** 区切りは2つ減る。

        仕様として採用してある ―― 同じ総ダメージなら手数のほうが押し戻せる
        ので、一撃の重さは「削る力」、手数は「押す力」と割れる。
        そのうえ大技は相手の後退の残り回数を先に食うので、撃ち込むほど
        相手は踏みとどまる。
        """
        bt, _, victim = self.pair()
        spec = victim.spec
        distance = GAME.combat["knockback_distance_m"]
        start = victim.x

        bt.apply_damage(victim, spec.hp * 0.55)          # 4段のうち2段ぶん
        self.assertAlmostEqual(abs(victim.x - start), distance)
        self.assertEqual(victim.knockbacks_done, 2)      # 区切りは2つ消費

        bt.apply_damage(victim, spec.hp * 0.20)          # 3段目
        self.assertAlmostEqual(abs(victim.x - start), distance * 2)
        self.assertEqual(victim.knockbacks_done, 3)

    def test_many_small_hits_push_further_than_one_big_one(self):
        """同じ総ダメージなら、手数のほうが押し込める。"""
        def pushed(hits):
            bt, _, victim = self.pair()
            start = victim.x
            share = victim.spec.hp * 0.75 / hits
            for _ in range(hits):
                bt.apply_damage(victim, share)
            return abs(victim.x - start)

        self.assertGreater(pushed(3), pushed(1))

    def test_the_ones_that_retreat_most_can_afford_the_trip(self):
        """よく押し戻されるキャラほど、往復に耐える体力が要る。"""
        floor = GAME.roster_rules["min_hp_per_knockback"]
        for unit in GAME.units.values():
            if unit.knockback >= 4:
                self.assertGreaterEqual(unit.hp / unit.knockback, floor * 1.5,
                                        unit.name)


class TestFrontAnchoredAttacks(unittest.TestCase):
    """前線起点の射抜き。**安い1体を前に置いて全部止める**への答え。"""

    def line_of_grunts(self, uid):
        bt = battle()
        spec = GAME.units[uid]
        bt.sides[0].fighters = [
            Fighter(spec=spec, side=0, x=100.0, hp=float(spec.hp), facing=1)]
        grunt = GAME.units["grunt"]
        bt.sides[1].fighters = [
            Fighter(spec=grunt, side=1, x=140.0 + i * 10, hp=1e9, facing=-1)
            for i in range(5)]
        bt.snapshot()
        return bt, bt.sides[0].fighters[0]

    def test_the_window_starts_at_the_nearest_enemy(self):
        bt, shooter = self.line_of_grunts("arbalest")
        lo, hi = bt.strike_band(shooter)
        self.assertAlmostEqual(lo, 140.0)
        self.assertAlmostEqual(hi, 140.0 + GAME.units["arbalest"].spread_m)

    def test_it_takes_the_blocker_and_what_is_behind_it(self):
        bt, shooter = self.line_of_grunts("arbalest")
        hit = [round(f.x) for f in bt.targets_in_band(shooter)]
        self.assertIn(140, hit)                    # 前に立った1体
        self.assertIn(150, hit)                    # その後ろも巻き込む

    def test_a_plain_long_range_unit_only_takes_the_blocker(self):
        bt, shooter = self.line_of_grunts("archer")
        hit = bt.targets_in_band(shooter)[: GAME.units["archer"].pierce]
        self.assertEqual([round(f.x) for f in hit], [140])

    def test_the_window_never_blankets_the_field(self):
        cap = GAME.roster_rules["spread_ratio_max"]
        for spec in GAME.units.values():
            if spec.spread_m > 0:
                self.assertLessEqual(spec.spread_m, spec.far * cap + 1e-9,
                                     spec.name)


class TestDuels(unittest.TestCase):
    """**値段が倍以上違うなら、基本的には高いほうが1v1で勝つ。**

    2.6（同じ資金ぶん並べたら安いほうが勝てる）と対になる約束。
    片方だけだと「高いキャラを出す理由」か「安いキャラを出す理由」の
    どちらかが消える。

    ただし**絶対ではない**。全組を通すことを要求すると、単純な殴り合い
    以外で値段ぶんの仕事をするキャラ（特性で噛み合う・妨害する・支援する）が
    作れなくなるので、傾向として縛る。
    """

    def test_the_expensive_unit_usually_wins_one_on_one(self):
        report = validate.Report()
        validate.check_duels(GAME, report)
        self.assertEqual(report.errors, [])

    def test_the_rule_is_a_tendency_not_an_absolute(self):
        """下限は100%ではない ―― 例外を作れる余地が data 側に要る。"""
        self.assertLess(GAME.roster_rules["duel_pass_ratio"], 1.0)

    def test_units_built_around_synergy_sit_outside_it(self):
        """特性持ちは決闘で測らない。編成と噛み合って初めて効くので。"""
        report = validate.Report()
        losses = validate.check_duels(GAME, report)
        self.assertIsInstance(losses, list)
        traited = [u for u in GAME.units.values() if u.trait]
        self.assertTrue(traited, "特性を持つキャラが1体も居ない")
        for line in losses:
            for unit in traited:
                self.assertNotIn(unit.name, line)

    def test_the_cheap_unit_still_wins_per_coin(self):
        """決闘の規則を足したせいで 2.6 が壊れていないこと。"""
        report = validate.Report()
        validate.check_characters(GAME, report)
        self.assertEqual(report.errors, [])


class TestRaceSpells(unittest.TestCase):
    """種族呪文。**編成にその種族が3体以上無いと撃てず、その種族にだけ効く。**"""

    ANIMALS = ("hound", "boar", "raider")

    def test_a_scattered_roster_cannot_cast_it(self):
        card = next(c for c in GAME.cards.values() if c.race == "動物")
        bt = battle(loadout(roster=("grunt", "shieldman", "hound"),
                            brought=card.id), loadout(), money=3000)
        self.assertFalse(bt.sides[0].unlocked(card))
        self.assertFalse(bt.start_cast(bt.sides[0], ("brought", 0)))

    def test_a_single_race_roster_can(self):
        card = next(c for c in GAME.cards.values() if c.race == "動物")
        bt = battle(loadout(roster=self.ANIMALS, brought=card.id),
                    loadout(), money=3000)
        self.assertTrue(bt.sides[0].unlocked(card))
        self.assertTrue(bt.start_cast(bt.sides[0], ("brought", 0)))

    def test_it_only_touches_its_own_race(self):
        card = next(c for c in GAME.cards.values() if c.race == "動物")
        bt = battle(loadout(roster=self.ANIMALS, brought=card.id),
                    loadout(), money=3000)
        side = bt.sides[0]
        side.add_effect(Effect(stat=card.apply.stat, mult=card.apply.mult,
                               add=None, until=1e9, source=card.id,
                               race=card.race))
        beast = GAME.units["hound"]
        human = GAME.units["grunt"]
        self.assertNotEqual(
            side.stat(card.apply.stat, 1.0, beast.race), 1.0)
        self.assertEqual(side.stat(card.apply.stat, 1.0, human.race), 1.0)
        # 全軍ぶん（資金・出撃コスト）には一切かからない
        self.assertEqual(side.stat(card.apply.stat, 1.0), 1.0)

    def test_every_race_has_exactly_one(self):
        report = validate.Report()
        validate.check_races(GAME, report)
        self.assertEqual(report.errors, [])


class TestCastLimit(unittest.TestCase):
    """**呪文は1試合3回まで。** 資金とクールタイムだけだと、撃てるときに
    撃つのが常に正解で「いつ撃つか」が択になっていなかった。"""

    def side_with_money(self):
        bt = battle(loadout(brought="morale"), loadout(), money=3000)
        return bt, bt.sides[0]

    def test_the_fourth_cast_is_refused(self):
        bt, side = self.side_with_money()
        limit = GAME.casts_per_match
        for i in range(limit):
            side.brought_cd = 0.0
            side.gcd_left = 0.0
            self.assertTrue(bt.start_cast(side, ("brought", 0)), f"{i + 1}回目")
            side.casting = None
        side.brought_cd = 0.0
        side.gcd_left = 0.0
        self.assertFalse(bt.start_cast(side, ("brought", 0)))
        self.assertEqual(side.casts_left, 0)

    def test_a_parried_cast_still_costs_a_use(self):
        """見切られても回数は戻らない ―― 資金と同じ扱い。"""
        bt = battle(loadout(avatar="bulwark", brought="morale"),
                    loadout(avatar="bulwark"), money=3000)
        side = bt.sides[0]
        before = side.casts_left
        bt.start_cast(side, ("brought", 0))
        self.assertTrue(bt.use_parry(bt.sides[1]), "相手が見切りを持っていない")
        bt.resolve_cast(side)
        self.assertEqual(side.casts_left, before - 1)

    def test_it_is_fewer_than_the_cards_you_hold(self):
        """持っている枚数より少ないから、回数が択になる。"""
        held = GAME.card_rules["stock_slots"] + GAME.card_rules["brought"]
        self.assertLess(GAME.casts_per_match, held)


class TestSuddenDeath(unittest.TestCase):
    """**時間では勝敗を決めない。** 3分を過ぎたら雷が盤面を壊す。"""

    def test_the_clock_no_longer_ends_the_match(self):
        bt = battle()
        bt.t = GAME.time_limit + 1.0
        self.assertFalse(bt.finished())          # 昔はここで時間切れだった
        bt.t = GAME.hard_stop
        self.assertTrue(bt.finished())           # 安全弁だけが止める

    def test_the_safety_stop_has_real_room_after_the_storm_starts(self):
        """安全弁は雷が仕事をする時間を奪わない程度に、離れた場所にある。"""
        self.assertGreater(GAME.hard_stop - GAME.time_limit, 60.0 * 5,
                           "雷が5発降る前に安全弁が来ると、雷そのものが機能しない")

    def test_the_storm_starts_on_time(self):
        bt = battle()
        self.assertFalse(bt.sudden_death)
        bt.t = GAME.time_limit
        self.assertTrue(bt.sudden_death)

    def test_a_bolt_is_announced_before_it_lands(self):
        bt = battle()
        bt.t = GAME.time_limit
        bt.schedule_bolt()
        self.assertTrue(bt.pending)
        lands_at = min(b[0] for b in bt.pending)
        self.assertAlmostEqual(lands_at - bt.t, bt.storm_warn)
        self.assertGreaterEqual(bt.storm_warn,
                                GAME.readability["human_reaction_sec"])

    def test_bolts_fall_in_mirrored_pairs(self):
        """**必ず対で落ちる。** 片側だけだと同じ編成どうしが引き分けなくなる。"""
        bt = battle()
        bt.t = GAME.time_limit
        bt.schedule_bolt()
        spots = sorted(b[1] for b in bt.pending)
        self.assertEqual(len(spots), 2)
        self.assertAlmostEqual(spots[0] + spots[1], GAME.lane_length)

    def test_it_kills_everything_in_range_on_both_sides(self):
        bt = battle()
        grunt, titan = GAME.units["grunt"], GAME.units["titan"]
        near_a = Fighter(spec=grunt, side=0, x=100.0, hp=float(grunt.hp), facing=1)
        near_b = Fighter(spec=titan, side=1, x=105.0, hp=float(titan.hp), facing=-1)
        far_off = Fighter(spec=titan, side=1, x=200.0, hp=float(titan.hp), facing=-1)
        bt.sides[0].fighters = [near_a]
        bt.sides[1].fighters = [near_b, far_off]

        bt.strike(102.0, 20.0)
        self.assertFalse(near_a.alive)           # 体力700でも
        self.assertFalse(near_b.alive)           # 体力6600でも
        self.assertTrue(far_off.alive)           # 範囲の外は無傷

    def test_the_lane_always_keeps_a_corridor(self):
        """半径がレーンを覆うと、誰も敵拠点まで歩けなくなる。"""
        widest = GAME.sudden_death["radius_max_m"] * 2
        self.assertLessEqual(widest, GAME.lane_length / 3.0)

    def test_the_same_match_always_gets_the_same_storm(self):
        def spots():
            bt = battle()
            bt.t = GAME.time_limit
            for _ in range(5):
                bt.schedule_bolt()
            return [round(b[1], 9) for b in bt.pending]

        self.assertEqual(spots(), spots())

    def test_the_radius_grows_once_per_pair_not_per_bolt(self):
        """半径の伸びは**対（1組）につき1回**。1組は2発落ちるが、伸びは1回ぶん。

        bolts_fallen は対ではなく個々の落雷を数える（1組で2ずつ増える）。
        伸びをそのまま bolts_fallen で刻むと、12→14→…→20のはずが
        12→16→20になってしまう（半分の対で頭打ちに達する）。
        """
        bt = battle()
        bt.t = GAME.time_limit
        base = GAME.sudden_death["radius_m"]
        growth = GAME.sudden_death["radius_growth_m"]
        seen = []
        for _ in range(3):
            bt.schedule_bolt()
            pair = bt.pending[-2:]
            seen.append(pair[0][2])
            for _, where, radius in pair:
                bt.strike(where, radius)
        self.assertEqual(seen, [base, base + growth, base + growth * 2])

    def test_the_safety_stop_is_not_a_timeout_verdict(self):
        """安全弁で終わっても、時間切れの与ダメージ判定は使わない。

        両拠点が残ったまま試合が終わるのは hard_stop（安全弁）だけ ――
        時間切れという結末は無くしたので、勝者が付いてはいけない。
        """
        bt = battle()
        bt.sides[0].base_hp = 100.0
        bt.sides[1].base_hp = 50.0    # 与ダメージ割合なら片方が勝ってしまう値
        bt.t = GAME.hard_stop
        result = Result.of(bt)
        self.assertIsNone(result.winner)
        self.assertEqual(result.reason, "安全弁（決着せず）")


class TestSiegeCap(unittest.TestCase):
    """**拠点は一撃で落ちない。** 攻城口は詰まるので、寄せた数だけ速くならない。"""

    def crowd_at_the_base(self, count):
        bt = battle()
        spec = GAME.units["siegetower"]          # 対拠点がいちばん高い部類
        enemy_base = bt.sides[1].base_x
        bt.sides[0].fighters = [
            Fighter(spec=spec, side=0, x=enemy_base - 1.0,
                    hp=float(spec.hp), facing=1)
            for _ in range(count)]
        return bt

    def test_the_base_takes_at_most_the_cap(self):
        cap = GAME.combat["siege_cap_dps"]
        bt = self.crowd_at_the_base(20)
        before = bt.sides[1].base_hp
        for _ in range(40):                      # 2秒ぶん
            bt.step()
        dealt = before - bt.sides[1].base_hp
        self.assertLessEqual(dealt, cap * 2.0 + 1e-6)

    def test_massing_does_not_speed_it_up_past_the_cap(self):
        """20体は5体より速くない。上限に張り付いたら頭打ち。"""
        def dealt(count):
            bt = self.crowd_at_the_base(count)
            before = bt.sides[1].base_hp
            for _ in range(60):
                bt.step()
            return before - bt.sides[1].base_hp

        self.assertAlmostEqual(dealt(20), dealt(40), places=6)

    def test_a_single_leaker_is_slower_than_a_broken_line(self):
        """1体すり抜けることと前線を割ることに、差が残っていること。"""
        def dealt(count):
            bt = self.crowd_at_the_base(count)
            before = bt.sides[1].base_hp
            for _ in range(60):
                bt.step()
            return before - bt.sides[1].base_hp

        self.assertLess(dealt(1), dealt(20))


class TestTraits(unittest.TestCase):
    """特性が触れるのは**出撃コストだけ**。戦闘の数字には一切効かない。"""

    EVIL = ("ghoul", "hexer", "wraith", "warlock",
            "assassin", "revenant", "warlord", "oni")

    def test_kinship_pays_off_for_a_single_race_roster(self):
        spec = GAME.units["warlord"]
        mixed = battle(loadout(roster=("grunt", "hound", "archer", "sweeper",
                                       "mortar", "siegetower", "warlord",
                                       "titan"))).sides[0]
        same = battle(loadout(roster=self.EVIL)).sides[0]
        self.assertEqual(mixed.unit_cost(spec), spec.cost)
        self.assertLess(same.unit_cost(spec), spec.cost * 0.7)

    def test_chain_reads_the_last_deployment(self):
        bt = battle(loadout(roster=("grunt", "titan")), loadout(), money=9000)
        side = bt.sides[0]
        spec = GAME.units["titan"]
        self.assertEqual(side.unit_cost(spec), spec.cost)
        self.assertTrue(bt.deploy(side, "titan"))       # 直前が古代兵器になる
        self.assertEqual(side.unit_cost(spec),
                         spec.cost - GAME.traits["chain"].params["amount"])

    def test_desperate_only_helps_the_losing_side(self):
        bt = battle(loadout(roster=("grunt", "ballista")), loadout(), money=9000)
        side = bt.sides[0]
        spec = GAME.units["ballista"]
        self.assertEqual(side.unit_cost(spec), spec.cost)
        gate = GAME.traits["desperate"].params["base_hp_at_most"]
        side.base_hp = GAME.base_hp * gate
        self.assertLess(side.unit_cost(spec), spec.cost)

    def test_traits_never_touch_combat(self):
        """特性はコスト以外の項目を持たない、を機械で押さえる。"""
        from game.engine import data as D
        for trait in GAME.traits.values():
            self.assertIn(trait.kind, D.TRAIT_KINDS)
            self.assertTrue(trait.kind.startswith("cost_"), trait.name)


class TestSpells(unittest.TestCase):
    """持ち込み1枚 ＋ ランダムに補充されるストック3枠。どちらも資金を払う。"""

    def test_casting_costs_money(self):
        bt = battle(loadout(brought="warcry"), loadout(), money=3000)
        side = bt.sides[0]
        before = side.money
        cost = GAME.cards["warcry"].cost
        self.assertTrue(bt.start_cast(side, ("brought", 0)))
        self.assertAlmostEqual(side.money, before - cost)

    def test_too_poor_to_cast(self):
        bt = battle(loadout(brought="bulwark"), loadout(), money=0)
        side = bt.sides[0]
        self.assertFalse(bt.start_cast(side, ("brought", 0)))
        self.assertIsNone(side.casting)

    def test_stock_is_consumed_and_refilled(self):
        bt = battle(money=9000)
        side = bt.sides[0]
        self.assertTrue(all(side.stock), "開始時はストックが埋まっている")
        first = side.stock[0]
        self.assertTrue(bt.start_cast(side, ("stock", 0)))
        self.assertIsNone(side.stock[0], "撃った枠は空になる")
        for _ in range(int(side.restock_sec / bt.tick) + 2):
            bt.step()
        self.assertIsNotNone(side.stock[0], "時間が経てば補充される")
        self.assertNotEqual(side.stock[0], None)
        del first

    def test_stock_has_no_duplicates(self):
        side = battle().sides[0]
        filled = [c for c in side.stock if c]
        self.assertEqual(len(filled), len(set(filled)),
                         "同じ札が並ぶと、選ぶ意味が薄くなる")

    def test_same_seed_same_stock(self):
        a = battle(loadout(stock_seed="x"), loadout(stock_seed="x")).sides
        self.assertEqual(a[0].stock, a[1].stock)
        b = battle(loadout(stock_seed="x"), loadout(stock_seed="y")).sides
        self.assertNotEqual(b[0].stock, b[1].stock)

    def test_cost_rises_with_power(self):
        """コストの高さがそのまま強さの帯になっている（あなたの設計）。

        条件付きの札（拠点が減っていないと撃てない）は、撃てないまま終わる
        試合があるぶんだけ効果が大きい。帯を見るときはその差を引く。
        """
        bonus = GAME.gate_power_bonus
        for lower, upper in (("軽", "中"), ("中", "重")):
            low = GAME.cards_in_band(lower)
            high = GAME.cards_in_band(upper)
            self.assertLess(max(c.cost for c in low), min(c.cost for c in high))
            self.assertLess(max(c.rated_power(bonus) for c in low),
                            min(c.rated_power(bonus) for c in high))


class TestWallet(unittest.TestCase):
    """財布を育てると、貯まる上限と貯まる速度の両方が上がる。"""

    def test_upgrade_raises_both_cap_and_rate(self):
        side = battle().sides[0]
        for _ in range(len(GAME.levels) - 1):
            cap, rate = side.money_cap, side.income
            side.money = side.upgrade_cost
            side.upgrade()
            self.assertGreater(side.money_cap, cap)
            self.assertGreater(side.income, rate)

    def test_no_dead_step_before_the_top_unlock(self):
        """一番高いユニットが解禁されるまで、育てても何も増えない段が無いこと。

        そこから先（上限だけが伸びる段）は死に段ではない ―― コストが1〜10に
        なったので、上限の余りは「大型を1体持ったまま呪文も抱える」ための枠になる。
        """
        costs = sorted(u.cost for u in GAME.units.values())
        top = max(costs)
        seen = 0
        for level in GAME.levels:
            now = sum(1 for c in costs if c <= level["max"])
            if seen < len(costs):
                self.assertGreater(now, seen,
                                   f"レベル{level['level']} で何も解禁されない")
            seen = now
            if level["max"] >= top:
                break
        else:
            self.fail("最も高いユニットがどのレベルでも解禁されない")

    def test_headroom_above_the_priciest_unit(self):
        """最終上限は最も高いユニットより広いこと。
        ぴったりだと、大型を出す資金を貯めている間は呪文が一切撃てなくなる。"""
        top = max(u.cost for u in GAME.units.values())
        self.assertGreater(GAME.levels[-1]["max"], top)

    def test_income_arrives_in_steps(self):
        """資金は連続ではなく刻みで入る（あなたの指定）。

        方針を止めて測る ―― 動かしたままだと、同じtickの出撃で減ったぶんと
        混ざって「刻み」が見えなくなる。
        """
        idle = lambda battle, side: None            # noqa: E731
        bt = Battle(GAME, loadout(), loadout(), idle, idle)
        side = bt.sides[0]
        side.money = 0.0
        every = GAME.levels[0]["income_every_sec"]
        amount = GAME.levels[0]["income_amount"]
        seen = []
        for _ in range(int(every * 3 / bt.tick)):
            bt.step()
            seen.append(side.money)
        steps = [(a, b) for a, b in zip(seen, seen[1:]) if b > a]
        self.assertTrue(steps, "資金が一度も増えていない")
        for before, after in steps:
            # 上限で切られた最後の1回だけは、刻みより小さくてよい
            clipped = abs(after - side.money_cap) < 1e-9
            self.assertTrue(abs(after - before - amount) < 1e-6 or clipped,
                            f"刻みではなく連続で増えている（{before} → {after}）")

    def test_upgrade_blocks_everything(self):
        """育てている間は何も出せない（設計書4.3）。"""
        bt = battle(money=9000)
        side = bt.sides[0]
        side.upgrade()
        self.assertTrue(side.busy)
        self.assertFalse(bt.deploy(side, "grunt"))
        self.assertFalse(bt.start_cast(side, ("brought", 0)))


class TestField(unittest.TestCase):
    def test_lane_is_three_times_the_longest_reach(self):
        """レーンは最長射程の3倍以上。

        110m対120mだった頃は、自陣に立った砲が敵拠点の10m手前まで届き、
        押し込んだ側が一歩も動かずに拠点を削れた ―― 「先に押し込んだ側の勝ち」
        の正体がこれ。射程がレーンの一部にしかならない長さが要る。
        """
        ratio = GAME.roster_rules["lane_per_reach_min"]
        self.assertGreaterEqual(GAME.lane_length, GAME.max_reach * ratio)
        longest = max(list(GAME.units.values()) + list(GAME.trumps.values()),
                      key=lambda u: u.far)
        self.assertLessEqual(longest.far, GAME.max_reach, longest.name)

    def test_units_do_not_queue_behind_each_other(self):
        """味方どうしは詰まらない。**立ち位置は射程が決める。**

        隊列間隔で並ばせていた頃は、自陣に押し込まれた側の20体が数十mに
        詰まって前の1体しか殴れず、どんなに強い編成でも拠点に1ダメージも
        入らなかった（36試合すべて0対0の引き分け）。
        """
        bt = battle()
        spec = GAME.units["grunt"]
        crowd = [Fighter(spec=spec, side=0, x=0.0, hp=float(spec.hp), facing=1)
                 for _ in range(5)]
        bt.sides[0].fighters.extend(crowd)
        for _ in range(20):
            bt.step()
        # 敵が居ないので全員が同じだけ進む。誰も互いを塞がない。
        self.assertTrue(all(f.x > 0 for f in crowd))
        self.assertEqual(len({round(f.x, 6) for f in crowd}), 1)


class TestDraft(unittest.TestCase):
    def test_both_sides_draw_the_same_tiers(self):
        seed = match_seed("x", "y", "m")
        template = pick_template(GAME, seed)
        owned = list(GAME.units)
        chosen = ("grunt", "spear", "archer", "shieldman", "twin", "sweeper")
        a = draw_random_slots(GAME, seed, "a", owned, chosen, template)
        b = draw_random_slots(GAME, seed, "b", owned, chosen, template)
        self.assertEqual([GAME.units[u].tier for u in a],
                         [GAME.units[u].tier for u in b])

    def test_chosen_units_are_never_drawn(self):
        seed = match_seed("x", "y", "m")
        chosen = ("grunt", "spear", "archer")
        drawn = draw_random_slots(GAME, seed, "a", list(GAME.units), chosen,
                                  pick_template(GAME, seed))
        self.assertFalse(set(drawn) & set(chosen))


class TestData(unittest.TestCase):
    def test_validator_passes(self):
        report = validate.Report()
        validate.check_avatars(GAME, report)
        validate.check_cards(GAME, report)
        validate.check_characters(GAME, report)
        validate.check_range_price(GAME, report)
        validate.check_races(GAME, report)
        validate.check_traits(GAME, report)
        validate.check_field(GAME, report)
        validate.check_roster_size(GAME, report)
        validate.check_milestones(GAME, report)
        validate.check_economy(GAME, report)
        validate.check_trumps(GAME, report)
        validate.check_readability(GAME, report)
        self.assertEqual(report.errors, [])

    def test_trump_is_affordable_while_it_can_still_matter(self):
        """解禁した瞬間に払える必要はない ―― 貯めること自体が択なので。
        ただし**使う時間が残っているうち**には届かないといけない。"""
        deadline = GAME.time_limit * 0.7
        reachable = validate.money_at(GAME, deadline)
        for trump in GAME.trumps.values():
            self.assertLessEqual(trump.cost, reachable, trump.name)


if __name__ == "__main__":
    unittest.main()
