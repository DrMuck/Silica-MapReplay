# -*- coding: utf-8 -*-
"""
MapReplay Live Service - Real-time game replay generation for Silica Dedicated Server

This service monitors the game log files and generates map replays on-the-fly
as games are being played. It runs as a background process with CPU affinity
set to avoid interfering with the game server.

Features:
- Monitors UserData/logs/ for new log entries
- Handles midnight log file rollover (L20251214.log -> L20251215.log)
- Generates video frames incrementally as events occur
- CPU core affinity to avoid game server's primary core
- Automatic game detection and replay finalization

Usage:
    python MapReplay_Service.py [--config config.py] [--daemon]

Author: MapReplay System
Version: 1.0.0
"""

import os
import sys
import time
import glob
import signal
import logging
import argparse
import threading
import multiprocessing
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
from typing import Optional, Dict, List, Tuple, Any

# Add modules directory to path
SCRIPT_DIR = Path(__file__).parent.resolve()
MODULES_DIR = SCRIPT_DIR / "modules"
sys.path.insert(0, str(MODULES_DIR))

# Attempt to import psutil for CPU affinity (optional)
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    print("Warning: psutil not installed. CPU affinity control disabled.")
    print("Install with: pip install psutil")

# Import modules (after path is set up)
import numpy as np
import config as cfg
from data_models import Building, KillEvent, DeathEvent, VictoryInfo, Resource, ChatMessage, ResourceStatusEvent
from statistics import build_all_stats_from_log, build_player_stats_from_kills, build_resource_stats_from_log, build_kill_stats_from_srpl
from srpl_reader import LiveSrplReader
from renderer import render_frame, render_scoreboard, clear_render_cache
import gc  # For garbage collection

# Asset pack support
try:
    from asset_loader import init_asset_pack
    from map_loader import load_map
    _HAS_ASSET_PACK = True
except ImportError:
    _HAS_ASSET_PACK = False


# ============================================================
# CONFIGURATION
# ============================================================

class LiveConfig:
    """Configuration for live replay service."""
    
    # Paths (relative to Silica Dedicated Server root)
    SERVER_ROOT = Path(__file__).parent.parent.resolve()  # Go up from Mod MapReplay
    LOG_DIR = SERVER_ROOT / "UserData" / "logs"
    ASSETS_DIR = SCRIPT_DIR / "Assets"
    MAPS_DIR = ASSETS_DIR / "Maps"
    ICONS_DIR = ASSETS_DIR / "Silica_Icons"
    OUTPUT_DIR = SCRIPT_DIR / "Replays"
    
    # Log file pattern
    LOG_PATTERN = "L*.log"  # Matches L20251214.log
    
    # Load settings from live_config.py
    @classmethod
    def load_from_file(cls):
        """Load configuration from live_config.py file."""
        config_path = SCRIPT_DIR / "live_config.py"
        if config_path.exists():
            import importlib.util
            spec = importlib.util.spec_from_file_location("live_config", config_path)
            live_cfg = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(live_cfg)
            
            # Video resolution
            cls.VIDEO_RESOLUTION = getattr(live_cfg, 'VIDEO_RESOLUTION', '1440p')
            
            # CPU settings
            cls.AVOID_CORES = getattr(live_cfg, 'AVOID_CORES', [0])
            
            # Monitoring settings
            cls.POLL_INTERVAL = getattr(live_cfg, 'POLL_INTERVAL', 0.5)
            cls.LINE_BATCH_SIZE = getattr(live_cfg, 'LINE_BATCH_SIZE', 100)
            
            # Game detection
            cls.MIN_GAME_DURATION = getattr(live_cfg, 'MIN_GAME_DURATION', 600)
            cls.GAME_END_TIMEOUT = getattr(live_cfg, 'GAME_END_TIMEOUT', 60)
            cls.DISABLE_TIMEOUT_END = getattr(live_cfg, 'DISABLE_TIMEOUT_END', False)
            cls.SUPPRESS_CHAT_COMMANDS = getattr(live_cfg, 'SUPPRESS_CHAT_COMMANDS', True)

            # File splitting
            cls.MAX_FILE_SIZE_MB = getattr(live_cfg, 'MAX_FILE_SIZE_MB', 24)
            cls.FILE_SIZE_CHECK_INTERVAL = getattr(live_cfg, 'FILE_SIZE_CHECK_INTERVAL', 100)
            
            # Discord settings
            cls.DISCORD_WEBHOOK_ENABLED = getattr(live_cfg, 'DISCORD_WEBHOOK_ENABLED', False)
            cls.DISCORD_WEBHOOK_URL = getattr(live_cfg, 'DISCORD_WEBHOOK_URL', "")
            cls.DISCORD_UPLOAD_TIMEOUT = getattr(live_cfg, 'DISCORD_UPLOAD_TIMEOUT', 300)
            cls.DISCORD_RETRY_ATTEMPTS = getattr(live_cfg, 'DISCORD_RETRY_ATTEMPTS', 3)
            cls.SERVER_NAME = getattr(live_cfg, 'SERVER_NAME', "")
            if not cls.SERVER_NAME:
                cls.SERVER_NAME = cls._detect_server_name()
            else:
                cls.SERVER_NAME = cls._sanitize_server_name(cls.SERVER_NAME)

            # Memory optimization settings
            cls.VIDEO_BITRATE_KBPS = getattr(live_cfg, 'VIDEO_BITRATE_KBPS', 1900)
            cls.FFMPEG_PRESET = getattr(live_cfg, 'FFMPEG_PRESET', 'veryfast')
            cls.GC_INTERVAL_FRAMES = getattr(live_cfg, 'GC_INTERVAL_FRAMES', 50)
            cls.GRAPH_UPDATE_INTERVAL = getattr(live_cfg, 'GRAPH_UPDATE_INTERVAL', 10)
    
    # CPU Affinity - avoid these cores (typically core 0 for game server)
    AVOID_CORES = [0]  # List of CPU cores to avoid
    
    # Monitoring settings
    POLL_INTERVAL = 0.5  # Seconds between log file checks
    LINE_BATCH_SIZE = 100  # Process this many lines at once
    
    # Game detection
    MIN_GAME_DURATION = 600  # Minimum game duration in seconds (10 min)
    GAME_END_TIMEOUT = 30  # Seconds to wait after last event before finalizing
    DISABLE_TIMEOUT_END = False  # Disable timeout-based game ending (for emulator testing)
    SUPPRESS_CHAT_COMMANDS = True  # Suppress /b and /1-/30 chat commands from replay
    
    # Video settings
    VIDEO_RESOLUTION = "1440p"  # Options: "720p", "1080p", "1440p", "4k"
    VIDEO_FPS = 45
    FRAME_STEP = 1  # Sample every N seconds
    
    # File splitting settings
    MAX_FILE_SIZE_MB = 24  # Split video if file exceeds this size (Discord limit is 25MB)
    FILE_SIZE_CHECK_INTERVAL = 100  # Check file size every N frames
    
    # Discord webhook settings
    DISCORD_WEBHOOK_ENABLED = False
    DISCORD_WEBHOOK_URL = ""  # Set in live_config.py
    DISCORD_UPLOAD_TIMEOUT = 300  # Timeout for upload in seconds
    DISCORD_RETRY_ATTEMPTS = 3  # Number of retry attempts for failed uploads
    SERVER_NAME = ""  # Server name shown in Discord messages
    
    # Memory management
    MAX_PENDING_FRAMES = 1000  # Max frames to hold in memory before forcing write

    # Logging
    LOG_LEVEL = logging.INFO
    LOG_FILE = SCRIPT_DIR / "mapreplay_service.log"

    @classmethod
    def _detect_server_name(cls):
        """Auto-detect server name from ~/Documents/Silica/ServerSettings.xml."""
        try:
            import xml.etree.ElementTree as ET
            settings_path = Path.home() / "Documents" / "Silica" / "ServerSettings.xml"
            if settings_path.is_file():
                tree = ET.parse(settings_path)
                name = tree.getroot().get("ServerName", "")
                if name:
                    return cls._sanitize_server_name(name)
        except Exception:
            pass
        return ""

    @staticmethod
    def _sanitize_server_name(name):
        """Strip URLs from server name to avoid Discord link previews."""
        import re
        # Remove URLs (http/https/discord links etc.)
        name = re.sub(r'https?://\S+', '', name)
        # Clean up leftover separators and whitespace
        name = re.sub(r'[|\s]+$', '', name)
        name = re.sub(r'\|{2,}', '|', name)
        return name.strip()


# Load config from file at module load time
LiveConfig.load_from_file()


# ============================================================
# LOGGING SETUP
# ============================================================

def setup_logging(config: LiveConfig):
    """Setup logging for the service."""
    logging.basicConfig(
        level=config.LOG_LEVEL,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=[
            logging.FileHandler(config.LOG_FILE, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger("MapReplay")


# ============================================================
# DISCORD WEBHOOK UPLOADER
# ============================================================

class DiscordUploader:
    """Handles uploading replay videos to Discord via webhook."""
    
    def __init__(self, config: LiveConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger
    
    def upload_video(self, video_path: Path, map_name: str = "", gametype: str = "", 
                     duration_mins: float = 0, part_num: int = 0, total_parts: int = 1,
                     game_date: str = None, commanders: dict = None, victory_info = None) -> bool:
        """
        Upload a video file to Discord via webhook.
        
        Args:
            video_path: Path to the video file
            map_name: Name of the map
            gametype: Game type (HvH, HvHvA, etc.)
            duration_mins: Game duration in minutes
            part_num: Part number (0 for single file, 1+ for split files)
            total_parts: Total number of parts
            game_date: Date of the game (YYYY-MM-DD format)
            commanders: Dict of {team: [(time, player_name), ...]}
            victory_info: VictoryInfo namedtuple with winning team
        
        Returns:
            True if upload successful, False otherwise
        """
        if not self.config.DISCORD_WEBHOOK_ENABLED:
            return True
        
        webhook_url = self.config.DISCORD_WEBHOOK_URL
        if not webhook_url:
            self.logger.warning("Discord webhook URL not configured - skipping upload")
            return False
        
        if not video_path.exists():
            self.logger.error(f"Video file not found: {video_path}")
            return False
        
        file_size_mb = video_path.stat().st_size / (1024 * 1024)
        
        # Discord has 25MB limit for regular uploads, 100MB for boosted servers
        # We'll warn if over 25MB but still try
        if file_size_mb > 25:
            self.logger.warning(f"File size ({file_size_mb:.1f}MB) exceeds Discord's 25MB limit - upload may fail")
        
        # Discord emoji characters (using chr() to avoid file encoding issues)
        E_GAME = chr(0x1F3AE)     # game controller
        E_CAL = chr(0x1F4C5)      # calendar
        E_CROWN = chr(0x1F451)    # crown
        E_TROPHY = chr(0x1F3C6)   # trophy
        E_TIMER = chr(0x23F1) + chr(0xFE0F)  # timer
        E_CHART = chr(0x1F4CA)    # chart
        
        # Build message content
        server_prefix = f"[{self.config.SERVER_NAME}] " if self.config.SERVER_NAME else ""
        if part_num > 0:
            title = f"{E_GAME} {server_prefix}**{map_name}** - {gametype} (Part {part_num}/{total_parts})"
        else:
            title = f"{E_GAME} {server_prefix}**{map_name}** - {gametype}"
        
        # Add date if available
        date_str = ""
        if game_date:
            date_str = f"{E_CAL} {game_date} | "
        
        # Build commander info
        commander_str = ""
        if commanders:
            cmd_parts = []
            for team in ["Sol", "Centauri", "Alien"]:
                if team in commanders and commanders[team]:
                    # Get the last commander for this team
                    last_cmd = commanders[team][-1][1]  # (time, player_name)
                    cmd_parts.append(f"{team}: {last_cmd}")
            if cmd_parts:
                commander_str = f"\n{E_CROWN} " + " | ".join(cmd_parts)
        
        # Add victory info
        victory_str = ""
        if victory_info and victory_info.winning_team:
            victory_str = f"\n{E_TROPHY} **{victory_info.winning_team} Victory!**"
            if victory_info.commander:
                victory_str += f" (Commander: {victory_info.commander})"
        
        content = f"{title}\n{date_str}{E_TIMER} Duration: {duration_mins:.0f} minutes | {E_CHART} Size: {file_size_mb:.1f}MB{commander_str}{victory_str}"
        
        # Attempt upload with retries
        import urllib.request
        import urllib.error
        import json
        
        for attempt in range(self.config.DISCORD_RETRY_ATTEMPTS):
            try:
                self.logger.info(f"Uploading to Discord: {video_path.name} (attempt {attempt + 1})")
                
                # Create multipart form data
                boundary = '----WebKitFormBoundary' + os.urandom(16).hex()
                
                # Build the multipart body
                body_parts = []
                
                # Add content field (JSON payload)
                payload = {"content": content}
                body_parts.append(
                    f'--{boundary}\r\n'
                    f'Content-Disposition: form-data; name="payload_json"\r\n'
                    f'Content-Type: application/json\r\n\r\n'
                    f'{json.dumps(payload)}\r\n'
                )
                
                # Add file field
                body_parts.append(
                    f'--{boundary}\r\n'
                    f'Content-Disposition: form-data; name="file"; filename="{video_path.name}"\r\n'
                    f'Content-Type: video/mp4\r\n\r\n'
                )
                
                # Read file content
                with open(video_path, 'rb') as f:
                    file_content = f.read()
                
                # Combine parts
                body_start = ''.join(body_parts).encode('utf-8')
                body_end = f'\r\n--{boundary}--\r\n'.encode('utf-8')
                body = body_start + file_content + body_end
                
                # Create request
                req = urllib.request.Request(
                    webhook_url,
                    data=body,
                    headers={
                        'Content-Type': f'multipart/form-data; boundary={boundary}',
                        'User-Agent': 'MapReplay-Service/1.0'
                    }
                )
                
                # Send request
                with urllib.request.urlopen(req, timeout=self.config.DISCORD_UPLOAD_TIMEOUT) as response:
                    if response.status in (200, 204):
                        self.logger.info(f"Successfully uploaded to Discord: {video_path.name}")
                        return True
                    else:
                        self.logger.warning(f"Discord upload returned status {response.status}")
                        
            except urllib.error.HTTPError as e:
                self.logger.error(f"Discord upload failed (HTTP {e.code}): {e.reason}")
                if e.code == 413:
                    self.logger.error("File too large for Discord - consider lowering MAX_FILE_SIZE_MB")
                    return False  # Don't retry for size issues
            except urllib.error.URLError as e:
                self.logger.error(f"Discord upload failed (network error): {e.reason}")
            except Exception as e:
                self.logger.error(f"Discord upload failed: {e}")
            
            # Wait before retry
            if attempt < self.config.DISCORD_RETRY_ATTEMPTS - 1:
                import time
                time.sleep(5 * (attempt + 1))  # Exponential backoff
        
        self.logger.error(f"Failed to upload to Discord after {self.config.DISCORD_RETRY_ATTEMPTS} attempts")
        return False
    
    def upload_all_parts(self, video_paths: List[Path], map_name: str, gametype: str, 
                        duration_mins: float, game_date: str = None, 
                        commanders: dict = None, victory_info = None) -> bool:
        """Upload all parts of a split video."""
        total_parts = len(video_paths)
        all_success = True
        
        for i, path in enumerate(video_paths, 1):
            part_num = i if total_parts > 1 else 0
            success = self.upload_video(
                path, map_name, gametype, duration_mins, 
                part_num=part_num, total_parts=total_parts,
                game_date=game_date, commanders=commanders, victory_info=victory_info
            )
            if not success:
                all_success = False
        
        return all_success


# ============================================================
# CPU AFFINITY MANAGER
# ============================================================

class CPUAffinityManager:
    """Manages CPU core affinity to avoid interfering with game server."""
    
    def __init__(self, avoid_cores: List[int], logger: logging.Logger):
        self.avoid_cores = avoid_cores
        self.logger = logger
        self.original_affinity = None
    
    def set_affinity(self):
        """Set CPU affinity to avoid specified cores."""
        if not HAS_PSUTIL:
            self.logger.warning("psutil not available - cannot set CPU affinity")
            return False
        
        try:
            process = psutil.Process()
            self.original_affinity = process.cpu_affinity()
            
            # Get all available cores
            all_cores = list(range(psutil.cpu_count()))
            
            # Remove avoided cores
            allowed_cores = [c for c in all_cores if c not in self.avoid_cores]
            
            if not allowed_cores:
                self.logger.warning("No cores available after exclusion - using all cores")
                return False
            
            # Set affinity
            process.cpu_affinity(allowed_cores)
            self.logger.info(f"CPU affinity set to cores: {allowed_cores} (avoiding: {self.avoid_cores})")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to set CPU affinity: {e}")
            return False
    
    def restore_affinity(self):
        """Restore original CPU affinity."""
        if not HAS_PSUTIL or self.original_affinity is None:
            return
        
        try:
            process = psutil.Process()
            process.cpu_affinity(self.original_affinity)
            self.logger.info(f"CPU affinity restored to: {self.original_affinity}")
        except Exception as e:
            self.logger.error(f"Failed to restore CPU affinity: {e}")


# ============================================================
# LOG FILE WATCHER
# ============================================================

class LogFileWatcher:
    """Watches log directory for new files and new lines."""
    
    def __init__(self, log_dir: Path, pattern: str, logger: logging.Logger):
        self.log_dir = log_dir
        self.pattern = pattern
        self.logger = logger
        
        self.current_file: Optional[Path] = None
        self.file_handle: Optional[Any] = None
        self.file_position: int = 0
        self.last_check_time: float = 0
    
    def get_latest_log_file(self) -> Optional[Path]:
        """Find the most recent log file in the directory."""
        log_files = list(self.log_dir.glob(self.pattern))
        if not log_files:
            return None
        
        # Sort by modification time (most recent first)
        log_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        return log_files[0]
    
    def get_log_file_for_date(self, date: datetime) -> Path:
        """Get the expected log file path for a given date."""
        filename = f"L{date.strftime('%Y%m%d')}.log"
        return self.log_dir / filename
    
    def open_file(self, file_path: Path, from_end: bool = False):
        """Open a log file for reading."""
        self.close_file()
        
        try:
            self.file_handle = open(file_path, 'r', encoding='utf-8', errors='ignore')
            self.current_file = file_path
            
            if from_end:
                # Seek to end of file (for starting fresh)
                self.file_handle.seek(0, 2)  # SEEK_END
                self.file_position = self.file_handle.tell()
            else:
                self.file_position = 0
            
            self.logger.info(f"Opened log file: {file_path} (position: {self.file_position})")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to open log file {file_path}: {e}")
            return False
    
    def close_file(self):
        """Close the current log file."""
        if self.file_handle:
            try:
                self.file_handle.close()
            except:
                pass
            self.file_handle = None
            self.current_file = None
    
    def read_new_lines(self) -> List[str]:
        """Read any new lines from the current log file."""
        if not self.file_handle:
            return []
        
        try:
            # Check if file still exists and hasn't been truncated
            if self.current_file and self.current_file.exists():
                current_size = self.current_file.stat().st_size
                if current_size < self.file_position:
                    # File was truncated or rotated
                    self.logger.warning("Log file was truncated/rotated - reopening")
                    self.file_handle.seek(0)
                    self.file_position = 0
            
            # Read new lines
            new_lines = self.file_handle.readlines()
            self.file_position = self.file_handle.tell()
            
            return [line.rstrip('\r\n') for line in new_lines if line.strip()]
            
        except Exception as e:
            self.logger.error(f"Error reading log file: {e}")
            return []
    
    def check_for_new_file(self) -> bool:
        """Check if a new log file should be opened (midnight rollover)."""
        latest = self.get_latest_log_file()
        
        if latest and latest != self.current_file:
            self.logger.info(f"New log file detected: {latest}")
            return self.open_file(latest, from_end=False)
        
        return False
    
    def check_for_log_closed(self, line: str) -> bool:
        """Check if the current log file is being closed (midnight)."""
        # Look for: L 12/12/2025 - 00:00:00: Log file closed
        return "Log file closed" in line


# ============================================================
# LIVE GAME STATE
# ============================================================

class LiveGameState:
    """Tracks the state of a game being played in real-time."""
    
    def __init__(self, map_name: str, gametype: str, start_time: float):
        self.map_name = map_name
        self.gametype = gametype
        self.start_time = start_time  # Absolute time from log
        self.game_time = 0.0  # Relative game time
        
        # Date tracking (extracted from log)
        self.log_date = None  # Format: "DD/MM" (for backwards compatibility)
        self.full_date = None  # Format: "YYYY-MM-DD" (for Discord)
        self.game_datetime = None  # Format: "YYYY/MM/DD - HH:MM" (for display and filename)
        
        # Data structures (same as offline parser)
        self.buildings = {}
        self.kills = []
        self.deaths = []
        self.commanders = {}
        self.resources = {}
        self.team_tech_events = defaultdict(list)
        self.chat_messages = []  # Chat messages from players
        self.resource_status_events = []  # ResourceStatusEvent list for graph 2

        # Tracking
        self.kill_counter = 0
        self.last_event_time = start_time
        self.victory_info = None
        self.is_ended = False
        
        # Frame generation
        self.last_frame_time = 0.0
        self.frames_generated = 0

        # Wall-clock Unix time when game was detected (for SRPL time sync)
        self._start_unix = 0.0
    
    def get_relative_time(self, abs_time: float) -> float:
        """Convert absolute log time to relative game time."""
        return abs_time - self.start_time
    
    def update_last_event(self, abs_time: float):
        """Update the last event timestamp."""
        self.last_event_time = abs_time
        self.game_time = self.get_relative_time(abs_time)


# ============================================================
# LIVE LOG PARSER
# ============================================================

class LiveLogParser:
    """Parses log lines incrementally for real-time processing."""
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.current_game: Optional[LiveGameState] = None
        self.completed_games: List[LiveGameState] = []
        
        # Time tracking for midnight rollover
        self.last_raw_time: Optional[float] = None
        self.time_offset = 0
        
        # Compile regex patterns once
        self._compile_patterns()
    
    def _compile_patterns(self):
        """Compile regex patterns for log parsing."""
        import re
        
        # Time extraction - support both formats
        # Standard format: [HH:MM:SS.mmm]
        self.re_time_standard = re.compile(r'\[(\d{2}):(\d{2}):(\d{2})\.(\d{3})\]')
        # Cleanlog format: L MM/DD/YYYY - HH:MM:SS:
        self.re_time_cleanlog = re.compile(r'L \d{2}/\d{2}/\d{4} - (\d{2}):(\d{2}):(\d{2}):')
        
        # Game events
        self.re_round_start = re.compile(
            r'World triggered "Round_Start" \(gamemode "MP_Strategy"\) \(gametype "([^"]+)"\)'
        )
        self.re_round_win = re.compile(r'World triggered "Round_Win"(?:.*\(gametype "(?P<gametype>[^"]+)"\))?')
        self.re_victory = re.compile(r'Team "(?P<team>[^"]+)" triggered "Victory"')
        self.re_loading_map = re.compile(r'Loading map "(?P<map>[^"]+)"')
        self.re_queued_map = re.compile(r'Queued map:\s*(?P<map>\S+)|Queued map: (?P<map2>\S+)')
        
        # Construction events
        self.re_construction = re.compile(
            r'Team "([^"]+)" triggered "construction_(start|complete)" '
            r'\(building_name "([^"]+)"\) \(building_position "([^"]+)"\)'
        )
        self.re_structure_sold = re.compile(
            r'Team "([^"]+)" triggered "structure_sold" '
            r'\(building_name "([^"]+)"\) \(building_position "([^"]+)"\)'
        )
        
        # Kill events
        # Updated regex to capture attacker_position for structure kills
        self.re_struct_kill = re.compile(
            r'"(?P<att_name>[^"<]+)<[^>]*><[^>]*><(?P<att_team>[^">]*)>" triggered "structure_kill" '
            r'\(structure "(?P<structure>[^"]+)"\) '
            r'\(weapon "(?P<weapon>[^"]+)"\) '
            r'\(struct_team "(?P<struct_team>[^"]*)"\).*?'
            r'\(attacker_position "(?P<att_pos>[^"]+)"\) '
            r'\(building_position "(?P<bld_pos>[^"]+)"\)'
        )
        self.re_unit_kill = re.compile(
            r'"(?P<att_name>[^"<]+)<[^>]*><[^>]*><(?P<att_team>[^">]*)>" '
            r'killed "(?P<v_name>[^"<]+)<[^>]*><[^>]*><(?P<v_team>[^">]*)>" '
            r'with "(?P<weapon>[^"]+)" \(dmgtype "[^"]*"\) '
            r'\(victim "(?P<victim_unit>[^"]+)"\) '
            r'\(attacker_position "(?P<att_pos>[^"]+)"\) '
            r'\(victim_position "(?P<v_pos>[^"]+)"\)'
        )
        self.re_suicide = re.compile(
            r'"(?P<player_name>[^"<]+)<[^>]*><[^>]*><(?P<team>[^">]*)>" '
            r'committed suicide'
        )
        
        # Other events
        self.re_commander = re.compile(
            r'"(?P<player_name>[^"<]+)<[^>]*><[^>]*><(?P<team>[^">]*)>" '
            r'changed role to "Commander"'
        )
        self.re_tech_change = re.compile(
            r'Team "(?P<team>[^"]+)" triggered "technology_change" \(tier "(?P<tier>\d+)"\)'
        )
        self.re_weapon = re.compile(r'\(weapon "([^"]+)"\)')
        
        # Resource events
        self.re_resource_spawned = re.compile(
            r'World triggered "Resource_Spawned" \(type "(?P<type>[^"]+)"\) '
            r'\(amount "(?P<amount>\d+)"\) \(position "(?P<pos>[^"]+)"\)'
        )
        self.re_resource_depleted = re.compile(
            r'World triggered "Resource_Depleted" \(type "(?P<type>[^"]+)"\) '
            r'\(position "(?P<pos>[^"]+)"\)'
        )
        self.re_resource_status = re.compile(
            r'Team "(?P<team>[^"]+)" triggered "resource_status" '
            r'\(collected "(?P<collected>\d+)"\) \(spent "(?P<spent>\d+)"\)'
        )

        # Chat events - "PlayerName<id><steamid><Team>" say "message" or say_team "message"
        self.re_chat_say = re.compile(
            r'"(?P<player_name>[^"<]+)<[^>]*><[^>]*><(?P<team>[^">]*)>"\s+say\s+"(?P<message>.+)"'
        )
        self.re_chat_say_team = re.compile(
            r'"(?P<player_name>[^"<]+)<[^>]*><[^>]*><(?P<team>[^">]*)>"\s+say_team\s+"(?P<message>.+)"'
        )
        # Chat command filter (balance UI commands: /b, /1 through /30)
        self.re_chat_command = re.compile(r'^/b\b|^/([12]?\d|30)\b')

        # Date extraction for cleanlog format
        self.re_date_cleanlog = re.compile(r'L (\d{2})/(\d{2})/(\d{4}) -')
    
    def parse_time(self, line: str) -> Optional[float]:
        """Extract timestamp from log line and handle midnight rollover."""
        # Try standard format first: [HH:MM:SS.mmm]
        m = self.re_time_standard.search(line)
        if m:
            h, mi, s, ms = map(int, m.groups())
            raw_time = h * 3600 + mi * 60 + s + ms / 1000.0
        else:
            # Try cleanlog format: L MM/DD/YYYY - HH:MM:SS:
            m = self.re_time_cleanlog.search(line)
            if m:
                h, mi, s = map(int, m.groups())
                raw_time = h * 3600 + mi * 60 + s
            else:
                return None
        
        # Handle midnight rollover
        if self.last_raw_time is not None:
            if raw_time < self.last_raw_time - 3600:  # More than 1 hour backwards
                self.time_offset += 86400
                self.logger.info(f"Midnight rollover detected (offset now: {self.time_offset}s)")
        
        self.last_raw_time = raw_time
        return raw_time + self.time_offset
    
    def extract_date(self, line: str) -> Optional[str]:
        """Extract date from cleanlog format line. Returns 'DD/MM' or None."""
        m = self.re_date_cleanlog.search(line)
        if m:
            month, day, year = m.groups()
            return f"{day}/{month}"  # Return as DD/MM
        return None
    
    def extract_full_date(self, line: str) -> Optional[str]:
        """Extract full date from cleanlog format line. Returns 'YYYY-MM-DD' or None."""
        m = self.re_date_cleanlog.search(line)
        if m:
            month, day, year = m.groups()
            return f"{year}-{month}-{day}"  # Return as YYYY-MM-DD
        return None
    
    def extract_full_datetime(self, line: str) -> Optional[Tuple[str, str]]:
        """
        Extract full date and time from cleanlog format line.
        
        Returns:
            Tuple of (date_str, time_str) where:
            - date_str is "YYYY/MM/DD" format
            - time_str is "HH:MM" format
            Or None if not found.
        """
        # Check for cleanlog format: L MM/DD/YYYY - HH:MM:SS:
        m_date = self.re_date_cleanlog.search(line)
        m_time = self.re_time_cleanlog.search(line)
        
        if m_date and m_time:
            month, day, year = m_date.groups()
            h, mi, s = m_time.groups()
            date_str = f"{year}/{month}/{day}"  # YYYY/MM/DD
            time_str = f"{h}:{mi}"  # HH:MM
            return (date_str, time_str)
        
        # Try standard format (date from filename or current date)
        m_time_std = self.re_time_standard.search(line)
        if m_time_std:
            h, mi, s, ms = m_time_std.groups()
            time_str = f"{h}:{mi}"  # HH:MM
            # No date in standard format, use current date as fallback
            from datetime import datetime
            date_str = datetime.now().strftime("%Y/%m/%d")
            return (date_str, time_str)
        
        return None
    
    def parse_position(self, pos_str: str) -> Optional[Tuple[float, float, float]]:
        """Parse position string into coordinates."""
        try:
            parts = pos_str.split()
            return float(parts[0]), float(parts[1]), float(parts[2]) if len(parts) > 2 else 0
        except:
            return None
    
    def process_line(self, line: str) -> Optional[str]:
        """
        Process a single log line.
        
        Returns:
            - "game_start" if a new game started
            - "game_end" if the game ended
            - "event" if a game event was processed
            - None if nothing relevant
        """
        t_abs = self.parse_time(line)
        if t_abs is None:
            return None
        
        # Check for map loading (can happen before Round_Start)
        m_map = self.re_loading_map.search(line)
        if m_map:
            map_name = m_map.group('map')
            self._pending_map_name = map_name  # Store for next game
            self._last_known_map = map_name    # Remember for consecutive games
            self.logger.info(f"Loading map detected: {map_name}")
            
            # If a game is running and we're loading a DIFFERENT map, end the current game
            if self.current_game and not self.current_game.is_ended:
                if self.current_game.map_name != map_name and self.current_game.map_name != "Unknown":
                    self.logger.info(f"Map change detected ({self.current_game.map_name} -> {map_name}), ending current game")
                    self.current_game.is_ended = True
                    self.current_game.game_time = self.current_game.get_relative_time(t_abs)
                    self.completed_games.append(self.current_game)
                    return "game_end"
            
            if self.current_game and self.current_game.map_name == "Unknown":
                self.current_game.map_name = map_name
                self.logger.info(f"Map identified for current game: {map_name}")
        
        # Check for game start (Round_Start or auto-detect from first gameplay event)
        m_start = self.re_round_start.search(line)
        is_gameplay_event = (not self.current_game or self.current_game.is_ended) and \
            getattr(self, '_pending_map_name', None) and \
            (self.re_construction.search(line) or self.re_resource_status.search(line) or
             self.re_struct_kill.search(line))

        if m_start or is_gameplay_event:
            if m_start:
                gametype = m_start.group(1)
            else:
                # Auto-detect: no Round_Start, infer gametype later from Round_Win
                gametype = "HUMANS_VS_HUMANS_VS_ALIENS"  # default, updated on Round_Win
                self.logger.info(f"Auto-detecting game start (no Round_Start event)")

            # End current game if one is running - remember its map name!
            previous_map = None
            if self.current_game and not self.current_game.is_ended:
                previous_map = self.current_game.map_name
                self.current_game.is_ended = True
                self.current_game.game_time = self.current_game.get_relative_time(t_abs)
                self.completed_games.append(self.current_game)
                self.logger.info(f"Previous game force-ended (new game detected)")

            # Use pending map name if available
            # Otherwise use previous game's map (for consecutive games on same map)
            # Otherwise "Unknown"
            map_name = getattr(self, '_pending_map_name', None)
            if not map_name:
                # No Loading map event - maybe same map as before?
                if previous_map and previous_map != "Unknown":
                    map_name = previous_map
                    self.logger.info(f"No Loading map event - assuming same map: {map_name}")
                else:
                    # Check if we have a last known map
                    map_name = getattr(self, '_last_known_map', 'Unknown')
                    if map_name != 'Unknown':
                        self.logger.info(f"Using last known map: {map_name}")

            # Remember this map for future games
            if map_name and map_name != "Unknown":
                self._last_known_map = map_name

            self._pending_map_name = None  # Clear for next game

            self.current_game = LiveGameState(map_name, gametype, t_abs)
            self.current_game._start_unix = time.time()

            # Extract date from log line
            log_date = self.extract_date(line)
            if log_date:
                self.current_game.log_date = log_date

            # Also store full date for Discord message
            full_date = self.extract_full_date(line)
            if full_date:
                self.current_game.full_date = full_date

            # Extract full datetime for display and filename (YYYY/MM/DD - HH:MM)
            datetime_info = self.extract_full_datetime(line)
            if datetime_info:
                date_str, time_str = datetime_info
                self.current_game.game_datetime = f"{date_str} - {time_str}"
                # Also store components for filename
                self.current_game.game_date_for_filename = date_str.replace("/", "-")  # YYYY-MM-DD
                self.current_game.game_time_for_filename = time_str.replace(":", "")   # HHMM

            self.logger.info(f"=== GAME STARTED === Map: {map_name}, Type: {gametype}, t={t_abs:.1f}s, Date: {self.current_game.game_datetime or log_date}")
            return "game_start"
        
        # If no active game, skip event processing
        if not self.current_game or self.current_game.is_ended:
            return None
        
        game = self.current_game
        t = game.get_relative_time(t_abs)
        
        # Check for game end events
        m_win = self.re_round_win.search(line)
        if m_win:
            # Update gametype from Round_Win if available (may have been unknown at start)
            win_gametype = m_win.group("gametype")
            if win_gametype and game.gametype != win_gametype:
                self.logger.info(f"Gametype updated: {game.gametype} -> {win_gametype}")
                game.gametype = win_gametype
            game.is_ended = True
            game.game_time = t
            self.completed_games.append(game)
            # Re-arm pending map for consecutive games on same map (no Loading map between them)
            if game.map_name and game.map_name != "Unknown":
                self._pending_map_name = game.map_name
            self.logger.info(f"Game ended (Round_Win) at t={t:.1f}s")
            return "game_end"
        
        m_victory = self.re_victory.search(line)
        if m_victory:
            winning_team = m_victory.group("team")
            commander = None
            if winning_team in game.commanders and game.commanders[winning_team]:
                commander = game.commanders[winning_team][-1][1]
            game.victory_info = VictoryInfo(winning_team, commander, "Victory", t)
            self.logger.info(f"Victory: {winning_team}")
        
        # Process game events
        event_processed = False
        
        # Construction events
        m_c = self.re_construction.search(line)
        if m_c:
            team, status, name, pos_str = m_c.groups()
            pos = self.parse_position(pos_str)
            if pos:
                x, y, _ = pos
                key = (team, name, x, y)
                
                if key not in game.buildings:
                    game.buildings[key] = {
                        "team": team, "name": name, "x": x, "y": y,
                        "start_t": None, "complete_t": None, "destroy_t": None, "sold_t": None
                    }
                
                if status == "start":
                    game.buildings[key]["start_t"] = t
                else:
                    game.buildings[key]["complete_t"] = t
                
                event_processed = True
        
        # Structure sold
        m_sold = self.re_structure_sold.search(line)
        if m_sold:
            team, name, pos_str = m_sold.groups()
            pos = self.parse_position(pos_str)
            if pos:
                x, y, _ = pos
                key = (team, name, x, y)
                if key in game.buildings:
                    game.buildings[key]["sold_t"] = t
                event_processed = True
        
        # Structure kill
        m_sk = self.re_struct_kill.search(line)
        if m_sk:
            attacker_name = m_sk.group("att_name")
            attacker_team = m_sk.group("att_team") or "Unknown"
            struct_name = m_sk.group("structure")
            attacker_unit = m_sk.group("weapon")
            victim_team = m_sk.group("struct_team") or "Unknown"
            att_pos = self.parse_position(m_sk.group("att_pos"))
            bld_pos = self.parse_position(m_sk.group("bld_pos"))
            
            if bld_pos:
                bx, by, _ = bld_pos
                ax, ay = (att_pos[0], att_pos[1]) if att_pos else (bx, by)
                
                key = (victim_team, struct_name, bx, by)
                
                if key not in game.buildings:
                    game.buildings[key] = {
                        "team": victim_team, "name": struct_name, "x": bx, "y": by,
                        "start_t": None, "complete_t": None, "destroy_t": None, "sold_t": None
                    }
                game.buildings[key]["destroy_t"] = t
                
                game.kill_counter += 1
                game.kills.append(KillEvent(
                    time=t, x=bx, y=by,
                    victim_team=victim_team,
                    victim_unit=struct_name,
                    attacker_team=attacker_team,
                    attacker_unit=attacker_unit,
                    attacker_x=ax, attacker_y=ay,  # Now uses actual attacker position!
                    attacker_name=attacker_name,
                    victim_name=struct_name,
                    is_structure=True,
                    kill_number=game.kill_counter
                ))
                event_processed = True
        
        # Unit kill
        m_uk = self.re_unit_kill.search(line)
        if m_uk:
            att_name = m_uk.group("att_name")
            att_team = m_uk.group("att_team") or "Unknown"
            v_name = m_uk.group("v_name")
            v_team = m_uk.group("v_team") or "Unknown"
            weapon = m_uk.group("weapon")
            victim_unit = m_uk.group("victim_unit")
            att_pos = self.parse_position(m_uk.group("att_pos"))
            v_pos = self.parse_position(m_uk.group("v_pos"))
            
            if v_pos and att_pos:
                game.kill_counter += 1
                game.kills.append(KillEvent(
                    time=t, x=v_pos[0], y=v_pos[1],
                    victim_team=v_team,
                    victim_unit=victim_unit,
                    attacker_team=att_team,
                    attacker_unit=weapon,
                    attacker_x=att_pos[0], attacker_y=att_pos[1],
                    attacker_name=att_name,
                    victim_name=v_name,
                    is_structure=False,
                    kill_number=game.kill_counter
                ))
                
                death_type = "teamkill" if att_team == v_team else "killed"
                game.deaths.append(DeathEvent(
                    time=t, player_name=v_name, team=v_team,
                    death_type=death_type, x=v_pos[0], y=v_pos[1]
                ))
                event_processed = True
        
        # Suicide
        m_suicide = self.re_suicide.search(line)
        if m_suicide:
            player_name = m_suicide.group("player_name")
            team = m_suicide.group("team") or "Unknown"
            game.deaths.append(DeathEvent(
                time=t, player_name=player_name, team=team,
                death_type="suicide", x=None, y=None
            ))
            event_processed = True
        
        # Commander change
        m_cmd = self.re_commander.search(line)
        if m_cmd:
            player_name = m_cmd.group("player_name")
            team = m_cmd.group("team")
            if team and team != "Unknown":
                if team not in game.commanders:
                    game.commanders[team] = []
                game.commanders[team].append((t, player_name))
            event_processed = True
        
        # Tech change
        m_tech = self.re_tech_change.search(line)
        if m_tech:
            team = m_tech.group("team")
            tier = int(m_tech.group("tier"))
            game.team_tech_events[team].append((t, tier))
            event_processed = True
        
        # Resource spawned
        m_res_spawn = self.re_resource_spawned.search(line)
        if m_res_spawn:
            res_type = m_res_spawn.group("type")
            amount = int(m_res_spawn.group("amount"))
            pos_str = m_res_spawn.group("pos")
            try:
                x_str, y_str, _ = pos_str.split()
                x, y = float(x_str), float(y_str)
                
                # Create resource key for tracking
                res_key = (res_type, round(x), round(y))
                
                resource = Resource(
                    resource_type=res_type,
                    x=x,
                    y=y,
                    amount=amount,
                    spawn_t=t,
                    depleted_t=None
                )
                game.resources[res_key] = resource
                self.logger.debug(f"Resource spawned: {res_type} at ({x:.0f}, {y:.0f})")
                event_processed = True
            except Exception as e:
                self.logger.warning(f"Failed to parse resource spawn: {e}")
        
        # Resource depleted
        m_res_deplete = self.re_resource_depleted.search(line)
        if m_res_deplete:
            res_type = m_res_deplete.group("type")
            pos_str = m_res_deplete.group("pos")
            try:
                x_str, y_str, _ = pos_str.split()
                x, y = float(x_str), float(y_str)
                
                # Find matching resource
                res_key = (res_type, round(x), round(y))
                if res_key in game.resources:
                    old_res = game.resources[res_key]
                    game.resources[res_key] = Resource(
                        resource_type=old_res.resource_type,
                        x=old_res.x,
                        y=old_res.y,
                        amount=old_res.amount,
                        spawn_t=old_res.spawn_t,
                        depleted_t=t
                    )
                    self.logger.debug(f"Resource depleted: {res_type} at ({x:.0f}, {y:.0f})")
                event_processed = True
            except Exception as e:
                self.logger.warning(f"Failed to parse resource depleted: {e}")

        # Resource status (team collected/spent totals for graph)
        m_res_status = self.re_resource_status.search(line)
        if m_res_status:
            team = m_res_status.group("team")
            collected = int(m_res_status.group("collected"))
            spent = int(m_res_status.group("spent"))
            game.resource_status_events.append(ResourceStatusEvent(t, team, collected, spent))
            event_processed = True

        # Chat messages - say_team first (more specific)
        m_chat_team = self.re_chat_say_team.search(line)
        if m_chat_team:
            player_name = m_chat_team.group("player_name")
            team = m_chat_team.group("team")
            message = m_chat_team.group("message")
            # Only include messages from players with a valid team
            if team and team not in ("", "Unknown"):
                # Filter out chat commands (balance UI: /b, /1-/30)
                if not (LiveConfig.SUPPRESS_CHAT_COMMANDS and self.re_chat_command.search(message)):
                    game.chat_messages.append(ChatMessage(t, player_name, team, message, True))
                    self.logger.debug(f"Chat (team): {player_name} [{team}]: {message}")
                    event_processed = True

        # Chat messages - say (global)
        if not m_chat_team:  # Only check if say_team didn't match
            m_chat = self.re_chat_say.search(line)
            if m_chat:
                player_name = m_chat.group("player_name")
                team = m_chat.group("team")
                message = m_chat.group("message")
                # Only include messages from players with a valid team
                if team and team not in ("", "Unknown"):
                    # Filter out chat commands (balance UI: /b, /1-/30)
                    if not (LiveConfig.SUPPRESS_CHAT_COMMANDS and self.re_chat_command.search(message)):
                        game.chat_messages.append(ChatMessage(t, player_name, team, message, False))
                        self.logger.debug(f"Chat: {player_name} [{team}]: {message}")
                        event_processed = True
        
        if event_processed:
            game.update_last_event(t_abs)
            return "event"
        
        return None


# ============================================================
# LIVE FRAME GENERATOR
# ============================================================

class LiveFrameGenerator:
    """Generates video frames in real-time as game events occur."""
    
    def __init__(self, config: LiveConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.current_game: Optional[LiveGameState] = None
        
        # Video writer
        self.video_writer = None
        self.output_path: Optional[Path] = None
        self.base_filename: str = ""  # Base name without .mp4 extension
        
        # File splitting
        self.current_part = 1
        self.all_output_paths: List[Path] = []  # Track all parts
        self.frames_since_size_check = 0
        
        # Frame buffer
        self.pending_frames: List[Any] = []
        
        # Cached resources
        self.base_map = None
        self.map_name = None
        self.last_frame_rgb = None  # Track last frame for freeze effect

        # SRPL live reader for unit positions
        self.srpl_reader: Optional[LiveSrplReader] = None
        self.srpl_dir = str(Path(__file__).parent.parent / "Mods" / "ReplayLogs")
    
    def start_game(self, game: LiveGameState):
        """Initialize frame generation for a new game."""
        self.current_game = game
        self.current_part = 1
        self.all_output_paths = []
        self.frames_since_size_check = 0
        self.last_frame_rgb = None  # Reset last frame
        
        # Clear render cache from previous game (fixes killbar memory leak)
        try:
            clear_render_cache()
            self.logger.debug("Cleared render cache for new game")
        except Exception as e:
            self.logger.warning(f"Failed to clear render cache: {e}")
        
        # Set up config module paths BEFORE loading anything
        cfg.ICON_DIR = str(self.config.ICONS_DIR)
        cfg.MAP_PATH = str(self.config.MAPS_DIR / f"{game.map_name}.png")
        
        self.logger.info(f"Set ICON_DIR to: {cfg.ICON_DIR}")
        self.logger.info(f"Set MAP_PATH to: {cfg.MAP_PATH}")
        
        # Get and log map-specific world extent
        world_extent = cfg.get_world_extent(game.map_name)
        self.logger.info(f"Map world extent: {world_extent} (map: {game.map_name})")
        
        # Load map
        try:
            from PIL import Image
            if _HAS_ASSET_PACK:
                from map_loader import load_map
                self.base_map = load_map(
                    game.map_name,
                    maps_dir=str(self.config.MAPS_DIR)
                )
            else:
                map_path = self.config.MAPS_DIR / f"{game.map_name}.png"
                if not map_path.exists():
                    self.logger.error(f"Map image not found: {map_path}")
                    return False
                self.base_map = Image.open(map_path).convert("RGBA")
            
            self.map_name = game.map_name
            
            # Resize map if needed
            target_size = cfg.MAP_SIZE
            if self.base_map.size[0] != target_size:
                self.base_map = self.base_map.resize(
                    (target_size, target_size), 
                    resample=Image.BICUBIC
                )
            
            self.logger.info(f"Loaded map: {game.map_name} ({self.base_map.size})")
            
        except Exception as e:
            self.logger.error(f"Failed to load map: {e}")
            return False
        
        # Create base filename (without part number)
        # Use game date/time from log if available, otherwise fall back to current time
        if hasattr(game, 'game_date_for_filename') and game.game_date_for_filename:
            # Use date and time from the actual game log
            date_part = game.game_date_for_filename  # YYYY-MM-DD
            time_part = getattr(game, 'game_time_for_filename', datetime.now().strftime("%H%M%S"))  # HHMM or HHMMSS
            timestamp = f"{date_part}_{time_part}"
        else:
            # Fall back to current time (for non-cleanlog format)
            timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        
        gametype_short = self._get_gametype_short(game.gametype)
        self.base_filename = f"{timestamp}_{game.map_name}_{gametype_short}"
        
        # Ensure output directory exists
        self.config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        # Try to find and open the matching SRPL file for unit positions
        self._open_srpl_for_game(game)

        # Initialize first video file
        return self._start_new_video_file()
    
    def _open_srpl_for_game(self, game: LiveGameState):
        """Find and open the SRPL file matching this game."""
        # Close any previous reader
        if self.srpl_reader:
            self.srpl_reader.close()
            self.srpl_reader = None

        if not os.path.isdir(self.srpl_dir):
            self.logger.info(f"SRPL dir not found: {self.srpl_dir}")
            return

        # Find the most recent .srpl file for this map
        # During a live game, the file was just created moments ago
        best_path = None
        best_mtime = 0
        for fname in os.listdir(self.srpl_dir):
            if not fname.endswith(".srpl"):
                continue
            if game.map_name and game.map_name not in fname:
                continue
            fpath = os.path.join(self.srpl_dir, fname)
            mtime = os.path.getmtime(fpath)
            if mtime > best_mtime:
                best_mtime = mtime
                best_path = fpath

        if not best_path:
            self.logger.info(f"No SRPL file found for map {game.map_name}")
            return

        # Only use if recently created (within last 120 seconds)
        if time.time() - best_mtime > 120:
            self.logger.info(f"SRPL file too old ({time.time() - best_mtime:.0f}s), skipping")
            return

        reader = LiveSrplReader(best_path)
        if reader.open():
            self.srpl_reader = reader
            self.logger.info(f"SRPL live reader opened: {best_path}")
            # Compute time offset: SRPL t=0 is true game start (Unix timestamp in header).
            # Log-derived game.start_time is absolute log timer (seconds since server start),
            # not Unix time — so we use the SRPL file's mtime as a proxy for creation time,
            # then compute how many seconds of game had elapsed before the log detected it.
            # offset = (log_start_unix - srpl_start_unix)
            # A positive offset means the log detected the game late; we shift SRPL forward.
            srpl_start_unix = reader.replay.start_timestamp
            if srpl_start_unix > 0 and hasattr(game, '_start_unix') and game._start_unix > 0:
                offset = game._start_unix - srpl_start_unix
                reader.replay.time_offset = max(0.0, offset)
                self.logger.info(f"SRPL time offset: {offset:.1f}s (log started {offset:.1f}s after SRPL)")
            else:
                # Fallback: use file mtime vs current time to estimate offset
                reader.replay.time_offset = 0.0
        else:
            self.logger.warning(f"Failed to open SRPL: {best_path}")

    def _start_new_video_file(self) -> bool:
        """Start a new video file (for initial or after split)."""
        # Close current writer if exists
        if self.video_writer:
            try:
                self.video_writer.close()
            except:
                pass
        
        # Generate filename with part number if we're splitting
        if self.current_part == 1 and len(self.all_output_paths) == 0:
            # First file - no part number yet (will rename if we need to split)
            filename = f"{self.base_filename}.mp4"
        else:
            # We're splitting - use part number
            filename = f"{self.base_filename}_pt{self.current_part}.mp4"
        
        self.output_path = self.config.OUTPUT_DIR / filename
        
        try:
            import imageio.v2 as imageio
            
            # Get settings from config (with defaults)
            bitrate = getattr(self.config, 'VIDEO_BITRATE_KBPS', 1900)
            preset = getattr(self.config, 'FFMPEG_PRESET', 'veryfast')
            
            # FFmpeg parameters balanced for quality and memory
            # Key changes from ultra-low-memory version:
            # - Removed -tune zerolatency (caused quality pulsing)
            # - Changed -g to match FPS (keyframe every second)
            # - Using -tune animation (better for game graphics)
            # - Increased bufsize for smoother quality
            self.video_writer = imageio.get_writer(
                str(self.output_path),
                fps=cfg.VIDEO_FPS,
                codec='libx264',
                quality=None,  # Disable quality mode, use bitrate instead
                macro_block_size=16,  # Force standard macroblock alignment
                output_params=[
                    '-b:v', f'{bitrate}k',        # Target bitrate from config
                    '-maxrate', f'{int(bitrate * 1.5)}k',  # Allow 50% burst for quality
                    '-bufsize', f'{bitrate}k',    # Full bitrate buffer for consistent quality
                    '-preset', preset,            # Encoding preset from config
                    '-tune', 'animation',         # Better for game graphics (consistent quality)
                    '-pix_fmt', 'yuv420p',        # Standard format
                    '-movflags', '+faststart',    # Better streaming
                    '-threads', '2',              # 2 threads (balance of speed/memory)
                    '-bf', '0',                   # No B-frames = consistent frame quality
                    '-g', '90',                   # Keyframe every 2 seconds (90 frames at 45fps)
                ]
            )
            self.all_output_paths.append(self.output_path)
            self.logger.info(f"Video writer initialized: {self.output_path} (bitrate: {bitrate}k, preset: {preset})")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to initialize video writer: {e}")
            return False
    
    def _check_file_size_and_split(self) -> bool:
        """
        Check current file size and split if needed.
        
        Returns True if a split occurred.
        """
        if not self.output_path or not self.output_path.exists():
            return False
        
        # Get current file size
        try:
            # Flush the writer to get accurate size
            if hasattr(self.video_writer, '_writer'):
                # For imageio-ffmpeg backend
                pass  # Can't easily flush
            
            current_size_mb = self.output_path.stat().st_size / (1024 * 1024)
            
            if current_size_mb >= self.config.MAX_FILE_SIZE_MB:
                self.logger.info(f"File size {current_size_mb:.1f}MB exceeds limit, splitting...")
                
                # If this is the first split, rename the first file to add _pt1
                if self.current_part == 1 and len(self.all_output_paths) == 1:
                    old_path = self.all_output_paths[0]
                    new_path = self.config.OUTPUT_DIR / f"{self.base_filename}_pt1.mp4"
                    
                    # Close current writer
                    try:
                        self.video_writer.close()
                    except:
                        pass
                    
                    # Rename file
                    try:
                        old_path.rename(new_path)
                        self.all_output_paths[0] = new_path
                        self.logger.info(f"Renamed {old_path.name} to {new_path.name}")
                    except Exception as e:
                        self.logger.error(f"Failed to rename file: {e}")
                
                # Start next part
                self.current_part += 1
                self._start_new_video_file()
                return True
                
        except Exception as e:
            self.logger.warning(f"Error checking file size: {e}")
        
        return False
    
    def _get_gametype_short(self, gametype: str) -> str:
        """Convert gametype to short form."""
        mapping = {
            "HUMANS_VS_HUMANS_VS_ALIENS": "HvHvA",
            "HUMANS_VS_ALIENS": "HvA",
            "HUMANS2_VS_ALIENS": "HvA",
            "HUMANS_VS_HUMANS": "HvH",
        }
        return mapping.get(gametype, "Game")
    
    def generate_frames_up_to(self, game_time: float):
        """Generate all frames from last generated to current game time."""
        if not self.current_game or not self.video_writer:
            return
        
        game = self.current_game
        
        # Get GC interval from config (0 = disabled)
        gc_interval = getattr(self.config, 'GC_INTERVAL_FRAMES', 50)
        
        # Convert buildings dict to Building namedtuples
        buildings = {}
        for key, b in game.buildings.items():
            buildings[key] = Building(
                team=b["team"], name=b["name"], x=b["x"], y=b["y"],
                start_t=b["start_t"], complete_t=b["complete_t"],
                destroy_t=b["destroy_t"], sold_t=b["sold_t"]
            )
        
        # Build stats
        kill_stats, building_stats = build_all_stats_from_log(
            buildings, game.kills,
            team_tech_events=dict(game.team_tech_events)
        )
        player_stats = build_player_stats_from_kills(game.kills)
        
        # Add death events to player stats
        for death in game.deaths:
            if death.player_name in player_stats:
                player = player_stats[death.player_name]
                player.total_deaths += 1
                if death.death_type == "suicide":
                    player.suicide_deaths += 1
                player.death_events.append(death)
        
        # Build unit kill stats
        unit_kill_stats = defaultdict(int)
        for kill in game.kills:
            if kill.attacker_unit and kill.attacker_unit != "Unknown":
                unit_kill_stats[kill.attacker_unit] += 1

        # Build resource stats for graph 2
        resource_stats = None
        if game.resource_status_events:
            resource_stats = build_resource_stats_from_log(game.resource_status_events)

        # Refresh SRPL data and override kill_stats with full kill data
        srpl_replay = None
        if not self.srpl_reader:
            # Retry finding SRPL file (may not have existed at game start)
            self._open_srpl_for_game(game)
        if self.srpl_reader:
            new_records = self.srpl_reader.refresh()
            if new_records > 0:
                self.logger.debug(f"SRPL: read {new_records} new records")
            srpl_replay = self.srpl_reader.replay
            # Override kill_stats with SRPL data (includes AI vs AI kills)
            if srpl_replay and srpl_replay.destructions:
                kill_stats = build_kill_stats_from_srpl(srpl_replay)

        # Generate frames
        start_t = game.last_frame_time
        end_t = game_time
        
        frame_times = []
        t = start_t
        while t <= end_t:
            frame_times.append(t)
            t += cfg.FRAME_STEP
        
        if not frame_times:
            return
        
        # Get map-specific world extent
        world_extent = cfg.get_world_extent(game.map_name)
        
        for t in frame_times:
            try:
                # Compute SRPL unit positions and dying units for this frame
                srpl_units = None
                dying_eids = None
                if srpl_replay and srpl_replay.ticks:
                    destroyed = srpl_replay.get_destroyed_before(t)
                    all_pos = srpl_replay.get_positions_at_time(t)

                    prev_t = t - cfg.FRAME_STEP
                    if prev_t >= 0:
                        prev_destroyed = srpl_replay.get_destroyed_before(prev_t)
                        dying_eids = destroyed - prev_destroyed
                    else:
                        dying_eids = None

                    srpl_units = [p for p in all_pos
                                  if p["entity_id"] not in destroyed
                                  or p["entity_id"] in (dying_eids or set())]

                frame = render_frame(
                    self.base_map,
                    buildings,
                    game.kills,
                    kill_stats,
                    building_stats,
                    player_stats,
                    unit_kill_stats,
                    game.commanders,
                    float(t),
                    heat_overlay_rgba=None,
                    world_extent=world_extent,
                    timing_detail={},
                    frame_num=game.frames_generated,
                    resources=list(game.resources.values()),  # Convert dict to list
                    victory_info=game.victory_info,
                    t_end=end_t,
                    total_frames=0,
                    map_name=game.map_name,
                    log_date=game.game_datetime or game.log_date,  # Pass full datetime if available
                    chat_messages=game.chat_messages,  # Pass chat messages for chat panel
                    resource_stats=resource_stats,
                    unit_positions=srpl_units,
                    dying_units=dying_eids,
                )
                
                # Write frame - convert to numpy array and immediately write
                frame_array = np.array(frame.convert("RGB"))
                self.video_writer.append_data(frame_array)
                
                # Store last frame for potential freeze effect
                self.last_frame_rgb = frame_array.copy()
                
                # Explicitly free memory
                del frame_array
                del frame
                
                game.frames_generated += 1
                self.frames_since_size_check += 1
                
                # Periodically check file size for splitting
                if self.frames_since_size_check >= self.config.FILE_SIZE_CHECK_INTERVAL:
                    self.frames_since_size_check = 0
                    self._check_file_size_and_split()
                
                # Periodic garbage collection to prevent memory buildup
                if gc_interval > 0 and game.frames_generated % gc_interval == 0:
                    gc.collect()
                
            except Exception as e:
                self.logger.error(f"Error generating frame at t={t}: {e}")
        
        game.last_frame_time = end_t
        
        # Log progress every 100 frames or 60 game-seconds
        if game.frames_generated % 100 == 0 or len(frame_times) > 30:
            self.logger.info(f"Progress: {game.frames_generated} frames generated ({end_t:.0f}s game time)")
    
    def finalize_game(self):
        """Finalize the current game video."""
        if not self.current_game or not self.video_writer:
            return None
        
        game = self.current_game
        
        # Generate any remaining frames
        self.generate_frames_up_to(game.game_time)
        
        # Add freeze frames before scoreboard (hold last gameplay frame)
        try:
            freeze_frame_count = getattr(cfg, 'FREEZE_LAST_FRAME_COUNT', 30)
            if freeze_frame_count > 0 and self.last_frame_rgb is not None:
                for _ in range(freeze_frame_count):
                    self.video_writer.append_data(self.last_frame_rgb)
                self.logger.info(f"Added {freeze_frame_count} freeze frames before scoreboard")
        except Exception as e:
            self.logger.warning(f"Error adding freeze frames: {e}")
        
        # Add scoreboard
        try:
            if getattr(cfg, 'SCOREBOARD_ENABLED', True):
                player_stats = build_player_stats_from_kills(game.kills)
                
                # Add deaths
                for death in game.deaths:
                    if death.player_name in player_stats:
                        player = player_stats[death.player_name]
                        player.total_deaths += 1
                        if death.death_type == "suicide":
                            player.suicide_deaths += 1
                
                scoreboard_frames = getattr(cfg, 'SCOREBOARD_FRAMES', 450)
                scoreboard_img = render_scoreboard(
                    player_stats, {},
                    cfg.VIDEO_WIDTH, cfg.VIDEO_HEIGHT,
                    victory_info=game.victory_info
                )
                scoreboard_rgb = np.array(scoreboard_img.convert("RGB"))
                
                for _ in range(scoreboard_frames):
                    self.video_writer.append_data(scoreboard_rgb)
                
                self.logger.info(f"Added scoreboard ({scoreboard_frames} frames)")
                
        except Exception as e:
            self.logger.error(f"Error adding scoreboard: {e}")
        
        # Close video writer
        try:
            self.video_writer.close()
            self.logger.info(f"Video finalized: {self.output_path}")
        except Exception as e:
            self.logger.error(f"Error closing video writer: {e}")
        
        # Prepare result with all info needed for Discord upload
        result = {
            'paths': self.all_output_paths.copy(),
            'map_name': game.map_name,
            'gametype': self._get_gametype_short(game.gametype),
            'duration_mins': game.game_time / 60.0,
            'frames': game.frames_generated,
            'parts': len(self.all_output_paths),
            'game_date': getattr(game, 'game_datetime', None) or getattr(game, 'full_date', None),  # YYYY/MM/DD - HH:MM or YYYY-MM-DD
            'commanders': game.commanders,
            'victory_info': game.victory_info,
        }
        
        # Log file size info
        total_size_mb = 0
        for p in self.all_output_paths:
            if p.exists():
                size_mb = p.stat().st_size / (1024 * 1024)
                total_size_mb += size_mb
                self.logger.info(f"  Part: {p.name} ({size_mb:.1f}MB)")
        
        if len(self.all_output_paths) > 1:
            self.logger.info(f"Total: {len(self.all_output_paths)} parts, {total_size_mb:.1f}MB")
        
        self.video_writer = None
        self.current_game = None
        self.base_map = None
        self.all_output_paths = []
        self.last_frame_rgb = None  # Clear last frame reference

        # Close SRPL reader
        if self.srpl_reader:
            self.srpl_reader.close()
            self.srpl_reader = None

        # Clear render cache after game ends
        try:
            clear_render_cache()
        except:
            pass
        
        return result


# ============================================================
# MAIN SERVICE
# ============================================================

class MapReplayService:
    """Main service that orchestrates real-time replay generation."""
    
    def __init__(self, config: LiveConfig):
        self.config = config
        self.logger = setup_logging(config)
        
        self.cpu_manager = CPUAffinityManager(config.AVOID_CORES, self.logger)
        self.log_watcher = LogFileWatcher(config.LOG_DIR, config.LOG_PATTERN, self.logger)
        self.parser = LiveLogParser(self.logger)
        self.frame_generator = LiveFrameGenerator(config, self.logger)
        self.discord_uploader = DiscordUploader(config, self.logger)
        
        self.running = False
        self.stats = {
            "lines_processed": 0,
            "games_completed": 0,
            "errors": 0,
        }
    
    def _handle_game_completion(self, result_info: dict) -> bool:
        """
        Handle a completed game - check duration, save, and optionally upload.
        
        Args:
            result_info: Dictionary with game info from finalize_game()
            
        Returns:
            True if game was saved (met minimum duration), False otherwise
        """
        if not result_info or not result_info.get('paths'):
            return False
        
        duration_mins = result_info.get('duration_mins', 0)
        min_duration_mins = self.config.MIN_GAME_DURATION / 60.0  # Convert seconds to minutes
        
        # Check minimum duration
        if duration_mins < min_duration_mins:
            self.logger.info(f"Game too short ({duration_mins:.1f} min < {min_duration_mins:.0f} min minimum) - deleting replay")
            # Delete the video files
            for path in result_info['paths']:
                try:
                    if path.exists():
                        path.unlink()
                        self.logger.debug(f"Deleted: {path}")
                except Exception as e:
                    self.logger.warning(f"Failed to delete {path}: {e}")
            return False
        
        # Game meets minimum duration - count it
        self.stats["games_completed"] += 1
        
        # Log completion
        for path in result_info['paths']:
            self.logger.info(f"Game replay saved: {path}")
        
        # Upload to Discord if enabled
        if self.config.DISCORD_WEBHOOK_ENABLED and self.config.DISCORD_WEBHOOK_URL:
            self.logger.info("Uploading to Discord...")
            success = self.discord_uploader.upload_all_parts(
                result_info['paths'],
                result_info['map_name'],
                result_info['gametype'],
                result_info['duration_mins'],
                game_date=result_info.get('game_date'),
                commanders=result_info.get('commanders'),
                victory_info=result_info.get('victory_info')
            )
            if success:
                self.logger.info("Discord upload complete!")
            else:
                self.logger.warning("Discord upload failed (video saved locally)")
        
        return True
    
    def start(self):
        """Start the service."""
        self.logger.info("=" * 60)
        self.logger.info("MapReplay Live Service Starting")
        self.logger.info("=" * 60)
        
        # Set video resolution from config
        cfg.set_resolution(self.config.VIDEO_RESOLUTION)
        self.logger.info(f"Video resolution: {self.config.VIDEO_RESOLUTION} ({cfg.VIDEO_WIDTH}x{cfg.VIDEO_HEIGHT})")
        
        # Initialize asset pack
        if _HAS_ASSET_PACK:
            try:
                init_asset_pack()
                self.logger.info("Asset pack loaded successfully")
            except FileNotFoundError:
                self.logger.warning("assets.pak not found, falling back to raw Asset files")
        
        # Set CPU affinity
        self.cpu_manager.set_affinity()
        
        # Find and open the latest log file
        latest_log = self.log_watcher.get_latest_log_file()
        if latest_log:
            self.log_watcher.open_file(latest_log, from_end=True)
            self.logger.info(f"Monitoring log file: {latest_log}")
        else:
            self.logger.warning(f"No log files found in {self.config.LOG_DIR}")
            self.logger.info("Waiting for log files...")
        
        self.running = True
        self.logger.info("Service started - monitoring for games...")
        
        try:
            self._main_loop()
        except KeyboardInterrupt:
            self.logger.info("Shutdown requested (Ctrl+C)")
        finally:
            self.stop()
    
    def _main_loop(self):
        """Main processing loop."""
        last_event_check = time.time()
        self._last_line_time = time.time()  # Track last log line for timeout
        
        while self.running:
            # Check for new log file (midnight rollover)
            self.log_watcher.check_for_new_file()
            
            # If no file open, try to find one
            if not self.log_watcher.file_handle:
                latest = self.log_watcher.get_latest_log_file()
                if latest:
                    self.log_watcher.open_file(latest, from_end=True)
                else:
                    time.sleep(self.config.POLL_INTERVAL)
                    continue
            
            # Read new lines
            new_lines = self.log_watcher.read_new_lines()
            
            for line in new_lines:
                # Check for log file closed
                if self.log_watcher.check_for_log_closed(line):
                    self.logger.info("Log file closed (midnight rollover)")
                    self.log_watcher.close_file()
                    continue
                
                # Process line
                result = self.parser.process_line(line)
                self.stats["lines_processed"] += 1
                
                if result == "game_start":
                    # First, finalize any previous game that was force-ended
                    if self.frame_generator.current_game:
                        prev_game = self.frame_generator.current_game
                        if prev_game.is_ended or prev_game != self.parser.current_game:
                            self.logger.info(f"Finalizing previous game (new game starting)")
                            result_info = self.frame_generator.finalize_game()
                            self._handle_game_completion(result_info)
                    
                    game = self.parser.current_game
                    if game:
                        # Wait a moment for map name to be identified
                        pass
                
                elif result == "game_end":
                    # Finalize the game
                    if self.frame_generator.current_game:
                        result_info = self.frame_generator.finalize_game()
                        self._handle_game_completion(result_info)
                
                elif result == "event":
                    game = self.parser.current_game
                    if game:
                        # Start frame generator if not started
                        if not self.frame_generator.current_game:
                            if game.map_name != "Unknown":
                                self.frame_generator.start_game(game)
                        
                        # Generate frames periodically (every 5 game-seconds)
                        time_since_last_frame = game.game_time - game.last_frame_time
                        if time_since_last_frame >= self.config.FRAME_STEP * 5:
                            self.logger.debug(f"Generating frames: game_time={game.game_time:.1f}s, last_frame={game.last_frame_time:.1f}s")
                            self.frame_generator.generate_frames_up_to(game.game_time)
            
            # Also generate frames if game is active but we haven't in a while
            # (This handles slow periods with few events)
            if self.parser.current_game and not self.parser.current_game.is_ended:
                game = self.parser.current_game
                if self.frame_generator.current_game:
                    time_since_last_frame = game.game_time - game.last_frame_time
                    if time_since_last_frame >= self.config.FRAME_STEP * 10:  # Catch-up if behind
                        self.logger.debug(f"Catch-up frame generation: {time_since_last_frame:.1f}s behind")
                        self.frame_generator.generate_frames_up_to(game.game_time)
            
            # Check for game timeout (no events for a while)
            # Skip if timeout-based ending is disabled (for emulator testing)
            current_time = time.time()
            if not self.config.DISABLE_TIMEOUT_END and current_time - last_event_check > 5:
                last_event_check = current_time
                
                if self.parser.current_game and not self.parser.current_game.is_ended:
                    game = self.parser.current_game
                    
                    # Check if no new log lines for GAME_END_TIMEOUT seconds
                    # This handles cases where Round_Win is missed or server hangs
                    if hasattr(self, '_last_line_time'):
                        seconds_since_last_line = current_time - self._last_line_time
                        if seconds_since_last_line > self.config.GAME_END_TIMEOUT:
                            self.logger.info(f"Game timeout: no log activity for {seconds_since_last_line:.0f}s, ending game")
                            game.is_ended = True
                            self.parser.current_game.is_ended = True
                            # Re-arm pending map for next game auto-detect
                            if game.map_name and game.map_name != "Unknown":
                                self.parser._pending_map_name = game.map_name
                            
                            # Finalize the game
                            if self.frame_generator.current_game:
                                result_info = self.frame_generator.finalize_game()
                                self._handle_game_completion(result_info)
            
            # Track when we last received a log line
            if new_lines:
                self._last_line_time = current_time
            
            # Small sleep to avoid busy-waiting
            if not new_lines:
                time.sleep(self.config.POLL_INTERVAL)
    
    def stop(self):
        """Stop the service gracefully."""
        self.logger.info("Stopping service...")
        self.running = False
        
        # Finalize any in-progress game
        if self.frame_generator.current_game:
            self.logger.info("Finalizing in-progress game...")
            self.frame_generator.finalize_game()
        
        # Close log file
        self.log_watcher.close_file()
        
        # Restore CPU affinity
        self.cpu_manager.restore_affinity()
        
        # Print stats
        self.logger.info("=" * 60)
        self.logger.info("Service Statistics:")
        self.logger.info(f"  Lines processed: {self.stats['lines_processed']}")
        self.logger.info(f"  Games completed: {self.stats['games_completed']}")
        self.logger.info(f"  Errors: {self.stats['errors']}")
        self.logger.info("=" * 60)
        self.logger.info("Service stopped.")


# ============================================================
# ENTRY POINT
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="MapReplay Live Service - Real-time game replay generation"
    )
    parser.add_argument(
        "--server-root",
        type=Path,
        help="Path to Silica Dedicated Server root directory"
    )
    parser.add_argument(
        "--avoid-cores",
        type=str,
        default="0",
        help="Comma-separated list of CPU cores to avoid (default: 0)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    
    args = parser.parse_args()
    
    # Create config
    config = LiveConfig()
    
    if args.server_root:
        config.SERVER_ROOT = args.server_root.resolve()
        config.LOG_DIR = config.SERVER_ROOT / "UserData" / "logs"
    
    if args.avoid_cores:
        config.AVOID_CORES = [int(c.strip()) for c in args.avoid_cores.split(",")]
    
    if args.debug:
        config.LOG_LEVEL = logging.DEBUG
    
    # Verify paths exist
    if not config.LOG_DIR.exists():
        print(f"Error: Log directory not found: {config.LOG_DIR}")
        print("Please specify --server-root or run from within Mod MapReplay directory")
        sys.exit(1)
    
    # Start service
    service = MapReplayService(config)
    service.start()


if __name__ == "__main__":
    main()
