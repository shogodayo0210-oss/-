"""シミュレータと data の回帰テスト。

    python3 -m unittest discover -s game/tests -t .
"""

import unittest

from game.engine.battle import Battle, Fighter, Loadout
from game.engine.data import load
from game.engine.draft import draw_random_slots, match_seed, pick_template
from game.engine.policy import POLICIES
from game.tools import validate


GAME = load()


def loadout(avatar="bulwark", roster=("grunt", "shield", "archer"),
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
                same = loadout(roster=("grunt", "spear", "shield", "archer"))
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
        self.mortar = GAME.units["mortar"]      # [70, 150]
        self.grunt = GAME.units["grunt"]        # [0, 12]

    def place(self, spec, side, x):
        fighter = Fighter(spec=spec, side=side, x=x, hp=float(spec.hp),
                          facing=1 if side == 0 else -1)
        self.bt.sides[side].fighters.append(fighter)
        return fighter

    def test_blind_spot_blocks_close_targets(self):
        shooter = self.place(self.mortar, 0, 0.0)
        self.place(self.grunt, 1, 30.0)         # 死角70mの内側
        self.bt.snapshot()
        self.assertEqual(self.bt.targets_in_band(shooter), [])

    def test_band_hits_beyond_the_blind_spot(self):
        shooter = self.place(self.mortar, 0, 0.0)
        far = self.place(self.grunt, 1, 100.0)  # 帯の中
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
        self.assertTrue(GAME.units["shield"].is_wall(self.line))
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
            self.assertLessEqual(unit.far, 50, f"{unit.name}: 壁特攻は接近戦の役割に限る")


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
        bt = battle(loadout(brought="levy"), loadout(), money=3000)
        side = bt.sides[0]
        spec = GAME.units["grunt"]
        full = side.unit_cost(spec)
        bt.start_cast(side, ("brought", 0))
        side.cast_left = 0
        bt.resolve_cast(side)
        self.assertAlmostEqual(side.unit_cost(spec), full * 0.7)


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
        toughest_cheap = max(u.hp for u in units if u.cost <= 2)
        fragile = [u for u in units
                   if u.cost >= 7 and u.hp < toughest_cheap and u.far > 50]
        self.assertTrue(fragile,
                        f"安い壁（体力{toughest_cheap}）より脆い高コストの遠距離が居ない")


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
        """コストの高さがそのまま強さの帯になっている（あなたの設計）。"""
        for lower, upper in (("軽", "中"), ("中", "重")):
            low = GAME.cards_in_band(lower)
            high = GAME.cards_in_band(upper)
            self.assertLess(max(c.cost for c in low), min(c.cost for c in high))
            self.assertLess(max(c.power for c in low), min(c.power for c in high))


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


class TestFieldFits(unittest.TestCase):
    def test_cap_fits_in_the_lane(self):
        """入りきらない数を上限にすると、前線が詰まって誰も攻め落とせない。
        実測で、上限30体（入るのは20体）のとき与ダメージが平均7%だった。"""
        fits = int(GAME.lane_length / GAME.combat["unit_spacing_m"])
        self.assertLessEqual(GAME.match["field"]["max_units_per_side"], fits)


class TestDraft(unittest.TestCase):
    def test_both_sides_draw_the_same_tiers(self):
        seed = match_seed("x", "y", "m")
        template = pick_template(GAME, seed)
        owned = list(GAME.units)
        chosen = ("grunt", "spear", "archer", "shield", "twin", "sweeper")
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
