#!/usr/bin/env python3
"""
BotW Wii U (v1.5.0 / v208) - Hardcore Survival Mod Builder
Outputs a ready-to-install Cemu Graphic Pack (compatible with Cemu, UKMM, and BCML).
Requires: pip install oead
"""

import argparse
import math
import random
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import oead

# ==============================================================================
# MOD CONFIGURATION (Adjust percentages and thresholds here)
# ==============================================================================
WEAPON_DROP_REDUCTION = 0.50       # Reduce enemy weapon drop probability by 50%
WEAPON_DURABILITY_REDUCTION = 0.40 # Reduce melee/bow/shield durability by 40%
WEAPON_MIN_DURABILITY = 3          # Minimum hit floor so weapons don't break in 1 hit

FOOD_CULL_RATE = 0.65              # Cull 65% of naturally spawning wild food & wildlife

ENEMY_CLONE_MIN_RATIO = 0.30       # Minimum +30% enemy density per eligible area
ENEMY_CLONE_MAX_RATIO = 0.50       # Maximum +50% enemy density per eligible area
CLONE_OFFSET_MIN_M = 1.8           # Minimum radial spawn offset (meters)
CLONE_OFFSET_MAX_M = 3.2           # Maximum radial spawn offset (meters)

COOK_HEARTS_REDUCTION = 0.40       # Reduce cooked meal heart recovery by 40%
COOK_DURATION_REDUCTION = 0.35     # Reduce cooked buff duration by 35%
COOK_MIN_DURATION_SEC = 10         # Floor for status buff durations (seconds)

ENEMY_DAMAGE_MULTIPLIER = 1.25     # Increase enemy attack power by +25%
ENEMY_MIN_DAMAGE_BONUS = 2         # Minimum +2 HP (+0.5 heart) for 0-base enemies

RANDOM_SEED = 208150               # Fixed seed for reproducible builds
# ==============================================================================

WEAPON_PREFIXES = (
    "Weapon_Sword_",
    "Weapon_Lsword_",
    "Weapon_Spear_",
    "Weapon_Bow_",
    "Weapon_Shield_",
)

EXCLUDED_WEAPONS = {
    "Weapon_Sword_502",  # One-Hit Obliterator (DLC)
    "Weapon_Bow_071",    # Bow of Light (Final Boss)
    "Weapon_Bow_072",    # Twilight Bow
}

WILD_FOOD_PREFIXES = (
    "Item_Fruit_",
    "Item_Mushroom_",
    "Item_Plant_",
    "Item_Fish_",
    "Animal_",
)

EXCLUDED_ENEMY_PREFIXES = (
    "Enemy_SiteBoss_",          # Blight Ganons
    "Enemy_Ganon",              # Calamity / Dark Beast Ganon
    "Enemy_Giant_",             # Hinox / Stalnox
    "Enemy_Sandworm_",          # Molduga
    "Enemy_Golem_",             # Stone Talus
    "Enemy_Lynel_",             # Lynels (avoid multi-Lynel arena clipping)
    "Enemy_Guardian_A_Fixed",   # Fixed Decayed Guardians
    "Enemy_Guardian_C",         # Skywatchers / Turrets
    "Enemy_Assasin_Boss",       # Master Kohga
    "Enemy_Assasin_Senior",     # Yiga Blademasters
    "Enemy_Dragon_",            # Dinraal, Naydra, Farosh
)


def is_great_plateau(translate: List[float]) -> bool:
    """Returns True if coordinates fall within the Great Plateau tutorial zone."""
    if not translate or len(translate) < 3:
        return False
    x, _, z = float(translate[0]), float(translate[1]), float(translate[2])
    return (-1650.0 <= x <= -350.0) and (1450.0 <= z <= 2350.0)


def read_maybe_yaz0(data: bytes) -> Tuple[bytes, bool]:
    """Decompresses Yaz0 data if compressed, returning (raw_bytes, was_compressed)."""
    if len(data) >= 4 and data[:4] == b"Yaz0":
        return bytes(oead.yaz0.decompress(data)), True
    return bytes(data), False


def write_maybe_yaz0(data: bytes, compress: bool) -> bytes:
    """Re-compresses data with Yaz0 if originally compressed."""
    if compress:
        return bytes(oead.yaz0.compress(data))
    return data


def safe_round_int(value: int, multiplier: float, minimum: int = 1) -> int:
    return max(minimum, int(round(value * multiplier)))


# ------------------------------------------------------------------------------
# AAMP Modifiers (.bdrop & .bgparamlist)
# ------------------------------------------------------------------------------
def patch_bdrop_bytes(raw_aamp: bytes) -> Tuple[bytes, bool]:
    """Reduces Weapon_* drop probabilities by WEAPON_DROP_REDUCTION in a .bdrop file."""
    pio = oead.aamp.ParameterIO.from_binary(raw_aamp)
    modified = False

    if "Header" not in pio.lists:
        return raw_aamp, False

    header_objs = list(pio.lists["Header"].objects.values())
    if not header_objs:
        return raw_aamp, False
    header = header_objs[0]

    table_num_param = header.params.get("TableNum")
    if table_num_param is None:
        return raw_aamp, False

    table_num = int(table_num_param.v)
    for t_idx in range(1, table_num + 1):
        t_key_param = header.params.get(f"Table{t_idx:02d}")
        if t_key_param is None:
            continue
        table_name = str(t_key_param.v)
        if table_name not in pio.lists:
            continue

        table_objs = list(pio.lists[table_name].objects.values())
        if not table_objs:
            continue
        t_obj = table_objs[0]

        col_num_param = t_obj.params.get("ColumnNum")
        if col_num_param is None:
            continue
        col_num = int(col_num_param.v)

        removed_prob = 0.0
        empty_slot_idx: Optional[int] = None

        for c_idx in range(1, col_num + 1):
            name_p = t_obj.params.get(f"ItemName{c_idx:02d}")
            prob_p = t_obj.params.get(f"ItemProbability{c_idx:02d}")
            if name_p is None or prob_p is None:
                continue

            item_name = str(name_p.v)
            prob = float(prob_p.v)

            if item_name == "":
                empty_slot_idx = c_idx
            elif item_name.startswith(WEAPON_PREFIXES) and prob > 0.0:
                new_prob = prob * (1.0 - WEAPON_DROP_REDUCTION)
                removed_prob += (prob - new_prob)
                prob_p.v = float(new_prob)
                modified = True

        # Re-allocate removed weapon probability to an empty (no-drop) slot
        if removed_prob > 0.0:
            if empty_slot_idx is not None:
                empty_prob_p = t_obj.params[f"ItemProbability{empty_slot_idx:02d}"]
                empty_prob_p.v = float(empty_prob_p.v) + removed_prob
            else:
                new_idx = col_num + 1
                col_num_param.v = new_idx
                t_obj.params[f"ItemName{new_idx:02d}"] = oead.aamp.Parameter("")
                t_obj.params[f"ItemProbability{new_idx:02d}"] = oead.aamp.Parameter(float(removed_prob))

    return (bytes(pio.to_binary()) if modified else raw_aamp), modified


def patch_bgparamlist_bytes(
    raw_aamp: bytes,
    actor_hint: str,
    processed_keys: Set[str],
    cache_key: str,
) -> Tuple[bytes, bool]:
    """Patches WeaponCommon.Life (durability) or Enemy/Attack Power in .bgparamlist."""
    if cache_key in processed_keys:
        return raw_aamp, False

    pio = oead.aamp.ParameterIO.from_binary(raw_aamp)
    modified = False

    # 1. Weapon Durability
    if actor_hint.startswith(WEAPON_PREFIXES) and actor_hint not in EXCLUDED_WEAPONS:
        if "WeaponCommon" in pio.lists:
            for obj in pio.lists["WeaponCommon"].objects.values():
                if "Life" in obj.params:
                    orig_life = int(obj.params["Life"].v)
                    if orig_life > 0:
                        new_life = safe_round_int(
                            orig_life,
                            1.0 - WEAPON_DURABILITY_REDUCTION,
                            WEAPON_MIN_DURABILITY,
                        )
                        if new_life != orig_life:
                            obj.params["Life"].v = new_life
                            modified = True

    # 2. Enemy Attack Power (do NOT modify WeaponCommon.AttackPower so player isn't buffed)
    if actor_hint.startswith("Enemy_") and not actor_hint.startswith("Enemy_Dragon_"):
        for list_name in ("Enemy", "Attack"):
            if list_name in pio.lists:
                for obj in pio.lists[list_name].objects.values():
                    for param_key in ("Power", "AttackPower"):
                        if param_key in obj.params:
                            orig_atk = int(obj.params[param_key].v)
                            if orig_atk >= 0:
                                scaled = int(round(orig_atk * ENEMY_DAMAGE_MULTIPLIER))
                                new_atk = max(scaled, orig_atk + ENEMY_MIN_DAMAGE_BONUS)
                                if new_atk != orig_atk:
                                    obj.params[param_key].v = new_atk
                                    modified = True

    if modified:
        processed_keys.add(cache_key)
        return bytes(pio.to_binary()), True
    return raw_aamp, False


# ------------------------------------------------------------------------------
# BYML Modifiers (ActorInfo.product.sbyml & CookData.sbyml)
# ------------------------------------------------------------------------------
def patch_actor_info(src_path: Path, dst_path: Path) -> Dict[str, int]:
    """Updates generalLife (weapons) and attackPower (enemies) in ActorInfo.product.sbyml."""
    raw, was_yaz0 = read_maybe_yaz0(src_path.read_bytes())
    doc = oead.byml.from_binary(raw)
    stats = {"weapons_nerfed": 0, "enemies_buffed": 0}

    for actor in doc["Actors"]:
        name = str(actor.get("name", ""))

        # Weapon durability
        if name.startswith(WEAPON_PREFIXES) and name not in EXCLUDED_WEAPONS:
            if "generalLife" in actor:
                orig_life = int(actor["generalLife"])
                if orig_life > 0:
                    new_life = safe_round_int(
                        orig_life,
                        1.0 - WEAPON_DURABILITY_REDUCTION,
                        WEAPON_MIN_DURABILITY,
                    )
                    actor["generalLife"] = oead.S32(new_life)
                    stats["weapons_nerfed"] += 1

        # Enemy base attack power
        elif name.startswith("Enemy_") and not name.startswith("Enemy_Dragon_"):
            if "attackPower" in actor:
                orig_atk = int(actor["attackPower"])
                if orig_atk >= 0:
                    scaled = int(round(orig_atk * ENEMY_DAMAGE_MULTIPLIER))
                    new_atk = max(scaled, orig_atk + ENEMY_MIN_DAMAGE_BONUS)
                    actor["attackPower"] = oead.S32(new_atk)
                    stats["enemies_buffed"] += 1

    out_byml = oead.byml.to_binary(doc, big_endian=True)
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    dst_path.write_bytes(write_maybe_yaz0(out_byml, was_yaz0))
    return stats


def patch_cook_data_bytes(raw_sbyml: bytes) -> bytes:
    """Weakens heart recovery and status buff durations in Cooking/CookData.sbyml."""
    raw, was_yaz0 = read_maybe_yaz0(raw_sbyml)
    doc = oead.byml.from_binary(raw)

    heart_mult = 1.0 - COOK_HEARTS_REDUCTION
    time_mult = 1.0 - COOK_DURATION_REDUCTION

    # 1. Global cooking multipliers
    if "System" in doc:
        sys_cfg = doc["System"]
        if "LifeRecoverRate" in sys_cfg:
            orig_rate = float(sys_cfg["LifeRecoverRate"])
            sys_cfg["LifeRecoverRate"] = oead.F32(orig_rate * heart_mult)
        if "SubLifeRecoverRate" in sys_cfg:
            orig_sub = float(sys_cfg["SubLifeRecoverRate"])
            sys_cfg["SubLifeRecoverRate"] = oead.F32(orig_sub * heart_mult)

    # 2. Fixed recipe heart recovery and duration overrides
    if "Recipes" in doc:
        for recipe in doc["Recipes"]:
            if "LifeRecover" in recipe and int(recipe["LifeRecover"]) > 0:
                recipe["LifeRecover"] = oead.S32(
                    safe_round_int(int(recipe["LifeRecover"]), heart_mult, 1)
                )
            if "EffectiveTime" in recipe and int(recipe["EffectiveTime"]) > 0:
                recipe["EffectiveTime"] = oead.S32(
                    safe_round_int(int(recipe["EffectiveTime"]), time_mult, COOK_MIN_DURATION_SEC)
                )

    # 3. Elixir & status effect base/max durations
    if "Effects" in doc:
        for eff in doc["Effects"]:
            for t_key in ("BaseTime", "MaxTime"):
                if t_key in eff and int(eff[t_key]) > 0:
                    eff[t_key] = oead.S32(
                        safe_round_int(int(eff[t_key]), time_mult, COOK_MIN_DURATION_SEC)
                    )

    out_byml = oead.byml.to_binary(doc, big_endian=True)
    return write_maybe_yaz0(out_byml, was_yaz0)


# ------------------------------------------------------------------------------
# SARC Archive Modifiers (.sbactorpack, TitleBG.pack, Bootup.pack)
# ------------------------------------------------------------------------------
def patch_sarc_archive(
    src_path: Path,
    dst_path: Path,
    processed_gparams: Set[str],
    patch_cook: bool = False,
) -> bool:
    """Patches .bdrop, .bgparamlist, and optionally CookData.sbyml inside a SARC."""
    raw_sarc, was_yaz0 = read_maybe_yaz0(src_path.read_bytes())
    sarc = oead.Sarc(raw_sarc)
    writer = oead.SarcWriter.from_sarc(sarc)
    any_modified = False

    for f in sarc.get_files():
        fname = f.name
        fdata = bytes(f.data)

        if fname.startswith("DropTable/") and fname.endswith(".bdrop"):
            new_data, mod = patch_bdrop_bytes(fdata)
            if mod:
                writer.files[fname] = new_data
                any_modified = True

        elif fname.startswith("GeneralParamList/") and fname.endswith(".bgparamlist"):
            actor_hint = Path(fname).stem
            new_data, mod = patch_bgparamlist_bytes(
                fdata,
                actor_hint=actor_hint,
                processed_keys=processed_gparams,
                cache_key=fname,
            )
            if mod:
                writer.files[fname] = new_data
                any_modified = True

        elif patch_cook and fname == "Cooking/CookData.sbyml":
            writer.files[fname] = patch_cook_data_bytes(fdata)
            any_modified = True

    if any_modified:
        _, out_sarc = writer.write()
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        dst_path.write_bytes(write_maybe_yaz0(out_sarc, was_yaz0))
    return any_modified


# ------------------------------------------------------------------------------
# Map Unit Modifiers (.smubin - Food Culling & Enemy Cloning)
# ------------------------------------------------------------------------------
def collect_used_hashes_and_refs(docs: List[Any]) -> Tuple[Set[int], Set[int], Set[int]]:
    """Collects all existing HashIds, all link targets, and Event/Demo targets."""
    used_hashes: Set[int] = set()
    referenced_hashes: Set[int] = set()
    event_linked_hashes: Set[int] = set()

    for doc in docs:
        if not doc:
            continue
        for obj in doc.get("Objs", []):
            if "HashId" in obj:
                used_hashes.add(int(obj["HashId"]))
            unit_name = str(obj.get("UnitConfigName", ""))
            is_event_actor = (
                "EventTag" in unit_name
                or "Demo" in unit_name
                or "LinkTag" in unit_name
            )
            for link in obj.get("LinksToObj", []):
                dest = int(link.get("DestUnitHashId", 0))
                if dest:
                    referenced_hashes.add(dest)
                    if is_event_actor:
                        event_linked_hashes.add(dest)

        for rail in doc.get("Rails", []):
            if "HashId" in rail:
                used_hashes.add(int(rail["HashId"]))
            for pt in rail.get("RailPoints", []):
                if "HashId" in pt:
                    used_hashes.add(int(pt["HashId"]))

    return used_hashes, referenced_hashes, event_linked_hashes


def generate_unique_hash(used_hashes: Set[int], rng: random.Random) -> int:
    while True:
        candidate = rng.randint(0x10000000, 0xFFFFFFFE)
        if candidate not in used_hashes:
            used_hashes.add(candidate)
            return candidate


def clone_enemy_object(
    src_obj: Dict[str, Any],
    used_hashes: Set[int],
    rng: random.Random,
    is_dungeon: bool,
) -> Dict[str, Any]:
    """Deep-copies an enemy BYML dict with a fresh HashId, safe offset, and clean links."""
    # Round-trip small dict via BYML to guarantee clean oead value types
    clone = oead.byml.from_binary(oead.byml.to_binary(src_obj, big_endian=True))

    new_hash = generate_unique_hash(used_hashes, rng)
    clone["HashId"] = oead.U32(new_hash)

    # Radial XZ offset so the clone doesn't clip into the original enemy
    if "Translate" in clone and len(clone["Translate"]) >= 3:
        angle = rng.uniform(0.0, 2.0 * math.pi)
        dist = rng.uniform(CLONE_OFFSET_MIN_M, CLONE_OFFSET_MAX_M)
        tx, ty, tz = (
            float(clone["Translate"][0]),
            float(clone["Translate"][1]),
            float(clone["Translate"][2]),
        )
        clone["Translate"] = [
            oead.F32(tx + math.cos(angle) * dist),
            oead.F32(ty + 0.15),
            oead.F32(tz + math.sin(angle) * dist),
        ]

    # Strip LinksToObj on clones so shrine/dungeon LinkTagAnd room-clear counters
    # and camp trigger chains don't soft-lock expecting an exact enemy count.
    if "LinksToObj" in clone:
        if is_dungeon:
            del clone["LinksToObj"]
        else:
            # Keep only non-logic camp/territory links (e.g. BattleArea / Reference)
            safe_links = [
                lnk for lnk in clone["LinksToObj"]
                if str(lnk.get("DefinitionName", "")) in ("Reference", "Area")
            ]
            if safe_links:
                clone["LinksToObj"] = safe_links
            else:
                del clone["LinksToObj"]

    return clone


def transform_smubin_pair(
    static_bytes: Optional[bytes],
    dynamic_bytes: Optional[bytes],
    rng: random.Random,
    cull_food: bool,
    is_dungeon: bool,
) -> Tuple[Optional[bytes], Optional[bytes], Dict[str, int]]:
    """Processes a map unit's Static + Dynamic .smubin pair together."""
    stats = {"food_culled": 0, "enemies_cloned": 0}
    docs: List[Optional[Any]] = [None, None]
    yaz0_flags = [True, True]

    for idx, raw_in in enumerate((static_bytes, dynamic_bytes)):
        if raw_in is not None:
            raw, was_yaz0 = read_maybe_yaz0(raw_in)
            docs[idx] = oead.byml.from_binary(raw)
            yaz0_flags[idx] = was_yaz0

    used_hashes, referenced_hashes, event_linked_hashes = collect_used_hashes_and_refs(docs)
    modified = [False, False]

    for idx, doc in enumerate(docs):
        if doc is None or "Objs" not in doc:
            continue

        new_objs = []
        eligible_enemies: List[Dict[str, Any]] = []

        for obj in doc["Objs"]:
            unit_name = str(obj.get("UnitConfigName", ""))
            obj_hash = int(obj.get("HashId", 0))
            translate = [float(v) for v in obj.get("Translate", [0.0, 0.0, 0.0])]
            params = obj.get("!Parameters", {})

            # --- Mechanic 3: Scarcer Wild Food & Ingredients ---
            if cull_food and unit_name.startswith(WILD_FOOD_PREFIXES):
                has_outgoing_links = bool(obj.get("LinksToObj"))
                is_referenced = obj_hash in referenced_hashes
                is_quest = bool(params.get("IsQuestItem", False))

                if (
                    not has_outgoing_links
                    and not is_referenced
                    and not is_quest
                    and not is_great_plateau(translate)
                ):
                    if rng.random() < FOOD_CULL_RATE:
                        stats["food_culled"] += 1
                        modified[idx] = True
                        continue  # Cull this food/wildlife spawn

            new_objs.append(obj)

            # --- Mechanic 4: Collect Eligible Enemies for Cloning ---
            if unit_name.startswith("Enemy_") and not unit_name.startswith(EXCLUDED_ENEMY_PREFIXES):
                if (
                    obj_hash not in event_linked_hashes
                    and not is_great_plateau(translate)
                ):
                    eligible_enemies.append(obj)

        # Duplicate 30-50% of eligible enemies in this map unit
        if eligible_enemies:
            ratio = rng.uniform(ENEMY_CLONE_MIN_RATIO, ENEMY_CLONE_MAX_RATIO)
            clone_count = max(1, int(round(len(eligible_enemies) * ratio)))
            chosen = rng.sample(eligible_enemies, min(clone_count, len(eligible_enemies)))
            for target_enemy in chosen:
                cloned = clone_enemy_object(target_enemy, used_hashes, rng, is_dungeon=is_dungeon)
                new_objs.append(cloned)
                stats["enemies_cloned"] += 1
                modified[idx] = True

        if modified[idx]:
            doc["Objs"] = new_objs

    out_bytes: List[Optional[bytes]] = [None, None]
    for idx in (0, 1):
        if modified[idx] and docs[idx] is not None:
            raw_out = oead.byml.to_binary(docs[idx], big_endian=True)
            out_bytes[idx] = write_maybe_yaz0(raw_out, yaz0_flags[idx])

    return out_bytes[0], out_bytes[1], stats


def process_map_tree(
    src_root: Path,
    dst_root: Path,
    rng: random.Random,
    totals: Dict[str, int],
) -> None:
    """Processes Overworld (Map/MainField), Shrines (Dungeon*.pack), and Divine Beasts."""
    # 1. Overworld: Map/MainField/<Section>/<Section>_{Static,Dynamic}.smubin
    mainfield_dir = src_root / "Map" / "MainField"
    if mainfield_dir.exists():
        sections = sorted({p.parent for p in mainfield_dir.rglob("*.smubin")})
        for sec_dir in sections:
            sec_name = sec_dir.name
            static_p = sec_dir / f"{sec_name}_Static.smubin"
            dynamic_p = sec_dir / f"{sec_name}_Dynamic.smubin"

            s_bytes = static_p.read_bytes() if static_p.exists() else None
            d_bytes = dynamic_p.read_bytes() if dynamic_p.exists() else None
            if s_bytes is None and d_bytes is None:
                continue

            out_s, out_d, st = transform_smubin_pair(
                s_bytes, d_bytes, rng, cull_food=True, is_dungeon=False
            )
            totals["food_culled"] += st["food_culled"]
            totals["enemies_cloned"] += st["enemies_cloned"]

            rel_dir = sec_dir.relative_to(src_root)
            if out_s is not None:
                p = dst_root / rel_dir / static_p.name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(out_s)
            if out_d is not None:
                p = dst_root / rel_dir / dynamic_p.name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(out_d)

    # 2. Shrines & Divine Beasts packed inside Pack/Dungeon*.pack & Pack/Remains*.pack
    pack_dir = src_root / "Pack"
    if pack_dir.exists():
        dungeon_packs = sorted(
            list(pack_dir.glob("Dungeon*.pack"))
            + list(pack_dir.glob("Remains*.pack"))
            + list(pack_dir.glob("FinalTrial.pack"))
        )
        for p_path in dungeon_packs:
            raw_sarc, was_yaz0 = read_maybe_yaz0(p_path.read_bytes())
            sarc = oead.Sarc(raw_sarc)
            writer = oead.SarcWriter.from_sarc(sarc)

            static_name = next((f.name for f in sarc.get_files() if f.name.endswith("_Static.smubin")), None)
            dynamic_name = next((f.name for f in sarc.get_files() if f.name.endswith("_Dynamic.smubin")), None)

            s_bytes = bytes(sarc.get_file(static_name).data) if static_name else None
            d_bytes = bytes(sarc.get_file(dynamic_name).data) if dynamic_name else None

            out_s, out_d, st = transform_smubin_pair(
                s_bytes, d_bytes, rng, cull_food=False, is_dungeon=True
            )
            totals["enemies_cloned"] += st["enemies_cloned"]

            if out_s is not None or out_d is not None:
                if out_s is not None and static_name:
                    writer.files[static_name] = out_s
                if out_d is not None and dynamic_name:
                    writer.files[dynamic_name] = out_d
                _, new_sarc = writer.write()
                out_pack = dst_root / "Pack" / p_path.name
                out_pack.parent.mkdir(parents=True, exist_ok=True)
                out_pack.write_bytes(write_maybe_yaz0(new_sarc, was_yaz0))


# ------------------------------------------------------------------------------
# Graphic Pack Scaffolding & Build Entrypoint
# ------------------------------------------------------------------------------
def write_rules_txt(output_dir: Path) -> None:
    rules = f"""[Definition]
titleIds = 00050000101C9300,00050000101C9400,00050000101C9500
name = Hardcore Survival Overhaul
path = "The Legend of Zelda: Breath of the Wild/Mods/Hardcore Survival"
description = Weapons drop {int(WEAPON_DROP_REDUCTION*100)}% less and break {int(WEAPON_DURABILITY_REDUCTION*100)}% faster, wild food is {int(FOOD_CULL_RATE*100)}% scarcer, enemy density is +{int(ENEMY_CLONE_MIN_RATIO*100)}-{int(ENEMY_CLONE_MAX_RATIO*100)}%, cooked dishes heal {int(COOK_HEARTS_REDUCTION*100)}% less, and enemies deal +{int((ENEMY_DAMAGE_MULTIPLIER-1)*100)}% damage.
version = 7
"""
    (output_dir / "rules.txt").write_text(rules, encoding="utf-8")


def build_mod(content_dir: Path, aoc_dir: Optional[Path], output_dir: Path) -> None:
    actor_info_src = content_dir / "Actor" / "ActorInfo.product.sbyml"
    if not actor_info_src.exists():
        raise FileNotFoundError(
            f"Could not find {actor_info_src}. Ensure --content points to a merged "
            "Wii U v1.5.0 (v208) content directory."
        )

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    out_content = output_dir / "content"
    rng = random.Random(RANDOM_SEED)
    processed_gparams: Set[str] = set()
    totals = {"food_culled": 0, "enemies_cloned": 0, "actor_packs_patched": 0}

    print("[1/5] Generating Cemu Graphic Pack rules.txt...")
    write_rules_txt(output_dir)

    print("[2/5] Patching ActorInfo.product.sbyml (weapon durability & enemy attack)...")
    ai_stats = patch_actor_info(
        actor_info_src,
        out_content / "Actor" / "ActorInfo.product.sbyml",
    )

    print("[3/5] Patching Bootup.pack (CookData.sbyml) & TitleBG.pack...")
    bootup_src = content_dir / "Pack" / "Bootup.pack"
    if bootup_src.exists():
        patch_sarc_archive(
            bootup_src,
            out_content / "Pack" / "Bootup.pack",
            processed_gparams,
            patch_cook=True,
        )

    titlebg_src = content_dir / "Pack" / "TitleBG.pack"
    if titlebg_src.exists():
        patch_sarc_archive(
            titlebg_src,
            out_content / "Pack" / "TitleBG.pack",
            processed_gparams,
            patch_cook=False,
        )

    print("[4/5] Patching Enemy_*.sbactorpack & Weapon_*.sbactorpack archives...")
    actor_pack_dir = content_dir / "Actor" / "Pack"
    if actor_pack_dir.exists():
        for pack_file in sorted(actor_pack_dir.glob("*.sbactorpack")):
            if pack_file.name.startswith(("Enemy_",) + WEAPON_PREFIXES):
                if patch_sarc_archive(
                    pack_file,
                    out_content / "Actor" / "Pack" / pack_file.name,
                    processed_gparams,
                    patch_cook=False,
                ):
                    totals["actor_packs_patched"] += 1

    print("[5/5] Modifying Overworld, Shrine, and Divine Beast map units (.smubin)...")
    process_map_tree(content_dir, out_content, rng, totals)

    if aoc_dir is not None and aoc_dir.exists():
        # Support either passing `aoc/` or `aoc/0010/`
        aoc_root = (aoc_dir / "0010") if (aoc_dir / "0010").exists() else aoc_dir
        out_aoc = output_dir / "aoc" / "0010" if (aoc_dir / "0010").exists() else (output_dir / "aoc")
        print(f"[DLC] Processing AOC map units in {aoc_root}...")
        process_map_tree(aoc_root, out_aoc, rng, totals)

    print("\n=== Hardcore Survival Build Complete ===")
    print(f"Output Graphic Pack : {output_dir.resolve()}")
    print(f"Weapons Nerfed      : {ai_stats['weapons_nerfed']} entries")
    print(f"Enemies Buffed      : {ai_stats['enemies_buffed']} entries")
    print(f"Actor Packs Patched : {totals['actor_packs_patched']} .sbactorpack files")
    print(f"Wild Food Culled    : {totals['food_culled']} spawns removed")
    print(f"Enemies Cloned      : {totals['enemies_cloned']} ambush reinforcements added")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build BotW Wii U Hardcore Survival Mod")
    parser.add_argument("--content", required=True, type=Path, help="Path to merged v1.5.0 Wii U content/ folder")
    parser.add_argument("--aoc", required=False, type=Path, help="Optional path to DLC aoc/ folder")
    parser.add_argument("--output", default=Path("./HardcoreSurvival"), type=Path, help="Output Graphic Pack folder")
    args = parser.parse_args()

    build_mod(args.content, args.aoc, args.output)
