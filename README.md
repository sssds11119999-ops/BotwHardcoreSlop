# BotW Hardcore Survival (Wii U v1.5.0 / Cemu)

A hardcore survival overhaul for *The Legend of Zelda: Breath of the Wild* (Wii U v1.5.0 / v208), designed for **Cemu**, **UKMM**, and **BCML**.

## Gameplay Changes
* **Reduced Weapon Drops (-50%):** Enemy drop tables are reweighted so weapons drop half as often, forcing reliance on scavenging and improvised gear.
* **Lower Weapon Durability (-40%):** Melee weapons, bows, and shields break 40% faster (with a minimum 3-hit floor so weapons never shatter on the first swing).
* **Scarcer Wild Food (-65%):** Naturally spawning fruits, mushrooms, plants, fish, and wildlife are culled by 65% across Hyrule while preserving quest-critical and Great Plateau tutorial spawns.
* **Higher Enemy Density (+30% to +50%):** Non-boss enemy encounters in the Overworld, Shrines, and Divine Beasts spawn additional reinforcements without breaking room-clear gates or EventFlow triggers.
* **Weakened Cooked Dishes (-40% Healing / -35% Buff Duration):** Cooked meals restore 40% fewer hearts, and meal/elixir status effects last 35% shorter.
* **Higher Enemy Damage (+25%):** Enemy base attack power is increased by 25% without enabling vanilla Master Mode's health regeneration or universal tier-ups.

## Installation (Players)
1. Download the latest `.zip` archive from the **[Releases](../../releases)** tab.
2. **For Cemu:** Extract the `BotW_HardcoreSurvival` folder into your Cemu `graphicPacks/` directory, then open **Options → Graphic packs → The Legend of Zelda: Breath of the Wild → Mods** and enable **Hardcore Survival Overhaul**.
3. **For UKMM / BCML:** Import the downloaded `.zip` or extracted Graphic Pack folder directly into UKMM or BCML to merge it with other gameplay mods.

## Building from Source (Custom Difficulty)
If you want to customize the difficulty percentages, edit the configuration variables at the top of `build_hardcore_survival.py` and run the builder against a merged Wii U v1.5.0 (`v208`) dump:

```bash
python -m venv .venv
source .venv/bin/activate
pip install oead

python build_hardcore_survival.py \
  --content "/path/to/merged_v1.5.0/content" \
  --aoc "/path/to/dlc/aoc" \
  --output "./BotW_HardcoreSurvival"
