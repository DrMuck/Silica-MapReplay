#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Replay Generator - Main Module

Main entry point for processing game replays.

Usage:
    from Replay_Main import process_replay
    
    process_replay(
        log_path="game.log",
        map_path="Maps/NarakaCity.png",
        icon_dir="Silica_Icons/",
        output_path="replay.mp4",
        world_extent=3000
    )
"""

import os
import sys
import math
import time
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.cm
from PIL import Image
import imageio.v2 as imageio
from tqdm import tqdm

# Import all modules
import config
from data_models import Building, KillEvent, DeathEvent
from statistics import build_all_stats_from_log, build_player_stats_from_kills, build_unit_kill_stats, build_resource_stats_from_log, build_kill_stats_from_srpl
from log_parser import parse_buildings_and_kills_from_log, world_to_pixel
from renderer import render_frame, make_heatmap_image
from icon_config import MISSING_ICON_TYPES
from asset_loader import init_asset_pack
from map_loader import load_map


class TimingStats:
    """Track timing statistics for performance analysis."""
    
    def __init__(self):
        self.timings = {}
        self.frame_timings = []
        self.render_detail = {}  # Accumulated detailed render timings
        self.start_time = None
    
    def start(self, name):
        """Start timing a section."""
        self.timings[f"{name}_start"] = time.perf_counter()
    
    def stop(self, name):
        """Stop timing a section and record duration."""
        end = time.perf_counter()
        start = self.timings.get(f"{name}_start", end)
        duration = end - start
        self.timings[name] = duration
        return duration
    
    def record_frame(self, heat_time, render_time, write_time, render_detail=None):
        """Record per-frame timing breakdown."""
        self.frame_timings.append({
            'heat': heat_time,
            'render': render_time,
            'write': write_time,
            'total': heat_time + render_time + write_time
        })
        
        # Accumulate detailed render timings
        if render_detail:
            for key, val in render_detail.items():
                self.render_detail[key] = self.render_detail.get(key, 0) + val
    
    def print_summary(self):
        """Print timing summary."""
        print("\n" + "="*70)
        print("TIMING SUMMARY")
        print("="*70)
        
        # Phase timings
        phases = ['log_parsing', 'stats_building', 'map_loading', 'video_init', 'frame_rendering']
        print("\n[Phase Timings]")
        for phase in phases:
            if phase in self.timings:
                print(f"  {phase:20s}: {self.timings[phase]:8.2f}s")
        
        # Total time
        if 'total' in self.timings:
            print(f"  {'TOTAL':20s}: {self.timings['total']:8.2f}s")
        
        # Frame timing breakdown
        if self.frame_timings:
            n_frames = len(self.frame_timings)
            print(f"\n[Frame Timing Breakdown] ({n_frames} frames)")
            
            avg_heat = sum(f['heat'] for f in self.frame_timings) / n_frames
            avg_render = sum(f['render'] for f in self.frame_timings) / n_frames
            avg_write = sum(f['write'] for f in self.frame_timings) / n_frames
            avg_total = sum(f['total'] for f in self.frame_timings) / n_frames
            
            total_heat = sum(f['heat'] for f in self.frame_timings)
            total_render = sum(f['render'] for f in self.frame_timings)
            total_write = sum(f['write'] for f in self.frame_timings)
            grand_total = total_heat + total_render + total_write
            
            print(f"  {'Component':20s} {'Avg/frame':>12s} {'Total':>12s} {'%':>8s}")
            print(f"  {'-'*56}")
            print(f"  {'Heat accumulation':20s} {avg_heat*1000:9.2f} ms {total_heat:9.2f}s {total_heat/grand_total*100:7.1f}%")
            print(f"  {'Frame rendering':20s} {avg_render*1000:9.2f} ms {total_render:9.2f}s {total_render/grand_total*100:7.1f}%")
            print(f"  {'Video writing':20s} {avg_write*1000:9.2f} ms {total_write:9.2f}s {total_write/grand_total*100:7.1f}%")
            print(f"  {'-'*56}")
            print(f"  {'TOTAL per frame':20s} {avg_total*1000:9.2f} ms")
            print(f"  {'Frames per second':20s} {1.0/avg_total:9.2f} fps")
        
        # Detailed render breakdown
        if self.render_detail:
            print(f"\n[Render Function Breakdown] (inside render_frame)")
            
            # Sort by time spent (descending)
            sorted_items = sorted(self.render_detail.items(), key=lambda x: x[1], reverse=True)
            total_detail = sum(self.render_detail.values())
            n_frames = len(self.frame_timings) if self.frame_timings else 1
            
            print(f"  {'Component':20s} {'Avg/frame':>12s} {'Total':>12s} {'%':>8s}")
            print(f"  {'-'*56}")
            for name, total_time in sorted_items:
                avg_time = total_time / n_frames
                pct = total_time / total_detail * 100 if total_detail > 0 else 0
                print(f"  {name:20s} {avg_time*1000:9.2f} ms {total_time:9.2f}s {pct:7.1f}%")
            print(f"  {'-'*56}")
            print(f"  {'TOTAL':20s} {total_detail/n_frames*1000:9.2f} ms {total_detail:9.2f}s")
        
        print("="*70 + "\n")


def process_replay(
    log_path,
    map_path,
    icon_dir,
    output_path,
    world_extent=3000,
    resolution="1440p",
    test_mode=False,
    gametype_filter=None,  # None = any game type, or specify e.g. "HUMANS_VS_HUMANS_VS_ALIENS"
    game_index=0,  # Which matching game to parse (0 = first, 1 = second, etc.)
    srpl_path=None  # Optional .srpl file for unit position overlay
):
    """
    Process a single replay video.
    
    Args:
        log_path: Path to game log file
        map_path: Path to map PNG file
        icon_dir: Directory containing unit icons
        output_path: Where to save output video
        world_extent: Map coordinate extent (e.g., 3000)
        resolution: "1080p", "1440p", or "4k"
        test_mode: If True, only render first 300 frames
        gametype_filter: Game type to filter for (None = any game type)
        game_index: Which matching game to parse (0 = first, 1 = second, etc.)
    """
    # Configure settings
    config.LOG_PATH = log_path
    config.MAP_PATH = map_path
    config.ICON_DIR = icon_dir
    config.VIDEO_OUTPUT = output_path
    config.WORLD_EXTENT = world_extent
    config.TEST_MODE = test_mode
    config.GAMETYPE_FILTER = gametype_filter
    config.GAME_INDEX = game_index
    config.SRPL_PATH = srpl_path
    config.set_resolution(resolution)

    # Also set in icon_config
    import icon_config
    icon_config.ICON_DIR = icon_dir

    print(f"Processing replay:")
    print(f"  Log: {log_path}")
    print(f"  Map: {map_path}")
    print(f"  Output: {output_path}")
    print(f"  Resolution: {resolution}")
    print(f"  World extent: {world_extent}")
    if srpl_path:
        print(f"  SRPL: {srpl_path}")
    print()
    
    # Run video generation
    make_video()


def make_video():
    """Main video creation function with stats tracking."""
    # Import settings from config module
    import config
    from icon_config import preload_all_icons
    
    # Initialize timing
    timing = TimingStats()
    timing.start('total')
    
    # === PHASE 0: Init Asset Pack & Preload Icons ===
    try:
        init_asset_pack()  # Auto-detects assets.pak location
    except FileNotFoundError:
        print("[WARN] assets.pak not found, falling back to raw Asset files")
    
    print("Preloading icons into RAM...")
    preload_all_icons(config.ICON_DIR)
    
    # === PHASE 1: Log Parsing ===
    timing.start('log_parsing')
    game_index = getattr(config, 'GAME_INDEX', 0)
    buildings, kills, deaths, commanders, team_tech_events, resources, victory_info, t_start, t_end, game_info, chat_messages, resource_status_events = \
        parse_buildings_and_kills_from_log(config.LOG_PATH, config.GAMETYPE_FILTER, game_index)
    timing.stop('log_parsing')

    # === PHASE 1b: SRPL Loading (optional) ===
    srpl_replay = None
    srpl_path = getattr(config, 'SRPL_PATH', None)
    if srpl_path:
        try:
            from srpl_reader import parse_srpl
            print(f"Loading SRPL: {srpl_path}")
            srpl_replay = parse_srpl(srpl_path)
            print(f"  Entities: {len(srpl_replay.entities)}, Ticks: {len(srpl_replay.ticks)}, "
                  f"Duration: {srpl_replay.duration_seconds:.0f}s, Players: {len(srpl_replay.players)}")
        except Exception as e:
            print(f"[WARN] Failed to load SRPL: {e}")
            srpl_replay = None

    # === PHASE 2: Statistics Building ===
    timing.start('stats_building')
    print("Building team statistics...")
    kill_stats, building_stats = build_all_stats_from_log(buildings, kills, team_tech_events=team_tech_events)
    print(f"Kill stats built for teams: {list(kill_stats.keys())}")
    print(f"Building stats built for teams: {list(building_stats.keys())}")

    # If SRPL data available, rebuild kill_stats from ALL destructions (including AI vs AI)
    # The log-based kills list is kept for the killbar (player-related kills only)
    if srpl_replay:
        kill_stats = build_kill_stats_from_srpl(srpl_replay)
        total_kills = sum(s.killed_units + s.killed_buildings for s in kill_stats.values())
        print(f"Kill stats rebuilt from SRPL: {total_kills} total kills (all, incl. AI vs AI)")
    
    # Build player statistics
    print("Building player statistics...")
    player_stats = build_player_stats_from_kills(kills)
    
    # Add death events to player stats
    for death in deaths:
        if death.player_name in player_stats:
            player = player_stats[death.player_name]
            player.total_deaths += 1
            if death.death_type == "suicide":
                player.suicide_deaths += 1
            player.death_events.append(death)
    
    # Build unit kill statistics
    unit_kill_stats = build_unit_kill_stats(kills)

    # Build resource stats for graph 2
    resource_stats = build_resource_stats_from_log(resource_status_events)

    print(f"Player stats built for {len(player_stats)} players")
    print(f"Unit kill stats: {len(unit_kill_stats)} unit types tracked")
    print(f"Resources parsed: {len(resources)}")
    print(f"Resource stats built for teams: {list(resource_stats.keys())}")
    if victory_info:
        print(f"Victory info: {victory_info.end_type}" + (f" - {victory_info.winning_team}" if victory_info.winning_team else ""))
    timing.stop('stats_building')
    
    # Print some debug info
    for team, stats in building_stats.items():
        if stats.timeline:
            final = stats.timeline[-1]
            print(f"  {team}: HQs {final[1]}/{final[2]}, Refs {final[3]}/{final[4]}, Tech Lvl {final[9]}")
    
    # === PHASE 3: Map Loading ===
    timing.start('map_loading')
    
    # Extract map name from path (for cleanlog overlay)
    map_name = os.path.splitext(os.path.basename(config.MAP_PATH))[0]
    base_map = load_map(map_name, map_path=config.MAP_PATH)
    orig_w, orig_h = base_map.size
    
    # Get date/time info from game_info (parsed from log)
    log_date = None
    log_time = None
    if game_info.get('date'):
        log_date = game_info['date']
    if game_info.get('time'):
        log_time = game_info['time']
    
    # Build display string for map info overlay
    map_info_display = None
    if log_date or log_time:
        parts = []
        if log_date:
            parts.append(log_date)
        if log_time:
            parts.append(log_time)
        map_info_display = " ".join(parts)
    
    # Auto-generate filename (with date + map + gametype) if we have game info
    # Works for both cleanlog and latestlog formats
    auto_generate_filename = getattr(config, 'AUTO_GENERATE_FILENAME', True)
    
    if auto_generate_filename and game_info.get('gametype_short'):
        gametype_short = game_info.get('gametype_short', 'Game')
        
        # Get date string - either from game_info or generate from current date
        if game_info.get('date'):
            # Parse date from DD/MM/YYYY to YYYY-MM-DD format for filename
            date_parts = game_info['date'].split('/')
            if len(date_parts) == 3:
                day, month, year = date_parts
                date_str = f"{year}-{month}-{day}"
            else:
                date_str = game_info['date'].replace('/', '-')
        else:
            # No date in log - use current date
            from datetime import datetime
            date_str = datetime.now().strftime("%Y-%m-%d")
        
        # Check if we need to auto-generate the output filename
        current_output = config.VIDEO_OUTPUT
        output_dir = os.path.dirname(current_output)
        output_ext = os.path.splitext(current_output)[1]
        current_basename = os.path.basename(current_output)
        
        # Generate new filename: YYYY-MM-DD_MapName_GameType.mp4
        new_filename = f"{date_str}_{map_name}_{gametype_short}{output_ext}"
        new_output_path = os.path.join(output_dir, new_filename) if output_dir else new_filename
        
        # Only update if the user hasn't explicitly disabled auto-naming
        # or if the current filename looks generic
        generic_names = ['output.mp4', 'replay.mp4', 'video.mp4']
        is_generic = current_basename.lower() in generic_names
        
        # Also consider it generic if it doesn't start with a date pattern
        import re
        has_date_prefix = bool(re.match(r'^\d{4}-\d{2}-\d{2}', current_basename))
        
        if is_generic or not has_date_prefix:
            config.VIDEO_OUTPUT = new_output_path
            print(f"Auto-generated output filename: {new_filename}")
    
    # Scale map to match resolution - ensure integer dimensions
    target_size = config.MAP_SIZE
    if orig_w != target_size or orig_h != target_size:
        base_map = base_map.resize((int(target_size), int(target_size)), resample=Image.BICUBIC)
        print(f"Scaled map from {orig_w}x{orig_h} to {base_map.size[0]}x{base_map.size[1]}")
    timing.stop('map_loading')
    
    if t_end <= t_start:
        print("Game duration is zero or negative; nothing to render.")
        return
    
    start_sec = math.ceil(t_start)
    end_sec = math.floor(t_end)
    frame_times_all = list(range(start_sec, end_sec + 1))
    frame_times = frame_times_all[::max(1, config.FRAME_STEP)]
    
    # TEST MODE: Limit frames
    if config.TEST_MODE:
        frame_times = frame_times[:config.TEST_RENDER_FRAMES]
        print(f"[TEST MODE] Rendering only first {len(frame_times)} frames")
    
    print(f"Rendering {len(frame_times)} frames (game time {start_sec}s..{end_sec}s, step={config.FRAME_STEP}s).")
    print(f"Video resolution: {config.VIDEO_WIDTH}x{config.VIDEO_HEIGHT} ({config.VIDEO_RESOLUTION})")
    print(f"Writing video to: {config.VIDEO_OUTPUT}")
    
    # Optional static heatmap
    if config.HEATMAP_OUTPUT:
        make_heatmap_image(base_map, kills, config.WORLD_EXTENT, config.HEATMAP_OUTPUT)
    
    # === PHASE 4: Video Initialization ===
    timing.start('video_init')
    writer = imageio.get_writer(config.VIDEO_OUTPUT, fps=config.VIDEO_FPS)
    
    # Precompute dynamic heat structures
    w, h = base_map.size
    heat = np.zeros((h, w), dtype=np.float32)
    
    R = int(config.KILL_HEAT_RADIUS)
    yy, xx = np.ogrid[-R:R+1, -R:R+1]
    disk = (xx * xx + yy * yy <= R * R).astype(np.float32)
    
    kills_sorted = sorted(kills, key=lambda ev: ev.time)
    ki = 0
    cancelled = False
    frame_num = 0  # Frame counter for caching
    timing.stop('video_init')
    
    # Clear render cache for new video
    from renderer import clear_render_cache
    clear_render_cache()
    
    # Initialize last frame for freeze effect
    last_frame_rgb = None
    
    # === PHASE 5: Frame Rendering ===
    timing.start('frame_rendering')
    
    try:
        for t in tqdm(frame_times, desc="Rendering frames"):
            # --- Heat accumulation timing ---
            heat_start = time.perf_counter()
            
            # Accumulate new kills
            while ki < len(kills_sorted) and kills_sorted[ki].time <= t:
                ev = kills_sorted[ki]
                px, py = world_to_pixel(ev.x, ev.y, w, h, config.WORLD_EXTENT)
                
                if px < -R or px >= w + R or py < -R or py >= h + R:
                    ki += 1
                    continue
                
                x0 = max(0, px - R)
                x1 = min(w, px + R + 1)
                y0 = max(0, py - R)
                y1 = min(h, py + R + 1)
                
                kx0 = x0 - (px - R)
                ky0 = y0 - (py - R)
                kx1 = kx0 + (x1 - x0)
                ky1 = ky0 + (y1 - y0)
                
                heat[y0:y1, x0:x1] += disk[ky0:ky1, kx0:kx1]
                ki += 1
            
            # Create heat overlay
            if config.KILL_HEAT_OVERLAY_ENABLED and heat.max() > 0:
                raw_max = float(heat.max())
                max_val = raw_max * (1.0 - config.HEATMAP_MAX_CLIP_PERCENT)
                max_val = max(max_val, 1.0)
                
                norm = heat / max_val
                norm = np.clip(norm, 0.0, 1.0)
                
                if config.HEATMAP_MODE == "gamma":
                    norm = np.power(norm, config.HEATMAP_GAMMA)
                elif config.HEATMAP_MODE == "log":
                    norm = np.log1p(norm * 9.0) / np.log1p(9.0)
                
                cmap = matplotlib.cm.get_cmap(config.KILL_HEAT_COLOR_MAP)
                rgba = cmap(norm)
                rgba = (rgba * 255).astype(np.uint8)
                
                alpha = (norm * config.KILL_HEAT_ALPHA * 255).astype(np.uint8)
                rgba[..., 3] = alpha
                
                heat_overlay = Image.fromarray(rgba, mode="RGBA")
            else:
                heat_overlay = None
            
            heat_time = time.perf_counter() - heat_start
            
            # --- Frame rendering timing ---
            render_start = time.perf_counter()
            render_detail = {}  # Collect detailed timing from render_frame
            
            # Get unit positions from SRPL if available
            srpl_units = None
            dying_eids = None
            if srpl_replay:
                game_t = float(t) - t_start  # Convert absolute time to game-relative time
                destroyed = srpl_replay.get_destroyed_before(game_t)
                all_pos = srpl_replay.get_positions_at_time(game_t)

                # Find units dying on this tick (destroyed between prev frame and now)
                prev_game_t = game_t - config.FRAME_STEP
                if prev_game_t >= 0:
                    prev_destroyed = srpl_replay.get_destroyed_before(prev_game_t)
                    dying_eids = destroyed - prev_destroyed  # Newly destroyed this frame
                else:
                    prev_destroyed = set()
                    dying_eids = None

                # Include alive units + dying units (for death flash), exclude already-dead
                srpl_units = [p for p in all_pos
                              if p["entity_id"] not in destroyed or p["entity_id"] in (dying_eids or set())]

            frame = render_frame(
                base_map,
                buildings,
                kills,
                kill_stats,
                building_stats,
                player_stats,
                unit_kill_stats,
                commanders,
                float(t),
                heat_overlay_rgba=heat_overlay,
                world_extent=config.WORLD_EXTENT,
                timing_detail=render_detail,
                frame_num=frame_num,
                resources=resources,
                victory_info=victory_info,
                t_end=t_end,
                total_frames=len(frame_times),
                map_name=map_name,
                log_date=map_info_display,  # Contains date + time for display
                chat_messages=chat_messages,
                resource_stats=resource_stats,
                unit_positions=srpl_units,
                dying_units=dying_eids,
            )
            
            frame_num += 1  # Increment frame counter
            render_time = time.perf_counter() - render_start
            
            # --- Video writing timing ---
            write_start = time.perf_counter()
            writer.append_data(np.array(frame.convert("RGB")))
            write_time = time.perf_counter() - write_start
            
            # Record frame timing with detailed breakdown
            timing.record_frame(heat_time, render_time, write_time, render_detail)
            
            # Store last frame for freeze effect
            last_frame_rgb = np.array(frame.convert("RGB"))
        
        # === FREEZE LAST FRAME ===
        freeze_frame_count = getattr(config, 'FREEZE_LAST_FRAME_COUNT', 30)
        if freeze_frame_count > 0 and last_frame_rgb is not None:
            print(f"\nFreezing last frame ({freeze_frame_count} frames)...")
            for _ in range(freeze_frame_count):
                writer.append_data(last_frame_rgb)
        
        # === SCOREBOARD RENDERING ===
        scoreboard_enabled = getattr(config, 'SCOREBOARD_ENABLED', True)
        scoreboard_frames = getattr(config, 'SCOREBOARD_FRAMES', 450)
        
        if scoreboard_enabled and scoreboard_frames > 0:
            print(f"\nRendering scoreboard ({scoreboard_frames} frames)...")
            
            from renderer import render_scoreboard
            
            # Create scoreboard image once (it's static)
            scoreboard_img = render_scoreboard(
                player_stats,
                kill_stats,
                config.VIDEO_WIDTH,
                config.VIDEO_HEIGHT,
                victory_info=victory_info
            )
            scoreboard_rgb = np.array(scoreboard_img.convert("RGB"))
            
            # Write scoreboard frames
            for _ in tqdm(range(scoreboard_frames), desc="Scoreboard frames"):
                writer.append_data(scoreboard_rgb)
            
            print(f"Scoreboard added: {scoreboard_frames} frames ({scoreboard_frames / config.VIDEO_FPS:.1f}s)")
                
    except KeyboardInterrupt:
        print("\n\n" + chr(0x26A0) + chr(0xFE0F) + "  Rendering cancelled by user (Ctrl+C)")
        cancelled = True
    finally:
        writer.close()
        timing.stop('frame_rendering')
        timing.stop('total')
    
    # Print cache statistics
    from renderer import get_render_cache
    get_render_cache().print_stats()
    
    if cancelled:
        print(f"Partial video saved to: {config.VIDEO_OUTPUT}")
        print("Note: Video may be incomplete.")
        timing.print_summary()
        return False
    
    print("Video rendering done.")
    if MISSING_ICON_TYPES:
        print("These unit types had no matching icons (normalized names):")
        for name in sorted(MISSING_ICON_TYPES):
            print("  -", name)
    
    # Print timing summary
    timing.print_summary()
    
    return True




if __name__ == "__main__":
    print("Replay_Main.py - Modular Replay Generator")
    print()
    print("Usage:")
    print("  from Replay_Main import process_replay")
    print("  process_replay('game.log', 'map.png', 'icons/', 'output.mp4')")
    print()
    print("Or use with MapReplay_MultiGame_Launcher.py for automatic processing.")
