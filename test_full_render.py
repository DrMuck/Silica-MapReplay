#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
"""
Full render test: parse log + SRPL, render all frames with detailed timing.
Tests the new SRPL-tick-driven approach with full killbar/graphs/stats.

Usage:
    python test_full_render.py
"""

import sys
import os
import time
import logging
import struct
from datetime import datetime
from collections import defaultdict

# Path setup: modules/ first, then service root
script_dir = os.path.dirname(os.path.abspath(__file__))
modules_dir = os.path.join(script_dir, "modules")
sys.path.insert(0, modules_dir)
sys.path.insert(1, script_dir)
os.chdir(modules_dir)

# --- Paths ---
LOG_PATH    = r"E:\Steam\steamapps\common\Silica Dedicated Server\UserData\logs\L20260315.log"
SRPL_PATH   = r"E:\Steam\steamapps\common\Silica Dedicated Server\Mods\ReplayLogs\20260315_213211_MonumentValley.srpl"
OUTPUT_PATH = r"C:\Users\schwe\temp_replay_test\MV_full_render_test.mp4"
LOG_DATE    = datetime(2026, 3, 15)  # For Unix time computation

TARGET_MAP    = "MonumentValley"
# Approximate game start from SRPL filename (21:32:11 local) → used to select right game
TARGET_HOUR   = 21

os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

# --- Logging ---
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("test_full_render")

# --- Imports from service and modules ---
from MapReplay_Service import LiveLogParser, LiveGameState, LiveConfig
from srpl_reader import LiveSrplReader, SrplReplay
from statistics import build_all_stats_from_log, build_player_stats_from_kills, build_resource_stats_from_log, build_kill_stats_from_srpl
from data_models import Building
import config as cfg
from asset_loader import init_asset_pack
from map_loader import load_map
from renderer import render_frame, RenderCache, clear_render_cache
import imageio.v2 as imageio
import numpy as np

# ---------------------------------------------------------------------------
# Step 1: Parse the log file to find the target game
# ---------------------------------------------------------------------------
print(f"\n{'='*70}")
print("STEP 1: Parsing log file...")
print(f"{'='*70}")

live_config = LiveConfig()
parser = LiveLogParser(logger)

target_game = None
game_candidates = []

t0_parse = time.perf_counter()
with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
    for line in f:
        result = parser.process_line(line.rstrip("\n"))

# After parsing all lines, check current (possibly unended) game and completed games
all_games = list(parser.completed_games)
if parser.current_game and not parser.current_game.is_ended:
    # Force-end the current game (last game in log, may not have Round_Win yet)
    parser.current_game.is_ended = True
    all_games.append(parser.current_game)

t_parse = time.perf_counter() - t0_parse
print(f"Log parsed in {t_parse:.2f}s — found {len(all_games)} games")

for i, g in enumerate(all_games):
    start_h = int(g.start_time // 3600) % 24
    print(f"  [{i}] {g.map_name:20s}  start={g.start_time:.0f}s ({start_h:02d}h)  "
          f"duration={g.game_time:.0f}s  kills={len(g.kills)}")

# Find the target game: MonumentValley starting around 21:xx
for g in all_games:
    start_h = int(g.start_time // 3600) % 24
    if g.map_name == TARGET_MAP and start_h == TARGET_HOUR:
        target_game = g
        break

if not target_game:
    logger.error(f"Could not find {TARGET_MAP} game at hour {TARGET_HOUR}. Exiting.")
    sys.exit(1)

start_h = int(target_game.start_time // 3600) % 24
start_m = int((target_game.start_time % 3600) // 60)
start_s = int(target_game.start_time % 60)
print(f"\nTarget game: {target_game.map_name} @ {start_h:02d}:{start_m:02d}:{start_s:02d}")
print(f"  Duration  : {target_game.game_time:.0f}s ({target_game.game_time/60:.1f} min)")
print(f"  Kills     : {len(target_game.kills)}")
print(f"  Buildings : {len(target_game.buildings)}")
print(f"  Resources : {len(target_game.resource_status_events)} events")

# Compute _start_unix from log date + log time
game_dt = LOG_DATE.replace(hour=start_h, minute=start_m, second=start_s)
target_game._start_unix = game_dt.timestamp()
print(f"  _start_unix: {target_game._start_unix:.0f} ({game_dt})")

# ---------------------------------------------------------------------------
# Step 2: Open and fully read the SRPL file
# ---------------------------------------------------------------------------
print(f"\n{'='*70}")
print("STEP 2: Loading SRPL file...")
print(f"{'='*70}")

t0_srpl = time.perf_counter()
reader = LiveSrplReader(SRPL_PATH)
if not reader.open():
    logger.error("Failed to open SRPL file. Exiting.")
    sys.exit(1)

# Read all available records
total_records = 0
while True:
    n = reader.refresh()
    total_records += n
    if n == 0:
        break

replay = reader.replay
t_srpl = time.perf_counter() - t0_srpl

print(f"SRPL loaded in {t_srpl:.2f}s")
print(f"  Map       : {replay.map_name}")
print(f"  Tick int  : {replay.tick_interval_ms}ms")
print(f"  Ticks     : {len(replay.tick_numbers)} ({replay.max_tick})")
print(f"  Entities  : {len(replay.entities)}")
print(f"  Duration  : {replay.tick_to_seconds(replay.max_tick):.0f}s ({replay.tick_to_seconds(replay.max_tick)/60:.1f} min)")
print(f"  start_ts  : {replay.start_timestamp} ({datetime.fromtimestamp(replay.start_timestamp)})")

# Compute time_offset
if replay.start_timestamp > 0 and target_game._start_unix > 0:
    offset = target_game._start_unix - replay.start_timestamp
    replay.time_offset = max(0.0, offset)
    print(f"  time_offset: {offset:.1f}s -> clamped to {replay.time_offset:.1f}s")
else:
    print("  time_offset: could not compute (missing timestamps)")

# ---------------------------------------------------------------------------
# Step 3: Set up renderer
# ---------------------------------------------------------------------------
print(f"\n{'='*70}")
print("STEP 3: Loading map and assets...")
print(f"{'='*70}")

t0_map = time.perf_counter()
pack = init_asset_pack()
base_map_full = load_map(TARGET_MAP)
if base_map_full is None:
    logger.error("Map image not found. Exiting.")
    sys.exit(1)

# Scale to config MAP_SIZE
map_size = cfg.MAP_SIZE
from PIL import Image
base_map = base_map_full.resize((map_size, map_size), Image.LANCZOS)
print(f"Map loaded: {base_map_full.size} -> scaled to {base_map.size}")
t_map = time.perf_counter() - t0_map
print(f"Assets loaded in {t_map:.2f}s")

# ---------------------------------------------------------------------------
# Step 4: Build stats
# ---------------------------------------------------------------------------
print(f"\n{'='*70}")
print("STEP 4: Building stats...")
print(f"{'='*70}")

t0_stats = time.perf_counter()

game = target_game
buildings = {}
for key, b in game.buildings.items():
    buildings[key] = Building(
        team=b["team"], name=b["name"], x=b["x"], y=b["y"],
        start_t=b["start_t"], complete_t=b["complete_t"],
        destroy_t=b["destroy_t"], sold_t=b["sold_t"]
    )

kill_stats, building_stats = build_all_stats_from_log(
    buildings, game.kills, team_tech_events=dict(game.team_tech_events)
)
player_stats = build_player_stats_from_kills(game.kills)

for death in game.deaths:
    if death.player_name in player_stats:
        p = player_stats[death.player_name]
        p.total_deaths += 1
        if death.death_type == "suicide":
            p.suicide_deaths += 1
        p.death_events.append(death)

unit_kill_stats = defaultdict(int)
for kill in game.kills:
    if kill.attacker_unit and kill.attacker_unit != "Unknown":
        unit_kill_stats[kill.attacker_unit] += 1

resource_stats = None
if game.resource_status_events:
    resource_stats = build_resource_stats_from_log(game.resource_status_events)

# Override kill_stats with SRPL data
if replay.destructions:
    kill_stats = build_kill_stats_from_srpl(replay)
    print("  Using SRPL kill_stats (includes AI kills)")

t_stats = time.perf_counter() - t0_stats
print(f"Stats built in {t_stats*1000:.1f}ms")

# ---------------------------------------------------------------------------
# Step 5: Render all frames
# ---------------------------------------------------------------------------
print(f"\n{'='*70}")
print("STEP 5: Rendering frames...")
print(f"{'='*70}")

world_extent = cfg.get_world_extent(TARGET_MAP)
resolution   = cfg.VIDEO_RESOLUTION
frame_step   = cfg.FRAME_STEP
fps          = cfg.VIDEO_FPS

# Resolution
res_map = {"720p": (1280, 720), "1080p": (1920, 1080), "1440p": (2560, 1440), "4k": (3840, 2160)}
frame_w, frame_h = res_map.get(resolution, (2560, 1440))

# Total frames to generate
total_game_time = game.game_time
frame_times = []
t = 0.0
while t <= total_game_time:
    frame_times.append(t)
    t += frame_step
## frame_times = frame_times[:1500]  # cap for benchmarking (disabled)

print(f"Resolution : {frame_w}x{frame_h} ({resolution})")
print(f"Game time  : {total_game_time:.0f}s ({total_game_time/60:.1f} min)")
print(f"Frame step : {frame_step}s, FPS: {fps}")
print(f"Frames     : {len(frame_times)}")

# Video writer
try:
    bitrate = 2200  # kbps
    preset  = 'veryfast'
    writer = imageio.get_writer(OUTPUT_PATH, fps=fps, codec='libx264',
                                quality=None, bitrate=None,
                                output_params=[
                                    '-b:v',      f'{bitrate}k',
                                    '-maxrate',  f'{int(bitrate * 1.5)}k',
                                    '-bufsize',  f'{bitrate}k',
                                    '-preset',   preset,
                                    '-tune',     'animation',
                                    '-g',        '90',
                                    '-bf',       '0',
                                    '-threads',  '2',
                                    '-pix_fmt',  'yuv420p',
                                    '-movflags', '+faststart',
                                ])
except Exception as e:
    logger.error(f"Failed to create video writer: {e}")
    sys.exit(1)

# Render cache (for killbar scroll buffer, stats panel cache, etc.)
clear_render_cache()
render_cache = RenderCache()

# Per-component timing accumulators
timing_accum = defaultdict(float)
timing_counts = defaultdict(int)

# Phase timers
t0_render_total = time.perf_counter()
t_stats_rebuild_total = 0.0
t_write_total = 0.0

progress_interval = max(1, len(frame_times) // 20)

for i, t_frame in enumerate(frame_times):
    # --- Stats rebuild timing (happens every call in current impl) ---
    # (stats are prebuilt above; this measures per-frame position lookup + dying unit detection)

    # Unit positions via SRPL interpolation
    t0_pos = time.perf_counter()
    unit_positions = replay.get_positions_at_time(t_frame + replay.time_offset)
    t_pos = time.perf_counter() - t0_pos

    # Dying units
    dying_units = set()
    for dest_tick, victim_id, _, is_building in replay.destructions:
        if not is_building:
            dest_t = replay.tick_to_seconds(dest_tick) - replay.time_offset
            if t_frame <= dest_t <= t_frame + frame_step * 3:
                dying_units.add(victim_id)

    # --- render_frame with timing_detail ---
    timing_detail = {}
    t0_rf = time.perf_counter()
    frame_img = render_frame(
        base_map, buildings, game.kills, kill_stats, building_stats,
        player_stats, unit_kill_stats, game.commanders,
        t_frame,
        world_extent=world_extent,
        timing_detail=timing_detail,
        frame_num=i,
        resources=list(game.resources.values()),
        victory_info=game.victory_info,
        t_end=total_game_time,
        total_frames=len(frame_times),
        map_name=game.map_name,
        log_date=game.log_date,
        start_time=f"{start_h:02d}:{start_m:02d}",
        chat_messages=game.chat_messages,
        resource_stats=resource_stats,
        unit_positions=unit_positions,
        dying_units=dying_units,
    )
    t_rf = time.perf_counter() - t0_rf

    # Accumulate detailed timings
    for k, v in timing_detail.items():
        timing_accum[k] += v
        timing_counts[k] += 1
    timing_accum['_pos_lookup'] += t_pos
    timing_accum['_render_total'] += t_rf

    # --- Write frame ---
    t0_wr = time.perf_counter()
    frame_np = np.array(frame_img.convert("RGB"))
    writer.append_data(frame_np)
    t_wr = time.perf_counter() - t0_wr
    t_write_total += t_wr

    if i % progress_interval == 0 or i == len(frame_times) - 1:
        pct = (i + 1) / len(frame_times) * 100
        elapsed = time.perf_counter() - t0_render_total
        fps_actual = (i + 1) / elapsed if elapsed > 0 else 0
        print(f"  {t_frame:6.0f}s / {total_game_time:.0f}s ({pct:3.0f}%)  "
              f"[frame {i+1}/{len(frame_times)}]  {fps_actual:.1f} frames/s")

writer.close()
t_render_total = time.perf_counter() - t0_render_total

# ---------------------------------------------------------------------------
# Step 6: Timing summary
# ---------------------------------------------------------------------------
print(f"\n{'='*70}")
print("TIMING SUMMARY")
print(f"{'='*70}")

n_frames = len(frame_times)
print(f"\n[Phase Timings]")
print(f"  {'Log parsing':25s}: {t_parse:.2f}s")
print(f"  {'SRPL loading':25s}: {t_srpl:.2f}s")
print(f"  {'Asset/map loading':25s}: {t_map:.2f}s")
print(f"  {'Stats building':25s}: {t_stats*1000:.1f}ms")
print(f"  {'Total render loop':25s}: {t_render_total:.2f}s")
print(f"  {'  Video write (within)':25s}: {t_write_total:.2f}s")

print(f"\n[Per-Frame Breakdown] ({n_frames} frames, {n_frames/t_render_total:.1f} frames/s)")
print(f"  {'Component':25s} {'Avg/frame':>12s} {'Total':>10s} {'%':>7s}")
print(f"  {'-'*58}")

render_only = timing_accum.get('_render_total', 0)
total_measured = render_only + timing_accum.get('_pos_lookup', 0) + t_write_total
# Exclude internal keys and upos count keys (not timings)
_count_keys = {'upos_n_units', 'upos_n_changed', 'upos_n_skipped'}
all_components = {k: v for k, v in timing_accum.items()
                  if not k.startswith('_') and k not in _count_keys}
all_components['_pos_lookup']    = timing_accum.get('_pos_lookup', 0)
all_components['_video_write']   = t_write_total
all_components['_render_overhead'] = render_only - sum(
    v for k, v in timing_accum.items()
    if not k.startswith('_') and k not in _count_keys
)

sorted_items = sorted(all_components.items(), key=lambda x: x[1], reverse=True)
total_accum = sum(v for v in all_components.values() if v > 0)

for name, total_t in sorted_items:
    if total_t <= 0:
        continue
    avg_ms = total_t / n_frames * 1000
    pct = total_t / total_accum * 100 if total_accum > 0 else 0
    display_name = name.lstrip('_')
    print(f"  {display_name:25s} {avg_ms:9.2f} ms {total_t:8.2f}s {pct:6.1f}%")

print(f"  {'-'*58}")
avg_total = t_render_total / n_frames * 1000
print(f"  {'TOTAL per frame':25s} {avg_total:9.2f} ms")
print(f"  {'Output FPS capacity':25s} {1000/avg_total:9.1f} fps")

# --- unit_positions sub-breakdown ---
upos_keys = ['upos_setup', 'upos_loop', 'upos_icon_fetch', 'upos_np_write',
             'upos_composite', 'upos_labels']
if any(timing_accum.get(k, 0) > 0 for k in upos_keys):
    upos_total = sum(timing_accum.get(k, 0) for k in upos_keys)
    upos_loop_other = (timing_accum.get('upos_loop', 0)
                       - timing_accum.get('upos_icon_fetch', 0)
                       - timing_accum.get('upos_np_write', 0))
    avg_units   = timing_accum.get('upos_n_units',   0) / n_frames
    avg_changed = timing_accum.get('upos_n_changed', 0) / n_frames
    avg_skipped = timing_accum.get('upos_n_skipped', 0) / n_frames
    print(f"\n[unit_positions sub-breakdown]  avg {avg_units:.0f} units/frame,"
          f" {avg_changed:.0f} changed, {avg_skipped:.0f} skipped")
    print(f"  {'Sub-component':25s} {'Avg/frame':>12s} {'Total':>10s} {'%':>7s}")
    print(f"  {'-'*58}")
    sub_rows = [
        ('loop (world_to_px/logic)', timing_accum.get('upos_loop', 0)),
        ('  icon_fetch (of loop)',   timing_accum.get('upos_icon_fetch', 0)),
        ('  np_write (of loop)',     timing_accum.get('upos_np_write', 0)),
        ('  loop_other',             upos_loop_other),
        ('composite (fromarray+ac)', timing_accum.get('upos_composite', 0)),
        ('labels',                   timing_accum.get('upos_labels', 0)),
        ('setup',                    timing_accum.get('upos_setup', 0)),
    ]
    for sname, stotal in sub_rows:
        savg = stotal / n_frames * 1000
        spct = stotal / upos_total * 100 if upos_total > 0 else 0
        print(f"  {sname:25s} {savg:9.2f} ms {stotal:8.2f}s {spct:6.1f}%")
    print(f"  {'-'*58}")
    print(f"  {'upos TOTAL':25s} {upos_total/n_frames*1000:9.2f} ms")

print(f"\nOutput: {OUTPUT_PATH}")
print(f"{'='*70}\n")
