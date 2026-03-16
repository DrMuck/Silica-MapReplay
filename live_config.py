# -*- coding: utf-8 -*-
"""
MapReplay Live Service Configuration

This file contains settings specific to the real-time replay generation service.
For video rendering settings, see modules/config.py
"""

# ============================================================
# VIDEO RESOLUTION
# ============================================================

# Video output resolution
# Options: "720p", "1080p", "1440p", "4k"
# Higher resolutions = better quality but larger files and more CPU
VIDEO_RESOLUTION = "1440p"


# ============================================================
# CPU AFFINITY SETTINGS
# ============================================================

# List of CPU cores to avoid using
# Typically core 0 is used heavily by the game server
# Set to empty list [] to use all cores
AVOID_CORES = [0]

# Process priority (Windows: IDLE_PRIORITY_CLASS, BELOW_NORMAL_PRIORITY_CLASS, etc.)
# Options: "idle", "below_normal", "normal"
PROCESS_PRIORITY = "below_normal"


# ============================================================
# LOG MONITORING SETTINGS
# ============================================================

# How often to check for new log lines (seconds)
POLL_INTERVAL = 0.5

# How many lines to process in one batch
LINE_BATCH_SIZE = 100


# ============================================================
# GAME DETECTION SETTINGS
# ============================================================

# Minimum game duration to generate replay (seconds)
# Games shorter than this will be skipped
MIN_GAME_DURATION = 600  # 10 minutes

# Seconds to wait after last event before considering game ended
# (Fallback if Round_Win event is missed)
# Note: resource_status events only fire every 60s, so this must be >60
GAME_END_TIMEOUT = 180

# Disable timeout-based game ending (for emulator testing)
# When True, games only end on Round_Win/Victory or new Round_Start
# Set to True when testing with Log_Emulator to avoid premature game endings
DISABLE_TIMEOUT_END = False

# Game types to process (leave empty for all)
# Options: "HUMANS_VS_HUMANS_VS_ALIENS", "HUMANS_VS_ALIENS", "HUMANS_VS_HUMANS"
GAMETYPE_FILTER = []  # Empty = process all game types


# ============================================================
# FRAME GENERATION SETTINGS
# ============================================================

# How often to generate frames during live processing (seconds)
# Higher values = less CPU usage but less responsive
FRAME_GENERATION_INTERVAL = 5

# Maximum frames to buffer before forcing write
MAX_PENDING_FRAMES = 500


# ============================================================
# MEMORY OPTIMIZATION SETTINGS
# ============================================================

# Video encoding bitrate (kbps)
# Lower = smaller files, less RAM, but lower quality
# Recommended: 1200-1800 for 1440p, 800-1200 for 1080p
VIDEO_BITRATE_KBPS = 2200  # Average target; encoder can burst up to 1.5x for complex frames

# FFmpeg encoding preset
# Options: "ultrafast", "superfast", "veryfast", "faster", "fast", "medium"
# Faster presets use less memory but produce larger files
# "veryfast" is a good balance
FFMPEG_PRESET = "veryfast"

# Graph update interval (frames)
# Higher = less frequent graph updates, saves memory/CPU
# Graphs are cached between updates
GRAPH_UPDATE_INTERVAL = 10

# Force garbage collection every N frames
# Helps prevent memory buildup, set to 0 to disable
GC_INTERVAL_FRAMES = 50


# ============================================================
# FILE SPLITTING SETTINGS
# ============================================================

# Maximum file size in MB before splitting into parts
# Discord has a 25MB limit for regular servers, 100MB for boosted
# Recommended: 24 (to stay safely under Discord's limit)
MAX_FILE_SIZE_MB = 46

# How often to check file size (every N frames)
FILE_SIZE_CHECK_INTERVAL = 100


# ============================================================
# DISCORD WEBHOOK SETTINGS
# ============================================================

# Enable automatic upload to Discord
DISCORD_WEBHOOK_ENABLED = False

# Discord webhook URL - get this from your Discord server settings
# Server Settings -> Integrations -> Webhooks -> New Webhook -> Copy Webhook URL
# Example: "https://discord.com/api/webhooks/1234567890/abcdefghijklmnop..."
DISCORD_WEBHOOK_URL = ""

# Upload timeout in seconds (increase for slow connections)
DISCORD_UPLOAD_TIMEOUT = 120

# Number of retry attempts for failed uploads
DISCORD_RETRY_ATTEMPTS = 3


# ============================================================
# OUTPUT SETTINGS  
# ============================================================

# Output filename format
# Available placeholders: {date}, {time}, {map}, {gametype}
OUTPUT_FILENAME_FORMAT = "{date}_{time}_{map}_{gametype}.mp4"

# Automatically delete replays older than N days (0 = never delete)
AUTO_DELETE_DAYS = 30


# ============================================================
# LOGGING SETTINGS
# ============================================================

# Log level: DEBUG, INFO, WARNING, ERROR
LOG_LEVEL = "INFO"

# Maximum log file size (MB) before rotation
MAX_LOG_SIZE_MB = 49

# Number of log backups to keep
LOG_BACKUP_COUNT = 5
