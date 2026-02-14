# -*- coding: utf-8 -*-
"""
Configuration Module for Replay Generator

All settings and configuration constants.
Each resolution has its own complete set of parameters - no scaling factors.

Usage:
    import config
    config.set_resolution("1080p")  # Call once at startup
    # Then access: config.KILLBAR_FONT_SIZE, config.ICON_SCALE, etc.
"""

import os

# ============================================================
# RESOLUTION CONFIGURATIONS
# Each resolution has ALL parameters explicitly defined
# ============================================================

RESOLUTION_CONFIGS = {
    "720p": {
        # Video dimensions
        "map_size": 720,
        "killbar_width": 200,
        "stats_width": 360,
        "total_width": 1280,
        "total_height": 720,
        
        # Icon scales
        "icon_scale": 0.55,           # Building/unit icons on map
        "resource_icon_scale": 0.35,  # Resource icons
        "kill_icon_scale": 0.9,       # Kill event icons multiplier
        "kill_soldier_scale": 0.7,    # Soldier icons multiplier
        
        # Killbar settings
        "killbar_entry_height": 18,
        "killbar_icon_size": 20,
        "killbar_font_size": 9,
        "killbar_max_entries": 42,  # Full height killbar (chat moved to stats panel)
        "killbar_icon_to_name_offset": -4,  # Offset between icon and name
        
        # Chat panel settings (lower 1/3 of killbar column)
        "chat_entry_height": 16,
        "chat_font_size": 8,
        "chat_max_entries": 14,  # Fits in bottom 1/3
        "chat_name_max_chars": 15,
        
        # Kill numbers on map
        "kill_number_font_size": 8,
        "kill_number_offset_y": -15,
        "attack_line_width": 2,
        
        # Graph fonts
        "graph_font_ax": 10,          # Axis tick labels
        "graph_font_label": 11,       # Axis titles
        "graph_font_legend": 10,      # Legend text
        "graph_height": 160,
        "graph_label_pad_x": 5,       # X-axis label offset from graph
        "graph_label_pad_y": 5,       # Y-axis label offset from graph
        
        # Table 1 (Team Statistics)
        "table1_header_font_size": 7,
        "table1_data_font_size": 10,
        "table1_row_height": 24,
        "table1_header_height": 16,
        "table1_icon_size": 20,
        "table1_height": 100,
        "table1_x_offset": -10,
        
        # Table 2 (Achievements)
        "table2_label_font_size": 11,
        "table2_data_font_size": 9,
        "table2_line_height": 15,
        "table2_x_data": 110,
        "table2_height": 230,
        "table1_to_table2_gap": 11,
        "table2_header_spacing": 8,
        
        # Heatmap
        "kill_heat_radius": 22,
        
        # Clock
        "clock_font_size": 20,
        "clock_margin": 10,
        "clock_box_margin": 5,
        
        # Victory screen
        "victory_font_size": 30,
        
        # Map info overlay (for cleanlog)
        "map_info_font_size": 14,
        "map_info_margin": 8,
    },
    
    "1080p": {
        # Video dimensions
        "map_size": 1080,
        "killbar_width": 280,
        "stats_width": 560,
        "total_width": 1920,
        "total_height": 1080,
        
        # Icon scales
        "icon_scale": 0.8,
        "resource_icon_scale": 0.45,
        "kill_icon_scale": 1.2,
        "kill_soldier_scale": 0.6,
        
        # Killbar settings
        "killbar_entry_height": 22,
        "killbar_icon_size": 26,
        "killbar_font_size": 12,
        "killbar_max_entries": 54,  # Full height killbar (chat moved to stats panel)
        "killbar_icon_to_name_offset": -6,  # Offset between icon and name
        
        # Chat panel settings (lower 1/3 of killbar column)
        "chat_entry_height": 18,
        "chat_font_size": 10,
        "chat_max_entries": 18,  # Fits in bottom 1/3
        "chat_name_max_chars": 15,
        
        # Kill numbers on map
        "kill_number_font_size": 13,
        "kill_number_offset_y": -22,
        "attack_line_width": 2,
        
        # Graph fonts
        "graph_font_ax": 11,
        "graph_font_label": 13,
        "graph_font_legend": 12,
        "graph_height": 240,
        "graph_label_pad_x": 8,       # X-axis label offset from graph
        "graph_label_pad_y": 8,       # Y-axis label offset from graph
        
        # Table 1 (Team Statistics)
        "table1_header_font_size": 12,
        "table1_data_font_size": 14,
        "table1_row_height": 36,
        "table1_header_height": 22,
        "table1_icon_size": 28,
        "table1_height": 150,
        "table1_x_offset": 0,
        
        # Table 2 (Achievements)
        "table2_label_font_size": 16,
        "table2_data_font_size": 14,
        "table2_line_height": 22,
        "table2_x_data": 160,
        "table2_height": 330,
        "table1_to_table2_gap": 10,
        "table2_header_spacing": 12,
        
        # Heatmap
        "kill_heat_radius": 34,
        
        # Clock
        "clock_font_size": 30,
        "clock_margin": 15,
        "clock_box_margin": 8,
        
        # Victory screen
        "victory_font_size": 45,
        
        # Map info overlay (for cleanlog)
        "map_info_font_size": 18,
        "map_info_margin": 10,
    },
    
    "1440p": {
        # Video dimensions
        "map_size": 1440,
        "killbar_width": 340,
        "stats_width": 780,
        "total_width": 2560,
        "total_height": 1440,
        
       # Icon scales
        "icon_scale": 0.80,
        "resource_icon_scale": 0.60,
        "kill_icon_scale": 0.8,
        "kill_soldier_scale": 0.5,
        
        # Killbar settings
        "killbar_entry_height": 24,
        "killbar_icon_size": 25,
        "killbar_font_size": 16,
        "killbar_max_entries": 65,  # Full height killbar (chat moved to stats panel)
        "killbar_icon_to_name_offset": -8,  # Offset between icon and name
        
        # Chat panel settings (lower 1/3 of killbar column)
        "chat_entry_height": 20,
        "chat_font_size": 12,
        "chat_max_entries": 22,  # Fits in bottom 1/3
        "chat_name_max_chars": 15,
        
        # Kill numbers on map
        "kill_number_font_size": 15,
        "kill_number_offset_y": -30,
        "attack_line_width": 3,
        
        # Graph fonts
        "graph_font_ax": 16,
        "graph_font_label": 16,
        "graph_font_legend": 16,
        "graph_height": 320,
        "graph_label_pad_x": 10,      # X-axis label offset from graph
        "graph_label_pad_y": 10,      # Y-axis label offset from graph
        
        # Table 1 (Team Statistics)
        "table1_header_font_size": 16,
        "table1_data_font_size": 18,
        "table1_row_height": 48,
        "table1_header_height": 30,
        "table1_icon_size": 38,
        "table1_height": 200,
        "table1_x_offset": 0,
        
        # Table 2 (Achievements)
        "table2_label_font_size": 22,
        "table2_data_font_size": 18,
        "table2_line_height": 28,
        "table2_x_data": 200,
        "table2_height": 420,
        "table1_to_table2_gap": 25,
        "table2_header_spacing": 15,
        
        # Heatmap
        "kill_heat_radius": 45,
        
        # Clock
        "clock_font_size": 40,
        "clock_margin": 20,
        "clock_box_margin": 10,
        
        # Victory screen
        "victory_font_size": 60,
        
        # Map info overlay (for cleanlog)
        "map_info_font_size": 24,
        "map_info_margin": 12,
    },
    
    "4k": {
        # Video dimensions
        "map_size": 2160,
        "killbar_width": 465,
        "stats_width": 1215,
        "total_width": 3840,
        "total_height": 2160,
        
        # Icon scales
        "icon_scale": 1.20,
        "resource_icon_scale": 0.90,
        "kill_icon_scale": 1.3,
        "kill_soldier_scale": 0.8,
        
        # Killbar settings
        "killbar_entry_height": 36,
        "killbar_icon_size": 34,
        "killbar_font_size": 22,
        "killbar_max_entries": 60,  # Full height killbar (chat moved to stats panel)
        "killbar_icon_to_name_offset": -10,  # Offset between icon and name
        
        # Chat panel settings (lower 1/3 of killbar column)
        "chat_entry_height": 30,
        "chat_font_size": 18,
        "chat_max_entries": 20,  # Fits in bottom 1/3
        "chat_name_max_chars": 15,
        
        # Kill numbers on map
        "kill_number_font_size": 22,
        "kill_number_offset_y": -45,
        "attack_line_width": 4,
        
        # Graph fonts
        "graph_font_ax": 20,
        "graph_font_label": 24,
        "graph_font_legend": 20,
        "graph_height": 480,
        "graph_label_pad_x": 15,      # X-axis label offset from graph
        "graph_label_pad_y": 15,      # Y-axis label offset from graph
        
        # Table 1 (Team Statistics)
        "table1_header_font_size": 22,
        "table1_data_font_size": 27,
        "table1_row_height": 72,
        "table1_header_height": 24,
        "table1_icon_size": 57,
        "table1_height": 310,
        "table1_x_offset": 0,
        
        # Table 2 (Achievements)
        "table2_label_font_size": 33,
        "table2_data_font_size": 27,
        "table2_line_height": 42,
        "table2_x_data": 300,
        "table2_height": 630,
        "table1_to_table2_gap": 38,
        "table2_header_spacing": 22,
        
        # Heatmap
        "kill_heat_radius": 68,
        
        # Clock
        "clock_font_size": 60,
        "clock_margin": 30,
        "clock_box_margin": 15,
        
        # Victory screen
        "victory_font_size": 90,
        
        # Map info overlay (for cleanlog)
        "map_info_font_size": 36,
        "map_info_margin": 18,
    },
}

# ============================================================
# CURRENT RESOLUTION VALUES (set by set_resolution())
# ============================================================

VIDEO_RESOLUTION = "1440p"  # Default

# Video dimensions
MAP_SIZE = 1440
KILLBAR_WIDTH = 340
STATS_WIDTH = 780
VIDEO_WIDTH = 2560
VIDEO_HEIGHT = 1440

# Icon scales
ICON_SCALE = 0.80
RESOURCE_ICON_SCALE = 0.60
KILL_ICON_SCALE = 0.8
KILL_SOLDIER_SCALE = 0.5

# Killbar
KILLBAR_ENTRY_HEIGHT = 24
KILLBAR_ICON_SIZE = 20
KILLBAR_FONT_SIZE = 12
KILLBAR_MAX_ENTRIES = 43  # Reduced to make room for chat
KILLBAR_ICON_TO_NAME_OFFSET = -8  # Offset between icon and name in killbar

# Chat panel
CHAT_ENTRY_HEIGHT = 20
CHAT_FONT_SIZE = 12
CHAT_MAX_ENTRIES = 22
CHAT_NAME_MAX_CHARS = 15

# Kill numbers
KILL_NUMBER_FONT_SIZE = 15
KILL_NUMBER_OFFSET_Y = -30
ATTACK_LINE_WIDTH = 3

# Graph fonts
Fontsize_Graphax = 12
Fontsize_Graphlabel = 14
Fontsize_Graphlegend = 12
STATS_GRAPH_HEIGHT = 320
GRAPH_LABEL_PAD_X = 10  # X-axis label offset from graph
GRAPH_LABEL_PAD_Y = 10  # Y-axis label offset from graph

# Table 1
TABLE1_HEADER_FONT_SIZE = 16
TABLE1_DATA_FONT_SIZE = 18
TABLE1_ROW_HEIGHT = 48
TABLE1_HEADER_HEIGHT = 30
TABLE1_ICON_SIZE = 38
TABLE1_HEIGHT = 200
TABLE1_X_OFFSET = 0

# Table 1 Column Widths (adjust these to change spacing)
# Columns: Units Lost, Units Killed, Bldgs Killed, Bldgs B/L, Refs/Bio B/L, HQs/Nest B/L, Tech, Nodes B/L, Commander
TABLE1_COL_WIDTHS = [55, 55, 55, 85, 85, 85, 45, 85, 90]  # Base widths before scaling

# Table 2
TABLE2_LABEL_FONT_SIZE = 22
TABLE2_DATA_FONT_SIZE = 18
TABLE2_LINE_HEIGHT = 28
TABLE2_X_DATA = 200
TABLE2_HEIGHT = 420
TABLE1_TO_TABLE2_GAP = 25
TABLE2_HEADER_SPACING = 15

# Heatmap
KILL_HEAT_RADIUS = 45

# Clock
CLOCK_FONT_SIZE = 40
CLOCK_MARGIN = 20
CLOCK_BOX_MARGIN = 10

# Victory
VICTORY_FONT_SIZE = 60

# Map info overlay (for cleanlog)
MAP_INFO_FONT_SIZE = 24
MAP_INFO_MARGIN = 12


# ============================================================
# STATIC SETTINGS (same for all resolutions)
# ============================================================

# File paths (set by launcher)
LOG_PATH = ""
MAP_PATH = ""
ICON_DIR = ""
VIDEO_OUTPUT = ""
KILL_HEATMAP_OUTPUT = ""
HEATMAP_OUTPUT = ""

# World settings
WORLD_EXTENT = 3000  # Default, will be overridden per-map

# Map-specific world extents (from Map_Scales.txt)
# Format: map_name -> world_extent
MAP_WORLD_EXTENTS = {
    "Badlands": 3000,
    "BlackIsle": 1000,
    "CrimsonPeak": 2048,
    "CrystalChasm": 1500,
    "GreatErg": 3000,
    "MonumentValley": 3000,
    "NarakaCity": 3000,
    "NorthPolarCap": 2048,
    "RiftBasin": 1500,
    "SmallStrategyTest": 500,
    "TheMaw": 1500,
    "WhisperingPlains": 2048,
}

def get_world_extent(map_name: str) -> int:
    """Get the world extent for a specific map."""
    extent = MAP_WORLD_EXTENTS.get(map_name, 3000)  # Default to 3000 if unknown
    return extent

GAMETYPE_FILTER = 'HUMANS_VS_HUMANS_VS_ALIENS'

# Video settings
FRAME_STEP = 2
VIDEO_FPS = 30
TEST_MODE = False
TEST_RENDER_FRAMES = 300

# Feature flags
ENABLE_KILLBAR = True
ENABLE_CHAT_PANEL = True  # Show chat messages below killbar
ENABLE_STATS_PANEL = True
ENABLE_KILL_ICONS = True
ENABLE_ATTACK_LINES = True
SHOW_KILL_NUMBERS_ON_MAP = True
ENABLE_VICTORY_SCREEN = True
ENABLE_RESOURCE_DISPLAY = True

# Kill icon timing (in frames)
KILL_SHOW_FRAMES = 30
KILL_FLASH_FRAMES = 3
ATTACK_LINE_DRAW_FRAMES = 30
ATTACK_LINE_FLASH_FRAMES = 3

# Derived timing (calculated)
KILL_SHOW_SECONDS = KILL_SHOW_FRAMES * FRAME_STEP
KILL_FLASH_SECONDS = KILL_FLASH_FRAMES * FRAME_STEP
ATTACK_LINE_DRAW_SECONDS = ATTACK_LINE_DRAW_FRAMES * FRAME_STEP
ATTACK_LINE_FLASH_SECONDS = ATTACK_LINE_FLASH_FRAMES * FRAME_STEP

# Building flash
DESTROY_FLASH_DURATION = 1.0

# Killbar static settings
KILLBAR_POSITION_X = 1
KILLBAR_POSITION_Y = 1
KILLBAR_NAME_MAX_CHARS = 10
KILLBAR_KILL_SYMBOL = "x"
KILLBAR_BG_ALPHA = 255
KILLBAR_SHOW_KILL_NUMBER = True
KILLBAR_SPACING_FACTORS = {
    "number_width": 3,
    "icon_to_name": -0.5,
    "name_width": 6.0,
    "name_to_symbol": 0.5,
    "symbol_width": 0.4,
    "symbol_to_icon": 0.15,
    "timestamp_gap": 0,
}

# Table 2 static settings
TABLE2_X_LABEL = 10
TABLE2_Y_START = 10
TABLE2_Y_OFFSET = 0
TABLE2_MAX_NAME_LENGTH = 15

# Table 1 column scale
col1_scale = 1.0

# Team colors
TEAM_COLORS = {
    "Sol": (50, 140, 255),
    "Centauri": (235, 70, 70),
    "Alien": (70, 220, 70),
}
GRAPH_COLORS = TEAM_COLORS
STATS_BG_COLOR = (25, 25, 25)

# Kill number color
KILL_NUMBER_COLOR = (0, 0, 0)

# Heatmap settings
KILL_HEAT_OVERLAY_ENABLED = False
KILL_HEAT_COLOR_MAP = "turbo"
KILL_HEAT_ALPHA = 0.75
HEATMAP_ALPHA = 40
HEATMAP_MAX_CLIP_PERCENT = 0.10
HEATMAP_GAMMA = 0.9
HEATMAP_MODE = "log"

# Victory screen
VICTORY_SCREEN_FRAMES = 25
VICTORY_BG_ALPHA = 180

# End-game Scoreboard
SCOREBOARD_ENABLED = True
SCOREBOARD_FRAMES = 100          # How many frames to show scoreboard (at 45fps = 10 seconds)
FREEZE_LAST_FRAME_COUNT = 30     # Freeze last gameplay frame for N frames before scoreboard (~0.67s at 45fps)
SCOREBOARD_HEADER_FONT_SIZE = 32
SCOREBOARD_TEAM_FONT_SIZE = 26
SCOREBOARD_PLAYER_FONT_SIZE = 18
SCOREBOARD_ROW_HEIGHT = 28
SCOREBOARD_TEAM_HEADER_HEIGHT = 45
SCOREBOARD_BG_ALPHA = 220
SCOREBOARD_MAX_PLAYERS_PER_TEAM = 25  # Max players to show per team

# Resource display
RESOURCE_FLASH_DURATION = 1.0
RESOURCE_COLORS = {
    "Balterium": (128, 0, 128),
    "Biotics": (255, 255, 255),
}

# Graph update interval (frames)
GRAPH_UPDATE_INTERVAL = 5


# ============================================================
# GRAPH LINE STYLES
# ============================================================

# Available line styles:
#   "solid"          - Solid line (-)
#   "dotted"         - Dotted line (:)
#   "dashed"         - Dashed line (--)
# ============================================================
# GRAPH LINE STYLES (PIL-based graphs)
# ============================================================
# Available styles for PIL graphs:
#   "solid"          - Solid line
#   "dotted"         - Regular dotted line (small dots, close together)
#   "dashed"         - Regular dashed line
#   "dashdot"        - Dash-dot line (-.)
#   "loosely_dotted" - Loosely spaced larger dots
#   "loosely_dashed" - Loosely spaced dashes (bigger gaps)
#
# Note: These are PIL-based styles, not matplotlib. The graphs use PIL for performance.

# Graph 1: Kills graph line styles and widths
GRAPH1_UNITS_KILLED_STYLE = "loosely_dotted"      # Units Killed line style
GRAPH1_UNITS_KILLED_WIDTH = 3             # Units Killed line width (pixels)
GRAPH1_BUILDINGS_KILLED_STYLE = "solid"   # Buildings Killed line style
GRAPH1_BUILDINGS_KILLED_WIDTH = 1         # Buildings Killed line width (pixels)

# Graph 2: Buildings graph line styles and widths
GRAPH2_HQ_STYLE = "solid"                 # HQ/Nest line style
GRAPH2_HQ_WIDTH = 1                       # HQ/Nest line width (pixels)
GRAPH2_REFS_STYLE = "loosely_dotted"      # Refineries/Bio line style
GRAPH2_REFS_WIDTH = 3                    # Refineries/Bio line width (pixels)

# ============================================================
# GRAPH 2 MODE SELECTION
# ============================================================
# "buildings"  - Original Buildings vs Time graph (HQ/Nest, Refs/Bio)
# "resources"  - Resource Status graph (Collected & Spent per team)
GRAPH2_MODE = "resources"

# Graph 2 (Resources mode): line styles and widths
GRAPH2_COLLECTED_STYLE = "solid"          # Collected resources line style
GRAPH2_COLLECTED_WIDTH = 2                # Collected resources line width (pixels)
GRAPH2_SPENT_STYLE = "loosely_dotted"     # Spent resources line style
GRAPH2_SPENT_WIDTH = 3                    # Spent resources line width (pixels)


# Legacy matplotlib function (kept for compatibility if USE_PIL_GRAPHS = False)
GRAPH_LINE_SPACING = 10  # Spacing factor for matplotlib "loosely" styles

def get_matplotlib_linestyle(style_name):
    """
    Convert our style names to matplotlib linestyle tuples.
    Only used if USE_PIL_GRAPHS = False in renderer.py
    
    Returns:
        tuple or str: matplotlib-compatible linestyle
    """
    spacing = GRAPH_LINE_SPACING
    
    styles = {
        "solid": "-",
        "dotted": ":",
        "dashed": "--",
        "dashdot": "-.",
        "loosely_dotted": (0, (1, spacing)),      # dot, space
        "loosely_dashed": (0, (5, spacing)),      # dash, space
        "densely_dotted": (0, (1, 1)),
        "densely_dashed": (0, (5, 1)),
    }
    
    return styles.get(style_name, "-")


# ============================================================
# LOG FORMAT SELECTION
# ============================================================

# Log format options:
#   "latestlog"  - Standard MelonLoader log format: [HH:MM:SS.mmm] ...
#   "cleanlog"   - Clean log format: L MM/DD/YYYY - HH:MM:SS: ...

LOG_FORMAT = "latestlog"  # Options: "latestlog", "cleanlog"

# Auto-generate output filename based on date, map, and gametype
# Format: YYYY-MM-DD_MapName_GameType.mp4 (e.g., 2025-12-14_GreatErg_HvH.mp4)
# Set to False to use VIDEO_OUTPUT as-is
AUTO_GENERATE_FILENAME = True


# ============================================================
# SET RESOLUTION FUNCTION
# ============================================================

def set_resolution(resolution):
    """
    Set all resolution-dependent values from the config.
    Call this once at startup before rendering.
    
    Args:
        resolution: "720p", "1080p", "1440p", or "4k"
    """
    global VIDEO_RESOLUTION
    global MAP_SIZE, KILLBAR_WIDTH, STATS_WIDTH, VIDEO_WIDTH, VIDEO_HEIGHT
    global ICON_SCALE, RESOURCE_ICON_SCALE, KILL_ICON_SCALE, KILL_SOLDIER_SCALE
    global KILLBAR_ENTRY_HEIGHT, KILLBAR_ICON_SIZE, KILLBAR_FONT_SIZE, KILLBAR_MAX_ENTRIES
    global KILLBAR_ICON_TO_NAME_OFFSET
    global CHAT_ENTRY_HEIGHT, CHAT_FONT_SIZE, CHAT_MAX_ENTRIES, CHAT_NAME_MAX_CHARS
    global KILL_NUMBER_FONT_SIZE, KILL_NUMBER_OFFSET_Y, ATTACK_LINE_WIDTH
    global Fontsize_Graphax, Fontsize_Graphlabel, Fontsize_Graphlegend, STATS_GRAPH_HEIGHT
    global GRAPH_LABEL_PAD_X, GRAPH_LABEL_PAD_Y
    global TABLE1_HEADER_FONT_SIZE, TABLE1_DATA_FONT_SIZE, TABLE1_ROW_HEIGHT
    global TABLE1_HEADER_HEIGHT, TABLE1_ICON_SIZE, TABLE1_HEIGHT, TABLE1_X_OFFSET
    global TABLE2_LABEL_FONT_SIZE, TABLE2_DATA_FONT_SIZE, TABLE2_LINE_HEIGHT
    global TABLE2_X_DATA, TABLE2_HEIGHT, TABLE1_TO_TABLE2_GAP, TABLE2_HEADER_SPACING
    global KILL_HEAT_RADIUS
    global CLOCK_FONT_SIZE, CLOCK_MARGIN, CLOCK_BOX_MARGIN
    global VICTORY_FONT_SIZE
    global MAP_INFO_FONT_SIZE, MAP_INFO_MARGIN
    
    if resolution not in RESOLUTION_CONFIGS:
        raise ValueError(f"Invalid resolution: {resolution}. Choose from: {list(RESOLUTION_CONFIGS.keys())}")
    
    VIDEO_RESOLUTION = resolution
    cfg = RESOLUTION_CONFIGS[resolution]
    
    # Video dimensions
    MAP_SIZE = cfg["map_size"]
    KILLBAR_WIDTH = cfg["killbar_width"]
    STATS_WIDTH = cfg["stats_width"]
    VIDEO_WIDTH = cfg["total_width"]
    VIDEO_HEIGHT = cfg["total_height"]
    
    # Icon scales
    ICON_SCALE = cfg["icon_scale"]
    RESOURCE_ICON_SCALE = cfg["resource_icon_scale"]
    KILL_ICON_SCALE = cfg["kill_icon_scale"]
    KILL_SOLDIER_SCALE = cfg["kill_soldier_scale"]
    
    # Killbar
    KILLBAR_ENTRY_HEIGHT = cfg["killbar_entry_height"]
    KILLBAR_ICON_SIZE = cfg["killbar_icon_size"]
    KILLBAR_FONT_SIZE = cfg["killbar_font_size"]
    KILLBAR_MAX_ENTRIES = cfg["killbar_max_entries"]
    KILLBAR_ICON_TO_NAME_OFFSET = cfg.get("killbar_icon_to_name_offset", -6)
    
    # Chat panel
    CHAT_ENTRY_HEIGHT = cfg.get("chat_entry_height", 20)
    CHAT_FONT_SIZE = cfg.get("chat_font_size", 12)
    CHAT_MAX_ENTRIES = cfg.get("chat_max_entries", 20)
    CHAT_NAME_MAX_CHARS = cfg.get("chat_name_max_chars", 15)
    
    # Kill numbers
    KILL_NUMBER_FONT_SIZE = cfg["kill_number_font_size"]
    KILL_NUMBER_OFFSET_Y = cfg["kill_number_offset_y"]
    ATTACK_LINE_WIDTH = cfg["attack_line_width"]
    
    # Graph fonts
    Fontsize_Graphax = cfg["graph_font_ax"]
    Fontsize_Graphlabel = cfg["graph_font_label"]
    Fontsize_Graphlegend = cfg["graph_font_legend"]
    STATS_GRAPH_HEIGHT = cfg["graph_height"]
    GRAPH_LABEL_PAD_X = cfg.get("graph_label_pad_x", 8)
    GRAPH_LABEL_PAD_Y = cfg.get("graph_label_pad_y", 8)
    
    # Table 1
    TABLE1_HEADER_FONT_SIZE = cfg["table1_header_font_size"]
    TABLE1_DATA_FONT_SIZE = cfg["table1_data_font_size"]
    TABLE1_ROW_HEIGHT = cfg["table1_row_height"]
    TABLE1_HEADER_HEIGHT = cfg["table1_header_height"]
    TABLE1_ICON_SIZE = cfg["table1_icon_size"]
    TABLE1_HEIGHT = cfg["table1_height"]
    TABLE1_X_OFFSET = cfg["table1_x_offset"]
    
    # Table 2
    TABLE2_LABEL_FONT_SIZE = cfg["table2_label_font_size"]
    TABLE2_DATA_FONT_SIZE = cfg["table2_data_font_size"]
    TABLE2_LINE_HEIGHT = cfg["table2_line_height"]
    TABLE2_X_DATA = cfg["table2_x_data"]
    TABLE2_HEIGHT = cfg["table2_height"]
    TABLE1_TO_TABLE2_GAP = cfg["table1_to_table2_gap"]
    TABLE2_HEADER_SPACING = cfg["table2_header_spacing"]
    
    # Heatmap
    KILL_HEAT_RADIUS = cfg["kill_heat_radius"]
    
    # Clock
    CLOCK_FONT_SIZE = cfg["clock_font_size"]
    CLOCK_MARGIN = cfg["clock_margin"]
    CLOCK_BOX_MARGIN = cfg["clock_box_margin"]
    
    # Victory
    VICTORY_FONT_SIZE = cfg["victory_font_size"]
    
    # Map info overlay (for cleanlog)
    MAP_INFO_FONT_SIZE = cfg.get("map_info_font_size", 20)
    MAP_INFO_MARGIN = cfg.get("map_info_margin", 10)
    
    print(f"Resolution set to {resolution}: {VIDEO_WIDTH}x{VIDEO_HEIGHT}")


def get_scale_ratio():
    """
    Get a simple scale ratio based on current resolution.
    Useful for misc scaling not covered by explicit config values.
    Base is 1440p = 1.0
    """
    ratios = {"720p": 0.5, "1080p": 0.75, "1440p": 1.0, "4k": 1.5}
    return ratios.get(VIDEO_RESOLUTION, 1.0)


def recalculate_timing():
    """Recalculate timing values after FRAME_STEP changes."""
    global KILL_SHOW_SECONDS, KILL_FLASH_SECONDS
    global ATTACK_LINE_DRAW_SECONDS, ATTACK_LINE_FLASH_SECONDS
    
    KILL_SHOW_SECONDS = KILL_SHOW_FRAMES * FRAME_STEP
    KILL_FLASH_SECONDS = KILL_FLASH_FRAMES * FRAME_STEP
    ATTACK_LINE_DRAW_SECONDS = ATTACK_LINE_DRAW_FRAMES * FRAME_STEP
    ATTACK_LINE_FLASH_SECONDS = ATTACK_LINE_FLASH_FRAMES * FRAME_STEP


def print_current_settings():
    """Print current resolution settings for debugging."""
    print(f"\n=== Current Settings ({VIDEO_RESOLUTION}) ===")
    print(f"Video: {VIDEO_WIDTH}x{VIDEO_HEIGHT}")
    print(f"Map size: {MAP_SIZE}")
    print(f"Icon scale: {ICON_SCALE}")
    print(f"Killbar font: {KILLBAR_FONT_SIZE}, icon: {KILLBAR_ICON_SIZE}")
    print(f"Graph fonts: ax={Fontsize_Graphax}, label={Fontsize_Graphlabel}, legend={Fontsize_Graphlegend}")
    print(f"Table1 fonts: header={TABLE1_HEADER_FONT_SIZE}, data={TABLE1_DATA_FONT_SIZE}")
    print(f"Table2 fonts: label={TABLE2_LABEL_FONT_SIZE}, data={TABLE2_DATA_FONT_SIZE}")
    print()


if __name__ == "__main__":
    print("Config Module - Resolution Test")
    for res in ["720p", "1080p", "1440p", "4k"]:
        set_resolution(res)
        print_current_settings()
