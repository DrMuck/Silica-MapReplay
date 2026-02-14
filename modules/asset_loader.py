# -*- coding: utf-8 -*-
"""
Asset Loader Module

Loads assets from the obfuscated assets.pak file.
Supports on-demand loading (maps) and bulk preloading (icons).

Usage:
    from asset_loader import AssetPack
    
    pack = AssetPack("assets.pak")
    
    # Load a single asset as PIL Image (on-demand, for maps)
    map_img = pack.load_image("Maps/GreatErg.png")
    
    # Load a single asset as raw bytes
    raw = pack.load_bytes("Silica_Icons/Tac_Skull.png")
    
    # Preload all icons into cache
    pack.preload_prefix("Silica_Icons/")
    icon_img = pack.load_image("Silica_Icons/Tac_Skull.png")  # From cache
    
    # List all assets
    print(pack.list_assets())
"""

import io
import os
import zlib
import struct
from pathlib import Path
from PIL import Image

# Must match the key in pack_assets.py
_OBF_KEY = b"SilicaMapReplay2025"


def _deobfuscate(data: bytes) -> bytes:
    """XOR deobfuscate data with repeating key."""
    key = _OBF_KEY
    key_len = len(key)
    result = bytearray(len(data))
    for i in range(len(data)):
        result[i] = data[i] ^ key[i % key_len]
    return bytes(result)


class AssetPack:
    """
    Reads assets from an obfuscated .pak file.
    
    The TOC (table of contents) is loaded once at init.
    Individual assets are loaded on-demand or bulk-preloaded.
    """
    
    MAGIC = b"SILPAK01"
    
    def __init__(self, pak_path: str):
        """
        Open a .pak file and read its table of contents.
        
        Args:
            pak_path: Path to the assets.pak file
            
        Raises:
            FileNotFoundError: If pak file doesn't exist
            ValueError: If pak file is corrupt or wrong format
        """
        self.pak_path = pak_path
        self._toc = {}       # rel_path -> (offset, comp_size, orig_size)
        self._cache = {}     # rel_path -> PIL Image (for preloaded assets)
        self._file = None    # Keep file handle open for seeking
        
        if not os.path.isfile(pak_path):
            raise FileNotFoundError(f"Asset pack not found: {pak_path}")
        
        self._read_toc()
    
    def _read_toc(self):
        """Read the table of contents from the pak file."""
        with open(self.pak_path, "rb") as f:
            # Read header
            magic = f.read(8)
            if magic != self.MAGIC:
                raise ValueError(f"Invalid pak file (bad magic): {self.pak_path}")
            
            num_entries = struct.unpack("<I", f.read(4))[0]
            toc_offset = struct.unpack("<I", f.read(4))[0]
            
            # Read TOC
            f.seek(toc_offset)
            for _ in range(num_entries):
                path_len = struct.unpack("<H", f.read(2))[0]
                rel_path = f.read(path_len).decode("utf-8")
                offset, comp_size, orig_size = struct.unpack("<III", f.read(12))
                self._toc[rel_path] = (offset, comp_size, orig_size)
    
    def list_assets(self, prefix: str = "") -> list:
        """
        List all asset paths in the pack.
        
        Args:
            prefix: Optional filter prefix (e.g., "Maps/" or "Silica_Icons/")
            
        Returns:
            Sorted list of relative paths
        """
        if prefix:
            return sorted(p for p in self._toc if p.startswith(prefix))
        return sorted(self._toc.keys())
    
    def has_asset(self, rel_path: str) -> bool:
        """Check if an asset exists in the pack."""
        return rel_path in self._toc
    
    def load_bytes(self, rel_path: str) -> bytes:
        """
        Load an asset as raw bytes (decompressed).
        
        Args:
            rel_path: Relative path (e.g., "Maps/GreatErg.png")
            
        Returns:
            Decompressed file bytes
            
        Raises:
            KeyError: If asset not found in pack
        """
        if rel_path not in self._toc:
            raise KeyError(f"Asset not found in pack: {rel_path}")
        
        offset, comp_size, orig_size = self._toc[rel_path]
        
        with open(self.pak_path, "rb") as f:
            f.seek(offset)
            obfuscated = f.read(comp_size)
        
        compressed = _deobfuscate(obfuscated)
        return zlib.decompress(compressed)
    
    def load_image(self, rel_path: str) -> Image.Image:
        """
        Load an asset as a PIL RGBA Image.
        Returns from cache if previously preloaded.
        
        Args:
            rel_path: Relative path (e.g., "Maps/GreatErg.png")
            
        Returns:
            PIL Image in RGBA mode
        """
        # Check cache first
        if rel_path in self._cache:
            return self._cache[rel_path].copy()
        
        raw = self.load_bytes(rel_path)
        img = Image.open(io.BytesIO(raw)).convert("RGBA")
        return img
    
    def preload_images(self, rel_paths: list) -> int:
        """
        Preload specific assets into the image cache.
        
        Args:
            rel_paths: List of relative paths to preload
            
        Returns:
            Number of successfully loaded images
        """
        loaded = 0
        for rel_path in rel_paths:
            if rel_path in self._cache:
                loaded += 1
                continue
            try:
                raw = self.load_bytes(rel_path)
                img = Image.open(io.BytesIO(raw)).convert("RGBA")
                self._cache[rel_path] = img
                loaded += 1
            except Exception as e:
                print(f"[ASSET PACK] Failed to preload {rel_path}: {e}")
        return loaded
    
    def preload_prefix(self, prefix: str) -> int:
        """
        Preload all assets matching a prefix into cache.
        
        Args:
            prefix: Path prefix (e.g., "Silica_Icons/")
            
        Returns:
            Number of successfully loaded images
        """
        paths = self.list_assets(prefix)
        return self.preload_images(paths)
    
    def get_cached_image(self, rel_path: str):
        """
        Get a preloaded image from cache (no disk I/O).
        Returns None if not cached.
        
        Args:
            rel_path: Relative path
            
        Returns:
            PIL Image copy or None
        """
        img = self._cache.get(rel_path)
        if img is not None:
            return img.copy()
        return None
    
    def clear_cache(self):
        """Clear all cached images from memory."""
        self._cache.clear()


# ============================================================
# Global singleton for easy access across modules
# ============================================================

_global_pack = None


def init_asset_pack(pak_path: str = None) -> AssetPack:
    """
    Initialize the global asset pack singleton.
    
    Args:
        pak_path: Path to assets.pak. If None, auto-detects from script location.
        
    Returns:
        The AssetPack instance
    """
    global _global_pack
    
    if pak_path is None:
        # Auto-detect: look for assets.pak next to this file or in parent
        here = Path(__file__).parent.resolve()
        candidates = [
            here / "assets.pak",
            here.parent / "assets.pak",
        ]
        for candidate in candidates:
            if candidate.is_file():
                pak_path = str(candidate)
                break
        
        if pak_path is None:
            raise FileNotFoundError(
                "assets.pak not found. Run pack_assets.py first, or provide the path explicitly."
            )
    
    _global_pack = AssetPack(pak_path)
    count = len(_global_pack.list_assets())
    print(f"[ASSET PACK] Loaded TOC: {count} assets from {pak_path}")
    return _global_pack


def get_asset_pack() -> AssetPack:
    """Get the global AssetPack instance. Must call init_asset_pack() first."""
    if _global_pack is None:
        raise RuntimeError("Asset pack not initialized. Call init_asset_pack() first.")
    return _global_pack
