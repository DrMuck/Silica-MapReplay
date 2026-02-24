#!/usr/bin/env python3
"""Quick test: render a replay with .srpl unit position overlay."""

import sys
import os

# modules/ must come first so module imports (config, statistics, etc.) resolve correctly
script_dir = os.path.dirname(os.path.abspath(__file__))
modules_dir = os.path.join(script_dir, "modules")
sys.path.insert(0, modules_dir)
sys.path.insert(1, script_dir)
os.chdir(modules_dir)

from Replay_Main import process_replay

# Paths
LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "Userdata", "logs", "L20260220.log")
SRPL_PATH = os.path.join(os.path.dirname(__file__), "..", "Mods", "ReplayLogs", "20260220_171809_WhisperingPlains.srpl")
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "Replays", "test_srpl_units.mp4")

# Ensure output dir exists
os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

process_replay(
    log_path=LOG_PATH,
    map_path="WhisperingPlains.png",  # name used for asset pack lookup
    icon_dir="",  # loaded from assets.pak
    output_path=OUTPUT_PATH,
    world_extent=2048,  # WhisperingPlains
    resolution="1440p",
    test_mode=False,
    game_index=8,  # 17:18:09 game
    srpl_path=SRPL_PATH,
)
