# -*- coding: utf-8 -*-
"""
Extract map images, icons, and map scale data directly from Silica game assets.

Reads Unity asset files via UnityPy — no manual AssetRipper step needed.
Run this whenever the game updates to refresh assets.pak.

Usage:
    python extract_game_assets.py                          # extract + rebuild assets.pak
    python extract_game_assets.py --extract-only           # extract PNGs to Assets/ only
    python extract_game_assets.py --game-dir "D:/Silica"   # custom game path

Requires: pip install UnityPy Pillow
"""

import argparse
import io
import os
import struct
import sys
import time
import zlib
from pathlib import Path

try:
    import UnityPy
except ImportError:
    print("ERROR: UnityPy not installed. Run: pip install UnityPy")
    sys.exit(1)

from PIL import Image

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Default game install paths to search (client install has the full assets)
DEFAULT_GAME_DIRS = [
    r"C:\SteamLibrary\steamapps\common\Silica",
    r"C:\Program Files (x86)\Steam\steamapps\common\Silica",
    r"D:\SteamLibrary\steamapps\common\Silica",
    r"E:\Steam\steamapps\common\Silica",
]

# All textures in sharedassets0.assets — maps + icons + logos
SHAREDASSETS_INDEX = 0

# Map texture names (exact Texture2D.m_Name values)
MAP_TEXTURE_NAMES = {
    "Badlands", "BlackIsle", "Citadel", "CombatDome", "CrimsonPeak",
    "CrystalChasm", "GreatErg", "IndustrialQuarter", "MonumentValley",
    "NarakaCity", "NorthPolarCap", "PowerStation", "ProvingGrounds",
    "RiftBasin", "RiftBasin_TD", "SandboxTest", "SmallStrategyTest",
    "TheMaw", "WhisperingPlains",
}

# Icon prefix
ICON_PREFIX = "Tac_"

# Extra non-Tac textures to include (logos/faction icons used by MapReplay)
EXTRA_ICON_NAMES = {
    "512x512_Sol_Logo-01",
    "512x512_alien_logo",
    "Centauri_512x512-01-01",
    "Silica_Logo",
    "centauri-fist",
}

# Known world extents (half-size: world coords go from -extent to +extent)
# For multi-tile maps these can't be auto-computed reliably from terrain data.
KNOWN_WORLD_EXTENTS = {
    "Badlands": 3000,
    "BlackIsle": 1000,
    "CombatDome": 500,
    "CrimsonPeak": 2048,
    "CrystalChasm": 1500,
    "GreatErg": 3000,
    "MonumentValley": 3000,
    "NarakaCity": 3000,
    "NorthPolarCap": 2048,
    "PowerStation": 500,
    "RiftBasin": 1500,
    "RiftBasin_TD": 1500,
    "SmallStrategyTest": 500,
    "TheMaw": 1500,
    "WhisperingPlains": 2048,
}

# Obfuscation key (must match asset_loader.py)
_OBF_KEY = b"SilicaMapReplay2025"
_PAK_MAGIC = b"SILPAK01"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_game_dir(custom_path=None):
    """Locate the Silica game installation."""
    if custom_path:
        data_dir = os.path.join(custom_path, "Silica_Data")
        if os.path.isdir(data_dir):
            return custom_path
        raise FileNotFoundError(f"Silica_Data not found in: {custom_path}")

    for d in DEFAULT_GAME_DIRS:
        data_dir = os.path.join(d, "Silica_Data")
        if os.path.isdir(data_dir):
            return d
    raise FileNotFoundError(
        "Could not find Silica installation. Use --game-dir to specify the path."
    )


def get_scene_list(game_data_dir):
    """Read BuildSettings to get scene name -> level index mapping."""
    ggm = os.path.join(game_data_dir, "globalgamemanagers")
    env = UnityPy.load(ggm)
    for obj in env.objects:
        if obj.type.name == "BuildSettings":
            tree = obj.read_typetree()
            scenes = tree.get("scenes", [])
            # Extract map name from scene path
            result = {}
            for i, path in enumerate(scenes):
                # e.g. "Assets/Baltarus/Scenes/Worlds/Citadel.unity" -> "Citadel"
                name = Path(path).stem
                result[name] = i
            return result
    return {}


def compute_world_extents(game_data_dir, map_names):
    """
    Compute world extents from TerrainData for single-tile maps.
    Returns dict of {map_name: extent} for maps we could determine.
    """
    extents = dict(KNOWN_WORLD_EXTENTS)

    # Find which sharedassets file has each map's terrain
    # sharedassets indices roughly correspond to level indices for world scenes
    scene_map = get_scene_list(game_data_dir)

    for map_name in map_names:
        if map_name in extents:
            continue  # Already known

        # Try the sharedassets file matching the scene index
        scene_idx = scene_map.get(map_name)
        if scene_idx is None:
            continue

        sa_file = os.path.join(game_data_dir, f"sharedassets{scene_idx}.assets")
        if not os.path.isfile(sa_file):
            continue

        try:
            env = UnityPy.load(sa_file)
            tile_count = 0
            tile_size = 0
            for obj in env.objects:
                if obj.type.name == "TerrainData":
                    tree = obj.read_typetree()
                    hm = tree.get("m_Heightmap", {})
                    scales = hm.get("m_Scale", {})
                    res = hm.get("m_Resolution", 0)
                    sx = scales.get("x", 0) if isinstance(scales, dict) else 0
                    ts = (res - 1) * sx
                    if ts > 0:
                        tile_count += 1
                        tile_size = ts

            if tile_count == 1:
                # Single-tile: extent = tile_size / 2
                extent = int(tile_size / 2)
                extents[map_name] = extent
                print(f"  [TERRAIN] {map_name}: single tile {tile_size:.0f}m -> extent {extent}")
            elif tile_count > 1:
                print(f"  [TERRAIN] {map_name}: {tile_count} tiles - needs manual extent in KNOWN_WORLD_EXTENTS")
        except Exception as e:
            print(f"  [TERRAIN] {map_name}: error reading terrain - {e}")

    return extents


def extract_textures(game_data_dir, output_dir):
    """
    Extract map images and icons from sharedassets0.assets.
    Returns (maps_extracted, icons_extracted, extras_extracted) as lists of (name, path).
    """
    sa_file = os.path.join(game_data_dir, f"sharedassets{SHAREDASSETS_INDEX}.assets")
    print(f"Loading {sa_file}...")
    t0 = time.time()
    env = UnityPy.load(sa_file)
    print(f"  Loaded in {time.time() - t0:.1f}s ({len(env.objects)} objects)")

    maps_dir = os.path.join(output_dir, "Maps")
    icons_dir = os.path.join(output_dir, "Silica_Icons")
    os.makedirs(maps_dir, exist_ok=True)
    os.makedirs(icons_dir, exist_ok=True)

    maps_extracted = []
    icons_extracted = []
    extras_extracted = []

    print("Extracting textures...")
    for obj in env.objects:
        if obj.type.name != "Texture2D":
            continue

        data = obj.read()
        name = data.m_Name

        if name in MAP_TEXTURE_NAMES:
            out_path = os.path.join(maps_dir, f"{name}.png")
            img = data.image
            img.save(out_path)
            maps_extracted.append((name, out_path))
            print(f"  Map: {name} ({img.size[0]}x{img.size[1]})")

        elif name.startswith(ICON_PREFIX):
            out_path = os.path.join(icons_dir, f"{name}.png")
            img = data.image
            img.save(out_path)
            icons_extracted.append((name, out_path))

        elif name in EXTRA_ICON_NAMES:
            out_path = os.path.join(icons_dir, f"{name}.png")
            img = data.image
            img.save(out_path)
            extras_extracted.append((name, out_path))

    print(f"  Extracted: {len(maps_extracted)} maps, {len(icons_extracted)} icons, {len(extras_extracted)} extras")
    return maps_extracted, icons_extracted, extras_extracted


# ---------------------------------------------------------------------------
# Pack assets.pak
# ---------------------------------------------------------------------------

def _obfuscate(data: bytes) -> bytes:
    """XOR obfuscate data with repeating key."""
    key = _OBF_KEY
    key_len = len(key)
    result = bytearray(len(data))
    for i in range(len(data)):
        result[i] = data[i] ^ key[i % key_len]
    return bytes(result)


def build_pak(assets_dir, pak_path, map_scales_data=None):
    """
    Build assets.pak from extracted asset files.

    Scans assets_dir for Maps/*.png, Silica_Icons/*.png, and Maps/Map_Scales.txt.
    """
    entries = []  # (rel_path, file_path)

    # Collect files
    for root, dirs, files in os.walk(assets_dir):
        for fname in sorted(files):
            fpath = os.path.join(root, fname)
            rel = os.path.relpath(fpath, assets_dir).replace("\\", "/")
            entries.append((rel, fpath))

    # Add Map_Scales.txt if we have data
    scales_path = os.path.join(assets_dir, "Maps", "Map_Scales.txt")
    if map_scales_data:
        with open(scales_path, "w") as f:
            f.write(map_scales_data)
        # Make sure it's in entries
        if not any(r == "Maps/Map_Scales.txt" for r, _ in entries):
            entries.append(("Maps/Map_Scales.txt", scales_path))

    entries.sort(key=lambda x: x[0])
    print(f"Packing {len(entries)} assets into {pak_path}...")

    toc_entries = []  # (rel_path, offset, comp_size, orig_size)

    with open(pak_path, "wb") as f:
        # Write header placeholder (magic + num_entries + toc_offset)
        f.write(_PAK_MAGIC)
        f.write(struct.pack("<I", len(entries)))  # num_entries
        f.write(struct.pack("<I", 0))  # toc_offset placeholder

        # Write asset data
        for rel_path, file_path in entries:
            with open(file_path, "rb") as af:
                raw = af.read()

            compressed = zlib.compress(raw, 6)
            obfuscated = _obfuscate(compressed)

            offset = f.tell()
            f.write(obfuscated)
            toc_entries.append((rel_path, offset, len(obfuscated), len(raw)))

        # Write TOC
        toc_offset = f.tell()
        for rel_path, offset, comp_size, orig_size in toc_entries:
            path_bytes = rel_path.encode("utf-8")
            f.write(struct.pack("<H", len(path_bytes)))
            f.write(path_bytes)
            f.write(struct.pack("<III", offset, comp_size, orig_size))

        # Update header with toc_offset
        f.seek(12)  # after magic(8) + num_entries(4)
        f.write(struct.pack("<I", toc_offset))

    pak_size = os.path.getsize(pak_path)
    print(f"  Created {pak_path} ({pak_size / 1024 / 1024:.1f} MB, {len(entries)} assets)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Extract Silica game assets and build assets.pak")
    parser.add_argument("--game-dir", help="Path to Silica game installation")
    parser.add_argument("--output-dir", default=None,
                        help="Directory for extracted PNGs (default: Assets/ in script dir)")
    parser.add_argument("--pak-output", default=None,
                        help="Output path for assets.pak (default: assets.pak in script dir)")
    parser.add_argument("--extract-only", action="store_true",
                        help="Only extract PNGs, don't build assets.pak")
    parser.add_argument("--pak-only", action="store_true",
                        help="Only rebuild assets.pak from existing Assets/ dir")
    args = parser.parse_args()

    script_dir = Path(__file__).parent.resolve()
    output_dir = args.output_dir or str(script_dir / "Assets")
    pak_path = args.pak_output or str(script_dir / "assets.pak")

    if not args.pak_only:
        # Find game
        game_dir = find_game_dir(args.game_dir)
        game_data_dir = os.path.join(game_dir, "Silica_Data")
        print(f"Game found: {game_dir}")

        # Extract textures
        maps, icons, extras = extract_textures(game_data_dir, output_dir)
        map_names = {name for name, _ in maps}

        # Compute world extents
        print("Computing world extents from terrain data...")
        extents = compute_world_extents(game_data_dir, map_names)

        # Build Map_Scales.txt
        scales_lines = []
        for name, _ in sorted(maps):
            img = Image.open(os.path.join(output_dir, "Maps", f"{name}.png"))
            w, h = img.size
            ext = extents.get(name)
            if ext:
                scales_lines.append(f"{name}.png {w}x{h}\t{ext}")
            else:
                scales_lines.append(f"{name}.png {w}x{h}\t# UNKNOWN - set manually")
                print(f"  WARNING: no world extent for {name} — edit Map_Scales.txt")

        map_scales_data = "\n".join(scales_lines) + "\n"

        # Write Map_Scales.txt to disk
        scales_path = os.path.join(output_dir, "Maps", "Map_Scales.txt")
        with open(scales_path, "w") as f:
            f.write(map_scales_data)
        print(f"Wrote {scales_path}")

        # Print summary
        print(f"\nExtraction complete:")
        print(f"  Maps: {len(maps)}")
        print(f"  Icons: {len(icons)}")
        print(f"  Extras: {len(extras)}")
        print(f"  Output: {output_dir}")

        missing_extents = [n for n, _ in maps if n not in extents]
        if missing_extents:
            print(f"\n  Maps missing world extents: {', '.join(missing_extents)}")
            print(f"  Add them to KNOWN_WORLD_EXTENTS in this script, then re-run.")

    if not args.extract_only:
        if args.pak_only and not os.path.isdir(output_dir):
            print(f"ERROR: Assets directory not found: {output_dir}")
            print(f"Run without --pak-only first to extract assets.")
            sys.exit(1)

        # Read Map_Scales.txt if it exists
        scales_path = os.path.join(output_dir, "Maps", "Map_Scales.txt")
        map_scales_data = None
        if os.path.isfile(scales_path):
            with open(scales_path) as f:
                map_scales_data = f.read()

        build_pak(output_dir, pak_path, map_scales_data)

    print("\nDone!")


if __name__ == "__main__":
    main()
