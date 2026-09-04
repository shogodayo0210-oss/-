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
            deck=("warcry", "mire", "bulwark"), trump="colossus"):
    return Loadout(avatar=avatar, roster=tuple(roster), deck=tuple(deck),
                   trump=trump)


def battle(a=None, b=None, policy="balanced"):
    a = a or loadout()
    b = b or loadout()
    return Battle(GAME, a, b, POLICIES[policy], POLICIES[policy])


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


class TestParry(unittest.TestCase):
    """見切りは相手のカードを潰す。0.3秒の窓が詠唱の完了を覆えば不発になる。"""

    def test_parry_cancels_the_card(self):
        bt = battle(loadout(avatar="bulwark"), loadout(avatar="scout"))
        defender, attacker = bt.sides
        bt.start_cast(attacker, "warcry")
        bt.use_parry(defender)
        bt.resolve_cast(attacker)
        self.assertEqual(attacker.effects, [])
        self.assertGreater(attacker.card_cd["warcry"], 0)

    def test_card_lands_without_a_parry(self):
        bt = battle(loadout(avatar="scout"), loadout(avatar="scout"))
        attacker = bt.sides[1]
        bt.start_cast(attacker, "warcry")
        bt.resolve_cast(attacker)
        self.assertEqual(len(attacker.effects), 1)
        self.assertEqual(attacker.effects[0].stat, "attack")


class TestCardsTouchUnitStats(unittest.TestCase):
    """カードはユニットが持っている数字を触るだけ。専用の仕組みを持たない。"""

    def test_knockback_immunity(self):
        bt = battle()
        side = bt.sides[0]
        spec = GAME.units["grunt"]
        fighter = Fighter(spec=spec, side=0, x=50.0, hp=float(spec.hp), facing=1)
        side.fighters.append(fighter)
        bt.start_cast(side, "bulwark")
        side.cast_left = 0
        bt.resolve_cast(side)
        bt.apply_damage(fighter, spec.hp * 0.9)
        self.assertEqual(fighter.x, 50.0)          # 堅陣：後退しない

    def test_deploy_cost_discount(self):
        bt = battle()
        side = bt.sides[0]
        spec = GAME.units["grunt"]
        full = side.unit_cost(spec)
        bt.start_cast(side, "levy")
        side.cast_left = 0
        bt.resolve_cast(side)
        self.assertAlmostEqual(side.unit_cost(spec), full * 0.7)


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

    def test_trump_is_affordable_when_it_unlocks(self):
        unlock = GAME.trump_rules["unlock_at_sec"]
        reachable = validate.money_at(GAME, unlock)
        for trump in GAME.trumps.values():
            self.assertLessEqual(trump.cost, reachable, trump.name)


if __name__ == "__main__":
    unittest.main()
