"""1レーン攻城戦のシミュレータ。

`data/*.json` の数字だけで試合が回るようにしてある。ロジックに数値を
書かないので、バランス調整は JSON を触るだけで済む。

    python3 -m game.engine --a rush --b greed
"""

from .data import GameData, load
from .battle import Battle, Loadout, Result

__all__ = ["GameData", "load", "Battle", "Loadout", "Result"]
