# -*- coding: utf-8 -*-
"""
Map Loader Helper

Provides load_map() which loads map images from asset pack or raw files.
Used by both Replay_Main.py and MapReplay_Service.py.

Usage:
    from map_loader import load_map
    
    base_map = load_map("GreatErg")       # Loads from asset pack or file
    base_map = load_map("GreatErg", maps_dir="Assets/Maps")  # Explicit fallback dir
"""

import os
from PIL import Image

# Asset pack support
try:
    from asset_loader import get_asset_pack
    _HAS_ASSET_LOADER = True
except ImportError:
    _HAS_ASSET_LOADER = False


def load_map(map_name: str, maps_dir: str = None, map_path: str = None) -> Image.Image:
    """
    Load a map image by name. Tries asset pack first, then raw file.
    
    Args:
        map_name: Map name without extension (e.g., "GreatErg")
        maps_dir: Directory containing raw map PNGs (fallback)
        map_path: Full path to a specific map file (overrides maps_dir)
        
    Returns:
        PIL Image in RGBA mode
        
    Raises:
        FileNotFoundError: If map cannot be found in pack or on disk
    """
    rel_path = f"Maps/{map_name}.png"
    
    # --- Try asset pack first ---
    if _HAS_ASSET_LOADER:
        try:
            pack = get_asset_pack()
            if pack.has_asset(rel_path):
                img = pack.load_image(rel_path)
                print(f"[MAP] Loaded {map_name} from asset pack")
                return img
        except RuntimeError:
            pass  # Pack not initialized
    
    # --- Fallback: load from file ---
    if map_path and os.path.isfile(map_path):
        img = Image.open(map_path).convert("RGBA")
        print(f"[MAP] Loaded {map_name} from file: {map_path}")
        return img
    
    if maps_dir:
        file_path = os.path.join(maps_dir, f"{map_name}.png")
        if os.path.isfile(file_path):
            img = Image.open(file_path).convert("RGBA")
            print(f"[MAP] Loaded {map_name} from file: {file_path}")
            return img
    
    raise FileNotFoundError(
        f"Map '{map_name}' not found in asset pack or on disk. "
        f"Checked: asset pack '{rel_path}'"
        + (f", file '{map_path}'" if map_path else "")
        + (f", dir '{maps_dir}'" if maps_dir else "")
    )
