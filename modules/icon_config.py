# -*- coding: utf-8 -*-
"""
Icon Configuration Module

Maps unit/building names to icon filenames.
Provides icon loading and tinting functions.
"""

import os
import numpy as np
from PIL import Image

# Import from config
from config import TEAM_COLORS
import config  # For dynamic ICON_DIR access

# Asset pack support (obfuscated .pak file)
try:
    from asset_loader import get_asset_pack, init_asset_pack
    _HAS_ASSET_LOADER = True
except ImportError:
    _HAS_ASSET_LOADER = False

# Icon caches
_icon_base_cache = {}
_icon_tinted_cache = {}
MISSING_ICON_TYPES = set()
_icons_preloaded = False


def preload_all_icons(icon_dir=None):
    """
    Preload ALL icons into RAM at startup.
    Tries asset pack first, falls back to raw files from icon_dir.
    Call this after setting config.ICON_DIR.
    
    Returns:
        int: Number of icons loaded
    """
    global _icons_preloaded
    
    # Get unique icon filenames from ICON_MAP
    unique_files = set(ICON_MAP.values())
    
    # Also add team logos and other special icons
    special_icons = [
        "512x512_Sol_Logo-01.png",
        "Centauri_512x512-01-01.png",
        "512x512_alien_logo.png",
        "Silica_Logo.png",
    ]
    
    all_files = unique_files | set(special_icons)
    loaded = 0
    failed = 0
    
    # --- Try asset pack first ---
    if _HAS_ASSET_LOADER:
        try:
            pack = get_asset_pack()
            for filename in all_files:
                rel_path = f"Silica_Icons/{filename}"
                if pack.has_asset(rel_path):
                    try:
                        img = pack.load_image(rel_path)
                        _icon_base_cache[f"__file__{filename}"] = img
                        loaded += 1
                    except Exception as e:
                        print(f"[ICON PRELOAD] Failed to load {filename} from pack: {e}")
                        failed += 1
            
            if loaded > 0:
                _icons_preloaded = True
                print(f"[ICON PRELOAD] Loaded {loaded} icons from asset pack ({failed} failed)")
                return loaded
        except RuntimeError:
            # Asset pack not initialized - fall through to file-based loading
            pass
    
    # --- Fallback: load from raw files ---
    if icon_dir is None:
        icon_dir = config.ICON_DIR
    
    if not icon_dir or not os.path.isdir(icon_dir):
        print(f"[ICON PRELOAD] Warning: ICON_DIR not set or invalid: {icon_dir}")
        return 0
    
    for filename in all_files:
        path = os.path.join(icon_dir, filename)
        if os.path.isfile(path):
            try:
                img = Image.open(path).convert("RGBA")
                _icon_base_cache[f"__file__{filename}"] = img
                loaded += 1
            except Exception as e:
                print(f"[ICON PRELOAD] Failed to load {filename}: {e}")
                failed += 1
    
    _icons_preloaded = True
    print(f"[ICON PRELOAD] Loaded {loaded} icons from files ({failed} failed)")
    
    return loaded


def get_preloaded_icon(filename):
    """Get a preloaded icon by filename."""
    return _icon_base_cache.get(f"__file__{filename}")

ICON_MAP = {
    # HUMAN / SOL / CENTAURI STRUCTURES
    "Refinery": "Tac_Structure_Refinery.png",
    "Barracks": "Tac_Structure_Barracks.png",
    "ResearchFacility": "Tac_Structure_ResearchFacility.png",
    "LightFactory": "Tac_Structure_LightVehicleFactory.png",
    "HeavyFactory": "Tac_Structure_HeavyVehicleFactory.png",
    "UltraHeavyFactory": "Tac_Structure_UltraHeavyVehicleFactory.png",
    "AirFactory": "Tac_Structure_AirFactory.png",
    "Headquarters": "Tac_Structure_Headquarters.png",
    "RadarStation": "Tac_Structure_RadarStation.png",
    "Bunker": "Tac_Structure_Bunker.png",
    "Outpost": "Tac_Structure_Outpost.png",
    "Silo": "Tac_Structure_Silo.png",
    "Turret": "Tac_Structure_Turret.png",
    "HeavyTurret": "Tac_Structure_Turret.png",
    "AntiAirRocketTurret": "Tac_Structure_Turret.png",

    # ALIEN STRUCTURES
    "BioCache": "Tac_AlienStructure_BioCache.png",
    "LesserSpawningCyst": "Tac_AlienStructure_LesserSpawningCyst.png",
    "GreaterSpawningCyst": "Tac_AlienStructure_GreaterSpawningCyst.png",
    "GrandSpawningCyst": "Tac_AlienStructure_GrandSpawningCyst.png",
    "ColossalSpawningCyst": "Tac_AlienStructure_ColossalSpawningCyst.png",
    "ThornSpire": "Tac_AlienStructure_ThornSpire.png",
    "HiveSpire": "Tac_AlienStructure_HiveSpire.png",
    "Nest": "Tac_AlienStructure_Nest.png",
    "Node": "Tac_AlienStructure_Node.png",
    "QuantumCortex": "Tac_AlienStructure_QuantumCortex.png",

    # SOLDIERS
    "Commando": "Tac_Soldier_Commando.png",
    "Heavy": "Tac_Soldier_Heavy.png",
    "Marksman": "Tac_Soldier_Marksman.png",
    "Rifleman": "Tac_Soldier_Rifleman.png",
    "Scout": "Tac_Soldier_Scout.png",
    "Trooper": "Tac_Soldier_Rifleman.png",  # Trooper uses Rifleman icon
    "Militia": "Tac_Soldier_Rifleman.png",  # Militia uses Rifleman icon
    "Templar": "Tac_Soldier_Commando.png",  # Templar uses Heavy icon
    "Juggernaut": "Tac_Soldier_Heavy.png",  # Juggernaut uses Heavy icon
    "Sniper": "Tac_Soldier_Marksman.png",  # Sniper uses Marksman icon

    # CREATURES
    "Behemoth": "Tac_Creature_Behemoth.png",
    "Colossus": "Tac_Creature_Colossus.png",
    "Crab": "Tac_Creature_Crab.png",
    "CrabHorned": "Tac_Creature_CrabHorned.png",
    "Defiler": "Tac_Creature_Defiler.png",
    "Dragonfly": "Tac_Creature_Dragonfly.png",
    "Firebug": "Tac_Creature_Firebug.png",
    "Goliath": "Tac_Creature_Goliath.png",
    "Hunter": "Tac_Creature_Hunter.png",
    "Queen": "Tac_Creature_Queen.png",
    "Scorpion": "Tac_Creature_Scorpion.png",
    "Shocker": "Tac_Creature_Shocker.png",
    "Shrimp": "Tac_Creature_Shrimp.png",
    "Squid": "Tac_Creature_Squid.png",
    "Wasp": "Tac_Creature_Wasp.png",
    "Worm": "Tac_Creature_Worm.png",
    "GreatWorm": "Tac_Creature_Worm.png",  # Alias

    # VEHICLES
    "AntiAirCar": "Tac_Vehicle_AntiAirCar.png",
    "ArmedTransport": "Tac_Vehicle_ArmedTransport.png",
    "BarrageTruck": "Tac_Vehicle_BarrageTruck.png",
    "CombatTank": "Tac_Vehicle_CombatTank.png",
    "CrimsonTank": "Tac_Vehicle_CrimsonTank.png",
    "FlakTruck": "Tac_Vehicle_FlakTruck.png",
    "Harvester": "Tac_Vehicle_Harvester.png",
    "HeavyArmoredCar": "Tac_Vehicle_HeavyArmoredCar.png",
    "HeavyQuad": "Tac_Vehicle_HeavyQuad.png",
    "HeavyQuad2": "Tac_Vehicle_HeavyQuad2.png",
    "HeavyTank": "Tac_Vehicle_HeavyTank.png",
    "HoverBike": "Tac_Vehicle_HoverBike.png",
    "HoverHarvester": "Tac_Vehicle_HoverHarvester.png",
    "HoverTank": "Tac_Vehicle_HoverTank.png",
    "LightArmoredCar": "Tac_Vehicle_LightArmoredCar.png",
    "LightArmoredCar2": "Tac_Vehicle_LightArmoredCar2.png",
    "LightQuad": "Tac_Vehicle_LightQuad.png",
    "LightQuad2": "Tac_Vehicle_LightQuad2.png",
    "PulseTruck": "Tac_Vehicle_PulseTruck.png",
    "PyroTank": "Tac_Vehicle_PyroTank.png",
    "RailgunTank": "Tac_Vehicle_RailgunTank.png",
    "RetroHatchback": "Tac_Vehicle_RetroHatchback.png",
    "RocketTank": "Tac_Vehicle_RocketTank.png",
    "SiegeTank": "Tac_Vehicle_SiegeTank.png",
    "StrikeTank": "Tac_Vehicle_StrikeTank.png",
    "TroopHauler": "Tac_Vehicle_TroopHauler.png",
    "TroopTransport": "Tac_Vehicle_TroopTransport.png",
    "AssaultCar": "Tac_Vehicle_LightArmoredCar.png",  # Alias
    "FlakCar": "Tac_Vehicle_FlakTruck.png",  # Alias
    "HeavyRaider": "Tac_Vehicle_HeavyArmoredCar.png",  # Alias
    "LightRaider": "Tac_Vehicle_LightArmoredCar.png",  # Alias
    "HeavyHarvester": "Tac_Vehicle_Harvester.png",  # Alias
    "PlatoonHauler": "Tac_Vehicle_TroopTransport.png",  # Sol_Light_PlatoonHauler
    "AATruck": "Tac_Vehicle_FlakTruck.png",  # Sol_Light_AATruck
    "HeavyStriker": "Tac_Vehicle_HeavyArmoredCar.png",  # Sol_Light_HeavyStriker
    "LightStriker": "Tac_Vehicle_LightArmoredCar2.png",  # Sol_Light_LightStriker

    # AIR VEHICLES
    "Bomber": "Tac_AirVehicle_Bomber.png",
    "CrimsonFreighter": "Tac_AirVehicle_CrimsonFreighter.png",
    "Freighter": "Tac_AirVehicle_CrimsonFreighter.png",
    "Dreadnought": "Tac_AirVehicle_Dreadnought.png",
    "Dropship": "Tac_AirVehicle_Dropship.png",
    "Fighter": "Tac_AirVehicle_Fighter.png",
    "Gunship": "Tac_AirVehicle_Gunship.png",
    "Interceptor": "Tac_AirVehicle_Interceptor.png",
    "Shuttle": "Tac_AirVehicle_Shuttle.png",

    # OTHER
    "Resource_BalteriumField": "Tac_Resource_BalteriumField.png",
    "Resource_Organics": "Tac_Resource_Organics.png",
    "DropPod": "Tac_DropPod.png",
    "CampSite": "Tac_CampSite.png",
    "Skull": "Tac_Skull.png",
}


def normalize_unit_name(raw_name: str) -> str:
    """
    Normalize unit names to match ICON_MAP keys.
    
    Examples:
        Cent_Soldier_Trooper -> Trooper
        Sol_Air_Gunship -> Gunship
        Alien_Creature_Hunter -> Hunter
        Sol_Light_LightQuad -> LightQuad
        GreatWorm -> Worm
    """
    name = raw_name.strip()
    
    # Remove faction prefix (Sol_, Cent_, Centauri_, Alien_)
    for prefix in ["Sol_", "Cent_", "Centauri_", "Alien_"]:
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    
    # Remove category prefixes (Soldier_, Vehicle_, Creature_, Air_, etc.)
    categories = ["Soldier_", "Vehicle_", "Creature_", "Air_", "Light_", "Heavy_", "UltraHeavy_"]
    for cat in categories:
        if name.startswith(cat):
            name = name[len(cat):]
            break
    
    # Handle special cases
    if name == "GreatWorm":
        return "Worm"
    if name == "Crab_Horned":
        return "CrabHorned"
    
    # All human turret variants -> "Turret"
    if "Turret" in name and name not in ["HiveSpire", "ThornSpire"]:
        return "Turret"
    
    return name




def is_soldier(unit_name: str) -> bool:
    """Check if a unit is a soldier type."""
    normalized = normalize_unit_name(unit_name)
    soldier_types = {
        "Commando", "Heavy", "Marksman", "Rifleman", "Scout",
        "Trooper", "Militia", "Templar", "Juggernaut", "Sniper"
    }
    return normalized in soldier_types


def is_greatworm(unit_name: str) -> bool:
    """
    Check if a unit is a Greatworm (wildlife faction).
    
    Greatworms are neutral wildlife that can kill players but belong to no team.
    """
    if not unit_name:
        return False
    
    name_lower = unit_name.lower()
    normalized = normalize_unit_name(unit_name)
    
    # Check for Greatworm/Worm variations
    return (
        normalized in {"Worm", "GreatWorm"} or
        "greatworm" in name_lower or
        name_lower == "worm"
    )


def is_ai_unit(player_name):
    """
    Check if a player name is an AI unit (not a real player).
    
    AI units include:
    - Faction-prefixed units: Sol_*, Cent_*, Centauri_*, Alien_*
    - Category-prefixed units: Soldier_*, Light_*, Heavy_*, etc.
    - Structures: *Refinery, *Factory, *Headquarters, etc.
    - Alien creatures: Shrimp, Crab, Hunter, etc.
    - Vehicles and soldiers (when used as attacker name)
    - Special names: Unknown, World, Environment
    
    Real players have Steam IDs in the log, AI units don't.
    Real player example: "Lycan<2539076><76561198041683943><Sol>"
    AI unit example: "Cent_Soldier_Trooper<><><Centauri>"
    """
    if not player_name:
        return True
    
    # Special AI names
    if player_name in {"Unknown", "World", "Environment", ""}:
        return True
    
    # Faction prefixes indicate AI units
    faction_prefixes = ["Sol_", "Cent_", "Centauri_", "Alien_"]
    for prefix in faction_prefixes:
        if player_name.startswith(prefix):
            return True
    
    # Category prefixes also indicate AI units
    category_prefixes = ["Soldier_", "Light_", "Heavy_", "UltraHeavy_", "Air_", "Vehicle_", "Creature_"]
    for prefix in category_prefixes:
        if player_name.startswith(prefix):
            return True
    
    # Structure and building indicators (case-insensitive)
    structure_keywords = [
        "refinery", "factory", "headquarters", "nest", "barracks",
        "turret", "spire", "node", "bunker", "outpost", "silo",
        "cyst", "biocache", "cortex", "radarstation", "researchfacility"
    ]
    
    name_lower = player_name.lower()
    for keyword in structure_keywords:
        if keyword in name_lower:
            return True
    
    # Alien creatures (substring match, case-insensitive)
    creature_names = [
        "shrimp", "crab", "hunter", "wasp", "dragonfly",
        "scorpion", "goliath", "behemoth", "colossus", "firebug",
        "shocker", "defiler", "squid", "worm", "queen"
    ]
    
    for creature in creature_names:
        if creature in name_lower:
            return True
    
    # Vehicle types (substring match)
    vehicle_keywords = [
        "harvester", "tank", "truck", "car", "quad", "transport",
        "bomber", "fighter", "gunship", "dropship", "shuttle",
        "freighter", "dreadnought", "interceptor", "hoverbike",
        "hauler", "striker", "raider"
    ]
    
    for vehicle in vehicle_keywords:
        if vehicle in name_lower:
            return True
    
    # Soldier types (exact match or as part of name)
    soldier_names = [
        "rifleman", "heavy", "marksman", "scout", "commando",
        "trooper", "militia", "templar", "juggernaut", "sniper"
    ]
    
    for soldier in soldier_names:
        if soldier in name_lower:
            return True
    
    # Check if normalized name exists in ICON_MAP (strong indicator of AI unit)
    normalized = normalize_unit_name(player_name)
    if normalized in ICON_MAP:
        return True
    
    return False




def load_base_icon(unit_name: str):
    """Load icon for unit_name (unscaled, original color) from cache, asset pack, or ICON_DIR."""
    if unit_name in _icon_base_cache:
        return _icon_base_cache[unit_name]

    # Normalize the unit name
    normalized = normalize_unit_name(unit_name)
    
    filename = ICON_MAP.get(normalized)
    if not filename:
        if normalized not in MISSING_ICON_TYPES:
            MISSING_ICON_TYPES.add(normalized)
            print(f"[ICON WARN] No ICON_MAP entry for normalized name '{normalized}' (from '{unit_name}')")
        _icon_base_cache[unit_name] = None
        return None

    # Try to get from preloaded cache first (by filename)
    preloaded = get_preloaded_icon(filename)
    if preloaded is not None:
        img = preloaded.copy()
        _icon_base_cache[unit_name] = img
        return img

    # Try asset pack
    if _HAS_ASSET_LOADER:
        try:
            pack = get_asset_pack()
            rel_path = f"Silica_Icons/{filename}"
            if pack.has_asset(rel_path):
                img = pack.load_image(rel_path)
                _icon_base_cache[unit_name] = img
                return img
        except RuntimeError:
            pass

    # Fallback: load from disk (if not preloaded and no asset pack)
    icon_dir = config.ICON_DIR
    path = os.path.join(icon_dir, filename)
    if not os.path.isfile(path):
        if normalized not in MISSING_ICON_TYPES:
            MISSING_ICON_TYPES.add(normalized)
            print(f"[ICON WARN] Icon file missing: {path}")
        _icon_base_cache[unit_name] = None
        return None

    img = Image.open(path).convert("RGBA")
    _icon_base_cache[unit_name] = img
    return img




def tint_icon(base_icon, team, status):
    """
    Tint only the white-ish parts of the icon with team color.
    
    status:
      'construction' -> lighter team color
      'complete'     -> full team color
      'flash'        -> white
    """
    if team not in TEAM_COLORS and status != "flash":
        return base_icon
    
    arr = np.array(base_icon)
    r = arr[..., 0]
    g = arr[..., 1]
    b = arr[..., 2]
    a = arr[..., 3]
    
    if status == "flash":
        visible = a > 0
        arr[..., 0][visible] = 255
        arr[..., 1][visible] = 255
        arr[..., 2][visible] = 255
        return Image.fromarray(arr, mode="RGBA")
    
    base_color = TEAM_COLORS.get(team, (255, 255, 255))
    if status == "construction":
        base_color = tuple((c + 255) // 2 for c in base_color)
    
    # More lenient white mask - catches lighter grays and off-whites
    # Old: all channels > 200
    # New: all channels > 180 OR average brightness > 200
    avg_brightness = (r.astype(np.float32) + g.astype(np.float32) + b.astype(np.float32)) / 3.0
    
    white_mask = (
        (
            ((r > 180) & (g > 180) & (b > 180)) |  # Light colors
            (avg_brightness > 200)                   # OR bright overall
        ) &
        (np.abs(r - g) < 30) &  # More tolerance for color deviation
        (np.abs(r - b) < 30) &
        (np.abs(g - b) < 30) &
        (a > 0)
    )
    
    arr[..., 0][white_mask] = base_color[0]
    arr[..., 1][white_mask] = base_color[1]
    arr[..., 2][white_mask] = base_color[2]
    
    return Image.fromarray(arr, mode="RGBA")




def get_icon(unit_name: str, team: str, status: str, scale: float):
    """
    Return a tinted & scaled icon for a unit/team/status.
    status: 'construction', 'complete', 'flash'
    """
    cache_key = (unit_name, team, status, scale)
    if cache_key in _icon_tinted_cache:
        return _icon_tinted_cache[cache_key]

    base = load_base_icon(unit_name)
    if base is None:
        _icon_tinted_cache[cache_key] = None
        return None

    tinted = tint_icon(base, team, status)
    if scale != 1.0:
        w, h = tinted.size
        new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
        tinted = tinted.resize(new_size, resample=Image.BICUBIC)

    _icon_tinted_cache[cache_key] = tinted
    return tinted


def get_resource_icon(icon_name: str, color: tuple, status: str, scale: float):
    """
    Get a resource icon with custom color tinting.
    
    Args:
        icon_name: Base icon name (e.g., "Resource_BalteriumField")
        color: RGB tuple for tinting
        status: 'complete' or 'flash'
        scale: Scale factor
    
    Returns:
        PIL Image or None
    """
    cache_key = ("resource", icon_name, color, status, scale)
    if cache_key in _icon_tinted_cache:
        return _icon_tinted_cache[cache_key]
    
    base = load_base_icon(icon_name)
    if base is None:
        _icon_tinted_cache[cache_key] = None
        return None
    
    arr = np.array(base)
    r = arr[..., 0]
    g = arr[..., 1]
    b = arr[..., 2]
    a = arr[..., 3]
    
    if status == "flash":
        # White flash
        visible = a > 0
        arr[..., 0][visible] = 255
        arr[..., 1][visible] = 255
        arr[..., 2][visible] = 255
    else:
        # Apply custom color to visible pixels
        avg_brightness = (r.astype(np.float32) + g.astype(np.float32) + b.astype(np.float32)) / 3.0
        bright_mask = (avg_brightness > 100) & (a > 0)
        
        arr[..., 0][bright_mask] = color[0]
        arr[..., 1][bright_mask] = color[1]
        arr[..., 2][bright_mask] = color[2]
    
    result = Image.fromarray(arr, mode="RGBA")
    
    if scale != 1.0:
        w, h = result.size
        new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
        result = result.resize(new_size, resample=Image.BICUBIC)
    
    _icon_tinted_cache[cache_key] = result
    return result

