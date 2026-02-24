# -*- coding: utf-8 -*-
"""
Renderer Module

All rendering functions for video frames, killbar, stats panels, graphs.
"""

import os
import math
from collections import defaultdict
import numpy as np
# Note: matplotlib is imported conditionally only when USE_PIL_GRAPHS = False
# This saves memory and startup time when using PIL-based graphs (default)
from PIL import Image, ImageDraw, ImageFont

import config  # Import module for dynamic access to resolution-dependent values
from config import (
    WORLD_EXTENT,
    TEAM_COLORS, GRAPH_COLORS, STATS_BG_COLOR,
    ENABLE_KILLBAR, KILLBAR_POSITION_X, KILLBAR_POSITION_Y,
    KILLBAR_NAME_MAX_CHARS, KILLBAR_KILL_SYMBOL,
    KILLBAR_BG_ALPHA, KILLBAR_SHOW_KILL_NUMBER, KILLBAR_SPACING_FACTORS,
    ENABLE_STATS_PANEL, ENABLE_KILL_ICONS, ENABLE_ATTACK_LINES,
    ENABLE_CHAT_PANEL,
    SHOW_KILL_NUMBERS_ON_MAP, KILL_NUMBER_COLOR,
    KILL_SHOW_SECONDS, KILL_FLASH_SECONDS,
    ATTACK_LINE_DRAW_SECONDS, ATTACK_LINE_FLASH_SECONDS,
    DESTROY_FLASH_DURATION,
    col1_scale,
    TABLE2_X_LABEL, TABLE2_Y_START, TABLE2_Y_OFFSET,
    TABLE2_MAX_NAME_LENGTH,
    HEATMAP_ALPHA
)
# NOTE: These values are resolution-dependent and must be accessed via config.VARIABLE:
# config.KILLBAR_WIDTH, config.STATS_WIDTH, config.VIDEO_HEIGHT, config.VIDEO_WIDTH, config.MAP_SIZE
# config.KILLBAR_MAX_ENTRIES, config.KILLBAR_ENTRY_HEIGHT, config.KILLBAR_ICON_SIZE, config.KILLBAR_FONT_SIZE
# config.ICON_SCALE, config.RESOURCE_ICON_SCALE, config.KILL_ICON_SCALE, config.KILL_SOLDIER_SCALE
# config.KILL_NUMBER_FONT_SIZE, config.KILL_NUMBER_OFFSET_Y, config.ATTACK_LINE_WIDTH
# TABLE1_*, TABLE2_*, Fontsize_Graph*

from icon_config import get_icon, get_resource_icon, normalize_unit_name, is_soldier, is_ai_unit
from log_parser import world_to_pixel


# Helper to get resolution-dependent values
def get_killbar_font_size():
    return config.KILLBAR_FONT_SIZE

def get_killbar_icon_size():
    return config.KILLBAR_ICON_SIZE

def get_icon_scale():
    return config.ICON_SCALE


# Team prefixes to strip from AI unit names in killbar
_TEAM_PREFIXES = ("Sol_", "Cent_", "Alien_")

def _clean_killbar_name(name):
    """Strip team prefixes from AI unit names for cleaner killbar display."""
    for prefix in _TEAM_PREFIXES:
        if name.startswith(prefix):
            return name[len(prefix):]
    return name

def _filter_kills_for_killbar(kills, current_time):
    """Filter and clean kills for killbar display (no structure kills)."""
    past_kills = [k for k in kills if k.time <= current_time and not k.is_structure]
    return sorted(past_kills, key=lambda k: k.time, reverse=True)


def load_font(size: int):
    try:
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        return ImageFont.load_default()

# Font cache to avoid reloading fonts every frame
_font_cache = {}

def get_cached_font(size: int):
    """Get a cached font to avoid reloading every frame."""
    if size not in _font_cache:
        _font_cache[size] = load_font(size)
    return _font_cache[size]


# ============================================================
# CACHING SYSTEM FOR PERFORMANCE
# ============================================================

class KillbarScrollBuffer:
    """
    Optimized killbar rendering using scroll buffer technique.
    
    Instead of re-rendering all 60 entries every time a kill happens,
    we shift the existing image down and only render the new entry.
    
    Performance:
    - No new kill: ~0.1ms (return cached image)
    - One new kill: ~3ms (shift + render 1 entry)
    - Full rebuild: ~35ms (only when needed)
    """
    
    def __init__(self):
        self.buffer_image = None
        self.width = 0
        self.height = 0
        self.last_kill_count = 0
        self.last_kill_ids = []  # Track which kills are in buffer
        self._cached_font_size = None  # Track if font size changed
    
    @property
    def entry_height(self):
        """Read entry height dynamically from config."""
        return config.KILLBAR_ENTRY_HEIGHT
    
    @property
    def max_entries(self):
        """Read max entries dynamically from config."""
        return config.KILLBAR_MAX_ENTRIES
    
    @property
    def spacing(self):
        """Calculate spacing dynamically based on current font size."""
        fs = config.KILLBAR_FONT_SIZE
        sp = KILLBAR_SPACING_FACTORS
        return {
            'number_width': int(fs * sp["number_width"]),
            'icon_to_name': int(fs * sp["icon_to_name"]),
            'name_width': int(fs * sp["name_width"]),
            'name_to_symbol': int(fs * sp["name_to_symbol"]),
            'symbol_width': int(fs * sp["symbol_width"]),
            'symbol_to_icon': int(fs * sp["symbol_to_icon"]),
            'timestamp_gap': int(fs * sp["timestamp_gap"]),
        }
    
    def get_killbar(self, kills, current_time, width, height):
        """
        Get killbar image using scroll buffer optimization.
        
        Returns:
            PIL Image of the killbar panel
        """
        if not ENABLE_KILLBAR or not kills:
            if self.buffer_image is None or self.width != width or self.height != height:
                # Create panel with full black background
                self.buffer_image = Image.new("RGBA", (width, height), (20, 20, 20, 255))
                draw = ImageDraw.Draw(self.buffer_image, "RGBA")
                x_start = KILLBAR_POSITION_X
                bg_width = width - (KILLBAR_POSITION_X * 2)
                # Draw full-height black background
                draw.rectangle([(x_start, KILLBAR_POSITION_Y), (x_start + bg_width, height - KILLBAR_POSITION_Y)], 
                              fill=(0, 0, 0, KILLBAR_BG_ALPHA))
                self.width = width
                self.height = height
            return self.buffer_image
        
        # Check if dimensions changed
        if self.width != width or self.height != height:
            self.buffer_image = None
            self.width = width
            self.height = height
        
        # FAST PATH: Check if any new kills since last check
        # Count non-structure kills up to current_time
        current_kill_count = 0
        for k in kills:
            if k.time <= current_time:
                if not k.is_structure:
                    current_kill_count += 1
            else:
                break

        # If no new kills and we have a buffer, return cached
        if (self.buffer_image is not None and
            current_kill_count == self.last_kill_count):
            return self.buffer_image

        # New kills detected - need to process
        # Get current kills (sorted by time, most recent first), excluding structures
        recent_kills = _filter_kills_for_killbar(kills, current_time)[:self.max_entries]
        current_kill_ids = [k.kill_number for k in recent_kills]
        
        # CASE 1: No change in visible kills - return cached
        if (self.buffer_image is not None and 
            current_kill_ids == self.last_kill_ids):
            self.last_kill_count = current_kill_count
            return self.buffer_image
        
        # CASE 2: One new kill at the top (at max capacity) - shift and add
        if (self.buffer_image is not None and 
            len(current_kill_ids) == self.max_entries and
            len(self.last_kill_ids) == self.max_entries and
            current_kill_ids[1:] == self.last_kill_ids[:-1]):
            # New kill added at top, bottom one fell off
            new_kill = recent_kills[0]
            self._shift_and_add(new_kill, len(recent_kills))
            self.last_kill_ids = current_kill_ids
            self.last_kill_count = current_kill_count
            return self.buffer_image
        
        # CASE 3: One new kill, list growing (not yet at max)
        if (self.buffer_image is not None and
            len(current_kill_ids) > 0 and
            len(self.last_kill_ids) > 0 and
            len(current_kill_ids) == len(self.last_kill_ids) + 1 and
            len(current_kill_ids) <= self.max_entries and
            current_kill_ids[1:] == self.last_kill_ids):
            # New kill added at top, nothing fell off
            new_kill = recent_kills[0]
            self._shift_and_add(new_kill, len(recent_kills))
            self.last_kill_ids = current_kill_ids
            self.last_kill_count = current_kill_count
            return self.buffer_image
        
        # CASE 4: Full rebuild needed
        self._full_rebuild(recent_kills, width, height)
        self.last_kill_ids = current_kill_ids
        self.last_kill_count = current_kill_count
        return self.buffer_image
    
    def _shift_and_add(self, new_kill, total_entries):
        """Shift existing content down and add new entry at top."""
        # Calculate content area
        x_start = KILLBAR_POSITION_X
        y_start = KILLBAR_POSITION_Y
        content_start_y = y_start + 5
        
        # Crop the old entries (excluding the bottom one if at max)
        old_content_height = (total_entries - 1) * self.entry_height
        
        if old_content_height > 0 and self.buffer_image is not None:
            # Crop region that will be kept (all but bottom entry)
            old_region = self.buffer_image.crop((
                0,
                content_start_y,
                self.width,
                content_start_y + old_content_height
            ))
            
            # Create new buffer with background
            new_buffer = Image.new("RGBA", (self.width, self.height), (20, 20, 20, 255))
            
            # Draw background - full height
            bg_width = self.width - (KILLBAR_POSITION_X * 2)
            draw = ImageDraw.Draw(new_buffer, "RGBA")
            draw.rectangle([(x_start, y_start), (x_start + bg_width, self.height - KILLBAR_POSITION_Y)], 
                          fill=(0, 0, 0, KILLBAR_BG_ALPHA))
            
            # Paste old content shifted down
            new_buffer.paste(old_region, (0, content_start_y + self.entry_height))
            
            self.buffer_image = new_buffer
        else:
            # First entry or empty - create new buffer
            self.buffer_image = Image.new("RGBA", (self.width, self.height), (20, 20, 20, 255))
            bg_width = self.width - (KILLBAR_POSITION_X * 2)
            draw = ImageDraw.Draw(self.buffer_image, "RGBA")
            draw.rectangle([(x_start, y_start), (x_start + bg_width, self.height - KILLBAR_POSITION_Y)], 
                          fill=(0, 0, 0, KILLBAR_BG_ALPHA))
        
        # Render only the new entry at top
        self._render_single_entry(self.buffer_image, new_kill, content_start_y)
    
    def _render_single_entry(self, panel, kill, y_pos):
        """Render a single kill entry at the specified y position."""
        draw = ImageDraw.Draw(panel, "RGBA")
        font = get_cached_font(config.KILLBAR_FONT_SIZE)
        number_font = get_cached_font(config.KILLBAR_FONT_SIZE)
        
        x_start = KILLBAR_POSITION_X
        x_pos = x_start + 5
        
        sp = self.spacing
        
        # Kill number
        if KILLBAR_SHOW_KILL_NUMBER:
            kill_num_str = f"#{kill.kill_number}"
            draw.text((x_pos, y_pos + self.entry_height // 2), kill_num_str, 
                     font=number_font, fill=(200, 200, 200, 255), anchor="lm")
            x_pos += sp['number_width']
        
        # Attacker Icon
        attacker_icon = get_icon(kill.attacker_unit, kill.attacker_team, "complete", config.KILLBAR_ICON_SIZE / 64.0)
        if attacker_icon:
            icon_y = y_pos + (self.entry_height - attacker_icon.height) // 2
            panel.alpha_composite(attacker_icon, (x_pos, icon_y))
        x_pos += config.KILLBAR_ICON_SIZE + sp['icon_to_name']
        
        # Attacker name (strip team prefixes from AI names)
        attacker_name = _clean_killbar_name(kill.attacker_name)[:KILLBAR_NAME_MAX_CHARS]
        attacker_color = TEAM_COLORS.get(kill.attacker_team, (255, 255, 255))
        draw.text((x_pos, y_pos + self.entry_height // 2), attacker_name,
                 font=font, fill=(*attacker_color, 255), anchor="lm")
        x_pos += sp['name_width'] + sp['name_to_symbol']

        # Kill symbol
        draw.text((x_pos, y_pos + self.entry_height // 2), KILLBAR_KILL_SYMBOL,
                 font=font, fill=(255, 255, 255, 255), anchor="lm")
        x_pos += sp['symbol_width'] + sp['symbol_to_icon']

        # Victim Icon
        victim_icon = get_icon(kill.victim_unit, kill.victim_team, "complete", config.KILLBAR_ICON_SIZE / 64.0)
        if victim_icon:
            icon_y = y_pos + (self.entry_height - victim_icon.height) // 2
            panel.alpha_composite(victim_icon, (x_pos, icon_y))
        x_pos += config.KILLBAR_ICON_SIZE + sp['icon_to_name']

        # Victim name (strip team prefixes from AI names)
        victim_name = _clean_killbar_name(kill.victim_name)[:KILLBAR_NAME_MAX_CHARS]
        victim_color = TEAM_COLORS.get(kill.victim_team, (255, 255, 255))
        draw.text((x_pos, y_pos + self.entry_height // 2), victim_name, 
                 font=font, fill=(*victim_color, 255), anchor="lm")
        x_pos += sp['name_width'] + sp['timestamp_gap']
        
        # Timestamp
        minutes = int(kill.time // 60)
        seconds = int(kill.time % 60)
        timestamp_str = f"{minutes:02d}:{seconds:02d}"
        draw.text((x_pos, y_pos + self.entry_height // 2), timestamp_str, 
                 font=number_font, fill=(180, 180, 180, 255), anchor="lm")
    
    def _full_rebuild(self, recent_kills, width, height):
        """Full rebuild of killbar (fallback)."""
        self.buffer_image = render_killbar_cached(
            # We need to pass kills that will result in recent_kills
            # But render_killbar_cached filters itself, so we create a wrapper
            recent_kills, 
            float('inf'),  # current_time = infinity so all passed kills are included
            width, 
            height,
            pre_sorted=True  # Flag to skip re-sorting
        )
    
    def clear(self):
        """Clear the buffer completely for new game."""
        self.buffer_image = None
        self.width = 0
        self.height = 0
        self.last_kill_count = 0
        self.last_kill_ids = []
        self._cached_font_size = None


class ChatScrollBuffer:
    """
    Optimized chat panel rendering using scroll buffer technique.
    Similar to KillbarScrollBuffer but for chat messages.
    
    Since every line has the same entry_height, we treat multi-line messages
    as multiple single-height lines. This simplifies shift-and-add operations.
    """
    
    # Top margin for separation from killbar
    TOP_MARGIN = 15
    
    def __init__(self):
        self.buffer_image = None
        self.width = 0
        self.height = 0
        self.last_chat_count = 0
        self.last_chat_ids = []  # Track message times for change detection
        self.total_visible_lines = 0  # Total lines currently displayed (simpler than per-message tracking)
    
    @property
    def entry_height(self):
        """Read entry height dynamically from config."""
        return config.CHAT_ENTRY_HEIGHT
    
    @property
    def max_entries(self):
        """Read max entries dynamically from config."""
        return config.CHAT_MAX_ENTRIES
    
    def get_chat_panel(self, chat_messages, current_time, width, height, y_offset):
        """
        Get chat panel image using scroll buffer optimization.
        
        Args:
            chat_messages: List of ChatMessage namedtuples
            current_time: Current game time
            width: Panel width
            height: Panel height (for the chat area, typically 1/3 of killbar column)
            y_offset: Y position where the chat panel starts
        
        Returns:
            PIL Image of the chat panel
        """
        if not ENABLE_CHAT_PANEL or not chat_messages:
            if self.buffer_image is None or self.width != width or self.height != height:
                # Create panel with stats panel background color
                self.buffer_image = Image.new("RGBA", (width, height), (*STATS_BG_COLOR, 255))
                draw = ImageDraw.Draw(self.buffer_image, "RGBA")
                x_start = 5  # Small margin
                # Draw CHAT header with top margin (bigger font)
                header_font = get_cached_font(config.CHAT_FONT_SIZE + 4)
                draw.text((x_start, self.TOP_MARGIN), "CHAT", font=header_font, fill=(255, 255, 255, 255))
                self.width = width
                self.height = height
            return self.buffer_image
        
        # Check if dimensions changed
        if self.width != width or self.height != height:
            self.buffer_image = None
            self.width = width
            self.height = height
            self.last_chat_ids = []
            self.total_visible_lines = 0
        
        # Count chat messages up to current_time
        current_chat_count = 0
        for msg in chat_messages:
            if msg.time <= current_time:
                current_chat_count += 1
            else:
                break
        
        # If no new chats and we have a buffer, return cached
        if (self.buffer_image is not None and 
            current_chat_count == self.last_chat_count):
            return self.buffer_image
        
        # Get current messages
        past_chats = chat_messages[:current_chat_count]
        recent_chats = list(reversed(past_chats))[:self.max_entries]
        current_chat_ids = [c.time for c in recent_chats]
        
        # CASE 1: No change in visible chats - return cached
        if (self.buffer_image is not None and 
            current_chat_ids == self.last_chat_ids):
            self.last_chat_count = current_chat_count
            return self.buffer_image
        
        # CASE 2: One new chat at top - try shift and add
        if (self.buffer_image is not None and 
            len(current_chat_ids) > 0 and
            len(self.last_chat_ids) > 0):
            
            # Check if it's just one new message added (nothing fell off or one fell off)
            is_simple_add = (len(current_chat_ids) == len(self.last_chat_ids) + 1 and
                            current_chat_ids[1:] == self.last_chat_ids)
            is_add_with_drop = (len(current_chat_ids) == len(self.last_chat_ids) and
                               current_chat_ids[1:] == self.last_chat_ids[:-1])
            
            if is_simple_add or is_add_with_drop:
                new_chat = recent_chats[0]
                new_lines = self._shift_and_add(new_chat, width, height)
                if new_lines > 0:
                    self.last_chat_ids = current_chat_ids
                    self.last_chat_count = current_chat_count
                    # Update total lines (add new, content is auto-clipped by buffer height)
                    self.total_visible_lines = min(
                        self.total_visible_lines + new_lines,
                        self._max_visible_lines(height)
                    )
                    return self.buffer_image
        
        # CASE 3: Full rebuild needed
        self._full_rebuild(recent_chats, width, height)
        self.last_chat_ids = current_chat_ids
        self.last_chat_count = current_chat_count
        
        return self.buffer_image
    
    def _max_visible_lines(self, height):
        """Calculate maximum lines that can fit in the panel."""
        content_height = height - self.TOP_MARGIN - self.entry_height  # Minus header
        return max(1, content_height // self.entry_height)
    
    def _calc_message_lines(self, chat):
        """Calculate how many lines a message will need."""
        # Calculate line widths (same logic as _render_single_entry)
        x_start = 5  # Small margin for chat in stats panel
        
        # Get font for measurements
        font = get_cached_font(config.CHAT_FONT_SIZE)
        
        # Measure timestamp width
        timestamp_str = "00:00"
        ts_bbox = font.getbbox(timestamp_str)
        timestamp_width = ts_bbox[2] - ts_bbox[0] + 5  # Add small gap
        name_x = x_start + timestamp_width
        
        player_name = chat.player_name[:config.CHAT_NAME_MAX_CHARS]
        if chat.is_team_chat:
            name_display = f"[T]{player_name}"
        else:
            name_display = player_name
        
        # Measure actual name width
        name_bbox = font.getbbox(name_display)
        name_width = name_bbox[2] - name_bbox[0]
        msg_x = name_x + name_width + 2  # Small gap before colon
        
        first_line_width = self.width - msg_x - 5  # 5px margin on right
        continuation_width = self.width - name_x - 5
        
        char_width = config.CHAT_FONT_SIZE * 0.55
        first_line_chars = max(10, int(first_line_width / char_width))
        continuation_chars = max(10, int(continuation_width / char_width))
        
        message = f": {chat.message}"
        lines = self._wrap_text(message, first_line_chars, continuation_chars)
        return len(lines)
    
    def _shift_and_add(self, new_chat, width, height):
        """
        Shift existing content down and add new entry at top.
        
        Returns:
            Number of lines used by new entry, or 0 if shift failed
        """
        x_start = 5  # Small margin for chat in stats panel
        content_start_y = self.TOP_MARGIN + self.entry_height  # After header
        
        # Calculate how many lines the new message needs
        new_lines = self._calc_message_lines(new_chat)
        shift_amount = new_lines * self.entry_height
        
        # Calculate current content height (all lines have same height)
        old_content_height = self.total_visible_lines * self.entry_height
        
        if old_content_height > 0 and self.buffer_image is not None:
            # Crop existing content
            old_region = self.buffer_image.crop((
                0,
                content_start_y,
                self.width,
                min(content_start_y + old_content_height, height)
            ))
            
            # Create new buffer with stats panel background
            new_buffer = Image.new("RGBA", (self.width, self.height), (*STATS_BG_COLOR, 255))
            draw = ImageDraw.Draw(new_buffer, "RGBA")
            
            # Draw CHAT header (bigger font)
            header_font = get_cached_font(config.CHAT_FONT_SIZE + 4)
            draw.text((x_start, self.TOP_MARGIN), "CHAT", font=header_font, fill=(255, 255, 255, 255))
            
            # Paste old content shifted down (clipped by buffer bounds automatically)
            new_buffer.paste(old_region, (0, content_start_y + shift_amount))
            
            self.buffer_image = new_buffer
        else:
            # First entry - create new buffer
            self.buffer_image = Image.new("RGBA", (self.width, self.height), (*STATS_BG_COLOR, 255))
            draw = ImageDraw.Draw(self.buffer_image, "RGBA")
            header_font = get_cached_font(config.CHAT_FONT_SIZE + 4)
            draw.text((x_start, self.TOP_MARGIN), "CHAT", font=header_font, fill=(255, 255, 255, 255))
        
        # Render the new message at top
        draw = ImageDraw.Draw(self.buffer_image, "RGBA")
        font = get_cached_font(config.CHAT_FONT_SIZE)
        self._render_single_entry(draw, new_chat, x_start, content_start_y, font, height)
        
        return new_lines
    
    def _full_rebuild(self, recent_chats, width, height):
        """Full rebuild of chat panel."""
        self.buffer_image = Image.new("RGBA", (width, height), (*STATS_BG_COLOR, 255))
        
        draw = ImageDraw.Draw(self.buffer_image, "RGBA")
        font = get_cached_font(config.CHAT_FONT_SIZE)
        
        x_start = 5  # Small margin for chat in stats panel
        y_start = self.TOP_MARGIN  # Use top margin for separation
        
        # Draw header (bigger font)
        header_font = get_cached_font(config.CHAT_FONT_SIZE + 4)
        draw.text((x_start, y_start), "CHAT", font=header_font, fill=(255, 255, 255, 255))
        
        if not recent_chats:
            self.total_visible_lines = 0
            return
        
        y_current = y_start + self.entry_height
        total_lines = 0
        
        # Render each chat message
        for chat in recent_chats:
            if y_current + self.entry_height > height:
                break
            
            lines_used = self._render_single_entry(draw, chat, x_start, y_current, font, height)
            total_lines += lines_used
            y_current += self.entry_height * lines_used
        
        self.total_visible_lines = total_lines
    
    def _render_single_entry(self, draw, chat, x_pos, y_pos, font, max_height):
        """
        Render a single chat entry with text wrapping.
        
        Returns:
            Number of lines used by this entry
        """
        # Timestamp
        minutes = int(chat.time // 60)
        seconds = int(chat.time % 60)
        timestamp_str = f"{minutes:02d}:{seconds:02d}"
        draw.text((x_pos, y_pos), timestamp_str, font=font, fill=(150, 150, 150, 255))
        
        # Calculate timestamp width using actual text measurement
        ts_bbox = draw.textbbox((0, 0), timestamp_str, font=font)
        timestamp_width = ts_bbox[2] - ts_bbox[0] + 5  # Add small gap after timestamp
        name_x = x_pos + timestamp_width
        
        # Player name (truncated to CHAT_NAME_MAX_CHARS)
        player_name = chat.player_name[:config.CHAT_NAME_MAX_CHARS]
        team_color = TEAM_COLORS.get(chat.team, (255, 255, 255))
        
        # Add team chat indicator
        if chat.is_team_chat:
            name_display = f"[T]{player_name}"
        else:
            name_display = player_name
        
        draw.text((name_x, y_pos), name_display, font=font, fill=(*team_color, 255))
        
        # Calculate actual name width using text measurement
        name_bbox = draw.textbbox((0, 0), name_display, font=font)
        name_width = name_bbox[2] - name_bbox[0]
        msg_x = name_x + name_width + 2  # Small gap before colon
        
        # Calculate available width for message on first line
        first_line_width = self.width - msg_x - 5  # 5px margin on right
        # Continuation lines start at name_x position (aligned with player name)
        continuation_width = self.width - name_x - 5
        
        char_width = config.CHAT_FONT_SIZE * 0.55  # Approximate character width
        first_line_chars = max(10, int(first_line_width / char_width))
        continuation_chars = max(10, int(continuation_width / char_width))
        
        # Wrap message text
        message = f": {chat.message}"
        lines = self._wrap_text(message, first_line_chars, continuation_chars)
        
        # Draw wrapped lines
        lines_used = 1
        for i, line in enumerate(lines):
            line_y = y_pos + (i * self.entry_height)
            
            # Check if we have space for this line
            if line_y + self.entry_height > max_height:
                break
            
            if i == 0:
                # First line starts at message position (after player name)
                draw.text((msg_x, line_y), line, font=font, fill=(220, 220, 220, 255))
            else:
                # Continuation lines start at name_x (aligned with player name)
                draw.text((name_x, line_y), line, font=font, fill=(200, 200, 200, 255))
                lines_used += 1
        
        return lines_used
    
    def _wrap_text(self, text, first_line_chars, continuation_chars):
        """
        Wrap text into lines with different width for first and continuation lines.
        Uses hyphen when breaking words.
        
        Args:
            text: Text to wrap
            first_line_chars: Max characters for first line
            continuation_chars: Max characters for continuation lines
        """
        if len(text) <= first_line_chars:
            return [text]
        
        lines = []
        remaining = text
        is_first_line = True
        
        while remaining:
            max_chars = first_line_chars if is_first_line else continuation_chars
            
            if len(remaining) <= max_chars:
                lines.append(remaining)
                break
            
            # Find a good break point
            break_point = max_chars
            use_hyphen = False
            
            # Look for a space to break at (search backwards from max_chars)
            space_pos = remaining.rfind(' ', 0, max_chars)
            if space_pos > max_chars * 0.4:  # Only use space if it's not too early
                break_point = space_pos
            else:
                # No good space found - break word with hyphen
                break_point = max_chars - 1  # Leave room for hyphen
                use_hyphen = True
            
            if use_hyphen:
                lines.append(remaining[:break_point] + "-")
                remaining = remaining[break_point:]
            else:
                lines.append(remaining[:break_point].rstrip())
                remaining = remaining[break_point:].lstrip()
            
            is_first_line = False
            
            # Limit to reasonable number of lines (prevent runaway)
            if len(lines) >= 4:
                if remaining:
                    lines[-1] = lines[-1][:max(0, len(lines[-1])-2)] + ".."
                break
        
        return lines
    
    def clear(self):
        """Clear the buffer completely for new game."""
        self.buffer_image = None
        self.width = 0
        self.height = 0
        self.last_chat_count = 0
        self.last_chat_ids = []
        self.total_visible_lines = 0


class RenderCache:
    """Cache for expensive render operations."""
    
    def __init__(self):
        self.stats_panel = None
        self.stats_panel_frame = -1
        
        # Use new scroll buffer for killbar
        self.killbar_buffer = KillbarScrollBuffer()
        
        # Use scroll buffer for chat panel
        self.chat_buffer = ChatScrollBuffer()
        
        # Cache hit statistics
        self.stats_hits = 0
        self.stats_misses = 0
        self.killbar_hits = 0
        self.killbar_misses = 0
        self.killbar_shifts = 0  # New: track shift operations
        self.killbar_rebuilds = 0  # New: track full rebuilds
        
    def get_stats_panel(self, frame_num, kill_stats, building_stats, player_stats, 
                        unit_kill_stats, commanders, current_time, width, height, update_interval, resource_stats=None):
        """Get cached or regenerate stats panel."""
        # Check if we need to update
        should_update = (
            self.stats_panel is None or
            frame_num == 0 or
            (frame_num - self.stats_panel_frame) >= update_interval
        )
        
        if should_update:
            self.stats_panel = render_stats_panel_impl(
                kill_stats, building_stats, player_stats, 
                unit_kill_stats, commanders, current_time, width, height,
                resource_stats=resource_stats
            )
            self.stats_panel_frame = frame_num
            self.stats_misses += 1
        else:
            self.stats_hits += 1
        
        return self.stats_panel
    
    def get_killbar(self, frame_num, kills, current_time, width, height, map_width, update_interval=1):
        """Get killbar using optimized scroll buffer."""
        old_count = self.killbar_buffer.last_kill_count
        old_ids = self.killbar_buffer.last_kill_ids.copy() if self.killbar_buffer.last_kill_ids else []
        
        result = self.killbar_buffer.get_killbar(kills, current_time, width, height)
        
        new_count = self.killbar_buffer.last_kill_count
        new_ids = self.killbar_buffer.last_kill_ids
        
        # Track what happened
        if old_ids == new_ids:
            self.killbar_hits += 1
        elif len(new_ids) == len(old_ids) + 1 or (len(old_ids) > 0 and len(new_ids) > 0 and new_ids[1:] == old_ids[:-1]):
            self.killbar_shifts += 1
        else:
            self.killbar_rebuilds += 1
        
        return result
    
    def get_chat_panel(self, chat_messages, current_time, width, height, y_offset):
        """Get chat panel using scroll buffer."""
        return self.chat_buffer.get_chat_panel(chat_messages, current_time, width, height, y_offset)
    
    def clear(self):
        """Clear all caches for new game."""
        global _font_cache
        self.stats_panel = None
        self.stats_panel_frame = -1
        self.killbar_buffer.clear()
        self.chat_buffer.clear()
        self.stats_hits = 0
        self.stats_misses = 0
        self.killbar_hits = 0
        self.killbar_misses = 0
        self.killbar_shifts = 0
        self.killbar_rebuilds = 0
        # Clear font cache to ensure fresh fonts for new game
        _font_cache.clear()
    
    def print_stats(self):
        """Print cache hit/miss statistics."""
        total_stats = self.stats_hits + self.stats_misses
        total_killbar = self.killbar_hits + self.killbar_shifts + self.killbar_rebuilds
        
        if total_stats > 0:
            stats_rate = self.stats_hits / total_stats * 100
        else:
            stats_rate = 0
            
        if total_killbar > 0:
            killbar_hit_rate = self.killbar_hits / total_killbar * 100
            killbar_shift_rate = self.killbar_shifts / total_killbar * 100
            killbar_rebuild_rate = self.killbar_rebuilds / total_killbar * 100
        else:
            killbar_hit_rate = killbar_shift_rate = killbar_rebuild_rate = 0
        
        print(f"\n[Cache Statistics]")
        print(f"  Stats Panel: {self.stats_hits}/{total_stats} hits ({stats_rate:.1f}% hit rate)")
        print(f"  Killbar:")
        print(f"    - Cache hits:  {self.killbar_hits:5d} ({killbar_hit_rate:.1f}%) - no change")
        print(f"    - Shifts:      {self.killbar_shifts:5d} ({killbar_shift_rate:.1f}%) - 1 new kill") 
        print(f"    - Rebuilds:    {self.killbar_rebuilds:5d} ({killbar_rebuild_rate:.1f}%) - full redraw")


# Global render cache
_render_cache = RenderCache()

def get_render_cache():
    """Get the global render cache."""
    return _render_cache

def clear_render_cache():
    """Clear the render cache (call between games)."""
    _render_cache.clear()




def render_killbar(draw, kills, current_time, font, number_font):
    """
    Render killbar with scalable spacing based on font size.
    Layout: [#123] [Icon] Name ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â [Icon] Name [MM:SS]
    """
    if not ENABLE_KILLBAR or not kills:
        return

    recent_kills = _filter_kills_for_killbar(kills, current_time)[:config.KILLBAR_MAX_ENTRIES]

    if not recent_kills:
        return

    x_start = KILLBAR_POSITION_X
    y_start = KILLBAR_POSITION_Y

    # Use full killbar width (minus small margins)
    bg_width = config.KILLBAR_WIDTH - (KILLBAR_POSITION_X * 2)  # Account for left/right padding
    bg_height = len(recent_kills) * config.KILLBAR_ENTRY_HEIGHT + 10
    draw.rectangle([(x_start, y_start), (x_start + bg_width, y_start + bg_height)], fill=(0, 0, 0, KILLBAR_BG_ALPHA))

    # Calculate spacings based on font size
    fs = config.KILLBAR_FONT_SIZE
    sp = KILLBAR_SPACING_FACTORS

    number_width = int(fs * sp["number_width"])
    icon_to_name = getattr(config, 'KILLBAR_ICON_TO_NAME_OFFSET', int(fs * sp["icon_to_name"]))
    name_width = int(fs * sp["name_width"])
    name_to_symbol = int(fs * sp["name_to_symbol"])
    symbol_width = int(fs * sp["symbol_width"])
    symbol_to_icon = int(fs * sp["symbol_to_icon"])
    timestamp_gap = int(fs * sp["timestamp_gap"])

    y_current = y_start + 5

    for kill in recent_kills:
        x_pos = x_start + 5

        # Kill number
        if KILLBAR_SHOW_KILL_NUMBER:
            kill_num_str = f"#{kill.kill_number}"
            draw.text((x_pos, y_current + config.KILLBAR_ENTRY_HEIGHT // 2), kill_num_str, font=number_font, fill=(200, 200, 200, 255), anchor="lm")
            x_pos += number_width

        # Space for attacker icon (rendered separately)
        x_pos += config.KILLBAR_ICON_SIZE + icon_to_name

        # Attacker name (strip team prefixes from AI names)
        attacker_name = _clean_killbar_name(kill.attacker_name)[:KILLBAR_NAME_MAX_CHARS]
        attacker_color = TEAM_COLORS.get(kill.attacker_team, (255, 255, 255))
        draw.text((x_pos, y_current + config.KILLBAR_ENTRY_HEIGHT // 2), attacker_name, font=font, fill=(*attacker_color, 255), anchor="lm")
        x_pos += name_width + name_to_symbol
        
        # Kill symbol
        draw.text((x_pos, y_current + config.KILLBAR_ENTRY_HEIGHT // 2), KILLBAR_KILL_SYMBOL, font=font, fill=(255, 255, 255, 255), anchor="lm")
        x_pos += symbol_width + symbol_to_icon
        
        # Space for victim icon (rendered separately)
        x_pos += config.KILLBAR_ICON_SIZE + icon_to_name

        # Victim name (strip team prefixes from AI names)
        victim_name = _clean_killbar_name(kill.victim_name)[:KILLBAR_NAME_MAX_CHARS]
        victim_color = TEAM_COLORS.get(kill.victim_team, (255, 255, 255))
        draw.text((x_pos, y_current + config.KILLBAR_ENTRY_HEIGHT // 2), victim_name, font=font, fill=(*victim_color, 255), anchor="lm")
        x_pos += name_width + timestamp_gap

        # Timestamp
        minutes = int(kill.time // 60)
        seconds = int(kill.time % 60)
        timestamp_str = f"{minutes:02d}:{seconds:02d}"
        draw.text((x_pos, y_current + config.KILLBAR_ENTRY_HEIGHT // 2), timestamp_str, font=number_font, fill=(180, 180, 180, 255), anchor="lm")

        y_current += config.KILLBAR_ENTRY_HEIGHT




def render_killbar_icons(frame, kills, current_time, map_width):
    """Composite killbar icons with consistent spacing."""
    if not ENABLE_KILLBAR or not kills:
        return

    recent_kills = _filter_kills_for_killbar(kills, current_time)[:config.KILLBAR_MAX_ENTRIES]

    if not recent_kills:
        return
    
    x_start = map_width + KILLBAR_POSITION_X
    y_start = KILLBAR_POSITION_Y
    y_current = y_start + 5
    
    # Calculate spacings (same as render_killbar)
    fs = config.KILLBAR_FONT_SIZE
    sp = KILLBAR_SPACING_FACTORS
    
    number_width = int(fs * sp["number_width"])
    icon_to_name = getattr(config, 'KILLBAR_ICON_TO_NAME_OFFSET', int(fs * sp["icon_to_name"]))
    name_width = int(fs * sp["name_width"])
    name_to_symbol = int(fs * sp["name_to_symbol"])
    symbol_width = int(fs * sp["symbol_width"])
    symbol_to_icon = int(fs * sp["symbol_to_icon"])
    
    for kill in recent_kills:
        x_pos = x_start + 5
        
        # Skip kill number space
        if KILLBAR_SHOW_KILL_NUMBER:
            x_pos += number_width
        
        # Attacker Icon
        attacker_icon = get_icon(kill.attacker_unit, kill.attacker_team, "complete", config.KILLBAR_ICON_SIZE / 64.0)
        if attacker_icon:
            icon_y = y_current + (config.KILLBAR_ENTRY_HEIGHT - attacker_icon.height) // 2
            frame.alpha_composite(attacker_icon, (x_pos, icon_y))
        
        # Move to victim icon position
        x_victim_icon = x_pos + config.KILLBAR_ICON_SIZE + icon_to_name + name_width + name_to_symbol + symbol_width + symbol_to_icon
        
        # Victim Icon
        victim_icon = get_icon(kill.victim_unit, kill.victim_team, "complete", config.KILLBAR_ICON_SIZE / 64.0)
        if victim_icon:
            icon_y = y_current + (config.KILLBAR_ENTRY_HEIGHT - victim_icon.height) // 2
            frame.alpha_composite(victim_icon, (int(x_victim_icon), icon_y))
        
        y_current += config.KILLBAR_ENTRY_HEIGHT


def render_killbar_cached(kills, current_time, width, height, pre_sorted=False):
    """
    Render complete killbar panel with icons (cacheable version).
    Returns a complete RGBA image that can be composited onto the frame.
    
    Args:
        kills: List of kill events
        current_time: Current game time
        width: Panel width
        height: Panel height (should be VIDEO_HEIGHT)
        pre_sorted: If True, kills are already sorted and filtered (skip processing)
    """
    # Always create panel with full height, dark background
    panel = Image.new("RGBA", (width, height), (20, 20, 20, 255))
    draw = ImageDraw.Draw(panel, "RGBA")
    
    x_start = KILLBAR_POSITION_X
    y_start = KILLBAR_POSITION_Y
    
    # Background covers full panel height (dark semi-transparent) - ALWAYS draw this
    bg_width = width - (KILLBAR_POSITION_X * 2)
    draw.rectangle([(x_start, y_start), (x_start + bg_width, height - KILLBAR_POSITION_Y)], 
                   fill=(0, 0, 0, KILLBAR_BG_ALPHA))
    
    if not ENABLE_KILLBAR or not kills:
        return panel
    
    if pre_sorted:
        recent_kills = kills[:config.KILLBAR_MAX_ENTRIES]
    else:
        past_kills = [k for k in kills if k.time <= current_time]
        recent_kills = sorted(past_kills, key=lambda k: k.time, reverse=True)[:config.KILLBAR_MAX_ENTRIES]
    
    if not recent_kills:
        return panel
    
    # Use cached fonts
    font = get_cached_font(config.KILLBAR_FONT_SIZE)
    number_font = get_cached_font(config.KILLBAR_FONT_SIZE)
    
    # Calculate spacings
    fs = config.KILLBAR_FONT_SIZE
    sp = KILLBAR_SPACING_FACTORS
    number_width = int(fs * sp["number_width"])
    icon_to_name = getattr(config, 'KILLBAR_ICON_TO_NAME_OFFSET', int(fs * sp["icon_to_name"]))
    name_width = int(fs * sp["name_width"])
    name_to_symbol = int(fs * sp["name_to_symbol"])
    symbol_width = int(fs * sp["symbol_width"])
    symbol_to_icon = int(fs * sp["symbol_to_icon"])
    timestamp_gap = int(fs * sp["timestamp_gap"])
    
    y_current = y_start + 5
    
    for kill in recent_kills:
        x_pos = x_start + 5
        
        # Kill number
        if KILLBAR_SHOW_KILL_NUMBER:
            kill_num_str = f"#{kill.kill_number}"
            draw.text((x_pos, y_current + config.KILLBAR_ENTRY_HEIGHT // 2), kill_num_str, font=number_font, fill=(200, 200, 200, 255), anchor="lm")
            x_pos += number_width
        
        # Attacker Icon
        attacker_icon = get_icon(kill.attacker_unit, kill.attacker_team, "complete", config.KILLBAR_ICON_SIZE / 64.0)
        if attacker_icon:
            icon_y = y_current + (config.KILLBAR_ENTRY_HEIGHT - attacker_icon.height) // 2
            panel.alpha_composite(attacker_icon, (x_pos, icon_y))
        x_pos += config.KILLBAR_ICON_SIZE + icon_to_name
        
        # Attacker name
        attacker_name = kill.attacker_name[:KILLBAR_NAME_MAX_CHARS]
        attacker_color = TEAM_COLORS.get(kill.attacker_team, (255, 255, 255))
        draw.text((x_pos, y_current + config.KILLBAR_ENTRY_HEIGHT // 2), attacker_name, font=font, fill=(*attacker_color, 255), anchor="lm")
        x_pos += name_width + name_to_symbol
        
        # Kill symbol
        draw.text((x_pos, y_current + config.KILLBAR_ENTRY_HEIGHT // 2), KILLBAR_KILL_SYMBOL, font=font, fill=(255, 255, 255, 255), anchor="lm")
        x_pos += symbol_width + symbol_to_icon
        
        # Victim Icon
        victim_icon = get_icon(kill.victim_unit, kill.victim_team, "complete", config.KILLBAR_ICON_SIZE / 64.0)
        if victim_icon:
            icon_y = y_current + (config.KILLBAR_ENTRY_HEIGHT - victim_icon.height) // 2
            panel.alpha_composite(victim_icon, (x_pos, icon_y))
        x_pos += config.KILLBAR_ICON_SIZE + icon_to_name
        
        # Victim name
        victim_name = kill.victim_name[:KILLBAR_NAME_MAX_CHARS]
        victim_color = TEAM_COLORS.get(kill.victim_team, (255, 255, 255))
        draw.text((x_pos, y_current + config.KILLBAR_ENTRY_HEIGHT // 2), victim_name, font=font, fill=(*victim_color, 255), anchor="lm")
        x_pos += name_width + timestamp_gap
        
        # Timestamp
        minutes = int(kill.time // 60)
        seconds = int(kill.time % 60)
        timestamp_str = f"{minutes:02d}:{seconds:02d}"
        draw.text((x_pos, y_current + config.KILLBAR_ENTRY_HEIGHT // 2), timestamp_str, font=number_font, fill=(180, 180, 180, 255), anchor="lm")
        
        y_current += config.KILLBAR_ENTRY_HEIGHT
    
    return panel


def create_kills_graph(kill_stats, current_time, width, height):
    """
    Create Graph 1: Killed Units and Killed Buildings.
    
    Line styles are configurable via config.GRAPH1_UNITS_KILLED_STYLE and
    config.GRAPH1_BUILDINGS_KILLED_STYLE.
    
    Returns:
        PIL Image
    """
    # Import matplotlib only when this function is called (fallback when USE_PIL_GRAPHS = False)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    
    # Get line styles from config - read fresh each time
    # Use importlib.reload to ensure we get the latest config values
    import importlib
    import config as cfg
    importlib.reload(cfg)
    
    try:
        units_style_name = getattr(cfg, 'GRAPH1_UNITS_KILLED_STYLE', 'dotted')
        buildings_style_name = getattr(cfg, 'GRAPH1_BUILDINGS_KILLED_STYLE', 'solid')
        spacing = getattr(cfg, 'GRAPH_LINE_SPACING', 10)
        units_style = cfg.get_matplotlib_linestyle(units_style_name)
        buildings_style = cfg.get_matplotlib_linestyle(buildings_style_name)
        # Debug: print on first frame only (current_time < 2)
        if current_time < 2:
            print(f"[Graph1] Line styles: units='{units_style_name}'->{units_style}, buildings='{buildings_style_name}'->{buildings_style}, spacing={spacing}")
    except AttributeError as e:
        # Fallback if config doesn't have these settings
        print(f"[Graph1] Warning: Could not read line styles from config: {e}")
        units_style = ':'
        buildings_style = '-'
    
    fig, ax = plt.subplots(figsize=(width/100, height/100), dpi=100)
    fig.patch.set_facecolor('#191919')
    ax.set_facecolor('#191919')
    
    # Track if we've added legend entries for line styles
    legend_added = {"units": False, "buildings": False}
    
    # Marker frequency - show marker every N points to avoid clutter
    marker_every = max(1, int(current_time / 60 / 5))  # ~5 markers per game length
    
    # Plot each team's kill stats
    for team_name, stats in kill_stats.items():
        if not stats.timeline:
            continue
        
        times = [t[0] for t in stats.timeline if t[0] <= current_time]
        killed_units = [t[3] for t in stats.timeline if t[0] <= current_time]  # Index 3 = killed_units
        killed_buildings = [t[4] for t in stats.timeline if t[0] <= current_time]  # Index 4 = killed_buildings
        
        if not times:
            continue
        
        # Convert times to minutes
        times_min = [t / 60.0 for t in times]
        
        color_rgb = GRAPH_COLORS.get(team_name, (255, 255, 255))
        color_hex = f"#{color_rgb[0]:02x}{color_rgb[1]:02x}{color_rgb[2]:02x}"
        
        # Plot Units Killed - only add to legend once
        if not legend_added["units"]:
            ax.plot(times_min, killed_units, 
                    linestyle=units_style, 
                    marker='o',
                    markersize=4,
                    markevery=marker_every,
                    color=color_hex, 
                    alpha=0.9, 
                    linewidth=2.0,
                    label="Units Killed")
            legend_added["units"] = True
        else:
            ax.plot(times_min, killed_units, 
                    linestyle=units_style, 
                    marker='o',
                    markersize=4,
                    markevery=marker_every,
                    color=color_hex, 
                    alpha=0.9, 
                    linewidth=2.0)
        
        # Plot Buildings Killed - only add to legend once
        if not legend_added["buildings"]:
            ax.plot(times_min, killed_buildings, 
                    linestyle=buildings_style, 
                    marker='^',
                    markersize=5,
                    markevery=marker_every,
                    color=color_hex, 
                    alpha=0.9, 
                    linewidth=2.0,
                    label="Buildings Killed")
            legend_added["buildings"] = True
        else:
            ax.plot(times_min, killed_buildings, 
                    linestyle=buildings_style, 
                    marker='^',
                    markersize=5,
                    markevery=marker_every,
                    color=color_hex, 
                    alpha=0.9, 
                    linewidth=2.0)
    
    # Get label padding from config
    label_pad_x = getattr(config, 'GRAPH_LABEL_PAD_X', 8)
    label_pad_y = getattr(config, 'GRAPH_LABEL_PAD_Y', 8)
    
    ax.set_xlabel("Time (minutes)", color='white', fontsize=config.Fontsize_Graphlabel, labelpad=label_pad_x)
    ax.set_ylabel("Kills", color='white', fontsize=config.Fontsize_Graphlabel, labelpad=label_pad_y)
    # No title as per requirements
    
    # Set x-axis to start at 0 (no offset)
    ax.set_xlim(left=0)
    
    ax.tick_params(colors='white', labelsize=config.Fontsize_Graphax)
    ax.spines['bottom'].set_color('white')
    ax.spines['left'].set_color('white')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.grid(True, alpha=0.2, color='white')
    
    # Legend with white text - use config font size
    import config as cfg
    legend_fontsize = getattr(cfg, 'Fontsize_Graphlegend', 12)
    
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        legend = ax.legend(loc='upper left', fontsize=legend_fontsize, framealpha=0.8, 
                          facecolor='#191919', edgecolor='white')
        # Set legend text color to white
        for text in legend.get_texts():
            text.set_color('white')
        # Set legend line colors to white
        for line in legend.get_lines():
            line.set_color('white')
    
    plt.tight_layout()
    
    # Convert to PIL Image
    fig.canvas.draw()
    img_array = np.frombuffer(fig.canvas.buffer_rgba(), dtype=np.uint8)
    img_array = img_array.reshape(fig.canvas.get_width_height()[::-1] + (4,))
    plt.close(fig)
    
    return Image.fromarray(img_array, mode="RGBA")




def create_buildings_graph(building_stats, current_time, width, height):
    """
    Create Graph 2: Buildings Currently on Map.
    
    Shows for each team:
    - HQ/Nest: Current count (configurable via config.GRAPH2_HQ_STYLE)
    - Refineries/Bio: Current count (configurable via config.GRAPH2_REFS_STYLE)
    
    Returns:
        PIL Image
    """
    # Import matplotlib only when this function is called (fallback when USE_PIL_GRAPHS = False)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    
    # Get line styles from config - read fresh each time
    # Use importlib.reload to ensure we get the latest config values
    import importlib
    import config as cfg
    importlib.reload(cfg)
    
    try:
        hq_style_name = getattr(cfg, 'GRAPH2_HQ_STYLE', 'solid')
        refs_style_name = getattr(cfg, 'GRAPH2_REFS_STYLE', 'loosely_dashed')
        spacing = getattr(cfg, 'GRAPH_LINE_SPACING', 10)
        hq_style = cfg.get_matplotlib_linestyle(hq_style_name)
        refs_style = cfg.get_matplotlib_linestyle(refs_style_name)
        # Debug: print on first frame only (current_time < 2)
        if current_time < 2:
            print(f"[Graph2] Line styles: hq='{hq_style_name}'->{hq_style}, refs='{refs_style_name}'->{refs_style}, spacing={spacing}")
    except AttributeError as e:
        # Fallback if config doesn't have these settings
        print(f"[Graph2] Warning: Could not read line styles from config: {e}")
        hq_style = '-'
        refs_style = '-.'
    
    fig, ax = plt.subplots(figsize=(width/100, height/100), dpi=100)
    fig.patch.set_facecolor('#191919')
    ax.set_facecolor('#191919')
    
    # Track legend entries
    legend_added = {"hq": False, "refs": False}
    
    # Marker frequency - show marker every N points to avoid clutter
    marker_every = max(1, int(current_time / 60 / 5))  # ~5 markers per game length
    
    # Plot each team's building stats
    for team_name, stats in building_stats.items():
        if not stats.timeline:
            continue
        
        times = [t[0] for t in stats.timeline if t[0] <= current_time]
        hq_current = [t[2] for t in stats.timeline if t[0] <= current_time]  # Index 2 = HQ current
        refs_current = [t[4] for t in stats.timeline if t[0] <= current_time]  # Index 4 = Refs current
        bio_current = [t[6] for t in stats.timeline if t[0] <= current_time]   # Index 6 = Bio current
        
        if not times:
            continue
        
        # Convert times to minutes
        times_min = [t / 60.0 for t in times]
        
        color_rgb = GRAPH_COLORS.get(team_name, (255, 255, 255))
        color_hex = f"#{color_rgb[0]:02x}{color_rgb[1]:02x}{color_rgb[2]:02x}"
        
        # HQ/Nest (configurable line style with square markers)
        if not legend_added["hq"]:
            ax.plot(times_min, hq_current, linestyle=hq_style, marker='s', markersize=5, markevery=marker_every,
                    color=color_hex, alpha=0.9, linewidth=2.5, label="HQ/Nest")
            legend_added["hq"] = True
        else:
            ax.plot(times_min, hq_current, linestyle=hq_style, marker='s', markersize=5, markevery=marker_every,
                    color=color_hex, alpha=0.9, linewidth=2.5)
        
        # Refineries/Bio Caches (configurable line style with diamond markers)
        if team_name == "Alien":
            # Bio Caches for Alien
            if not legend_added["refs"]:
                ax.plot(times_min, bio_current, linestyle=refs_style, marker='D', markersize=4, markevery=marker_every,
                        color=color_hex, alpha=0.9, linewidth=2.0, label="Refs/Bio")
                legend_added["refs"] = True
            else:
                ax.plot(times_min, bio_current, linestyle=refs_style, marker='D', markersize=4, markevery=marker_every,
                        color=color_hex, alpha=0.9, linewidth=2.0)
        else:
            # Refineries for Human teams
            if not legend_added["refs"]:
                ax.plot(times_min, refs_current, linestyle=refs_style, marker='D', markersize=4, markevery=marker_every,
                        color=color_hex, alpha=0.9, linewidth=2.0, label="Refs/Bio")
                legend_added["refs"] = True
            else:
                ax.plot(times_min, refs_current, linestyle=refs_style, marker='D', markersize=4, markevery=marker_every,
                        color=color_hex, alpha=0.9, linewidth=2.0)
    
    # Get label padding from config
    label_pad_x = getattr(config, 'GRAPH_LABEL_PAD_X', 8)
    label_pad_y = getattr(config, 'GRAPH_LABEL_PAD_Y', 8)
    
    ax.set_xlabel("Time (minutes)", color='white', fontsize=config.Fontsize_Graphlabel, labelpad=label_pad_x)
    ax.set_ylabel("Buildings on Map", color='white', fontsize=config.Fontsize_Graphlabel, labelpad=label_pad_y)
    
    # Set x-axis to start at 0
    ax.set_xlim(left=0)
    
    ax.tick_params(colors='white', labelsize=config.Fontsize_Graphax)
    ax.spines['bottom'].set_color('white')
    ax.spines['left'].set_color('white')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.grid(True, alpha=0.2, color='white')
    
    # Legend - use config font size
    import config as cfg
    legend_fontsize = getattr(cfg, 'Fontsize_Graphlegend', 12)
    
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        legend = ax.legend(loc='upper left', fontsize=legend_fontsize, framealpha=0.8, 
                          facecolor='#191919', edgecolor='white')
        for text in legend.get_texts():
            text.set_color('white')
        for line in legend.get_lines():
            line.set_color('white')
    
    plt.tight_layout()
    
    # Convert to PIL Image
    fig.canvas.draw()
    img_array = np.frombuffer(fig.canvas.buffer_rgba(), dtype=np.uint8)
    img_array = img_array.reshape(fig.canvas.get_width_height()[::-1] + (4,))
    plt.close(fig)
    
    return Image.fromarray(img_array, mode="RGBA")


# ============================================================
# PIL-BASED GRAPH RENDERING (Fast, no matplotlib overhead)
# ============================================================

class PILGraphRenderer:
    """
    Fast graph rendering using only PIL.
    No matplotlib overhead - direct line drawing.
    """
    
    def __init__(self, width, height, bg_color=(25, 25, 25), margin=None):
        self.width = width
        self.height = height
        self.bg_color = bg_color
        self.scale = config.get_scale_ratio()
        
        # Margins: left, right, top, bottom (scaled)
        if margin is None:
            self.margin = {
                'left': int(60 * self.scale) + int(0.65 * config.Fontsize_Graphlabel),
                'right': int(20 * self.scale),
                'top': int(20 * self.scale),
                'bottom': int(45 * self.scale)
            }
        else:
            self.margin = margin
        
        # Plot area
        self.plot_left = self.margin['left']
        self.plot_right = width - self.margin['right']
        self.plot_top = self.margin['top']
        self.plot_bottom = height - self.margin['bottom']
        self.plot_width = self.plot_right - self.plot_left
        self.plot_height = self.plot_bottom - self.plot_top
        
        # Pending y-label (composited after draw object is flushed)
        self._pending_y_label = None  # (rotated_img, x_pos, y_pos)
        
        # Cached fonts
        self._label_font = None
        self._tick_font = None
        self._legend_font = None
    
    @property
    def label_font(self):
        if self._label_font is None:
            self._label_font = get_cached_font(config.Fontsize_Graphlabel)
        return self._label_font
    
    @property
    def tick_font(self):
        if self._tick_font is None:
            self._tick_font = get_cached_font(config.Fontsize_Graphax)
        return self._tick_font
    
    @property
    def legend_font(self):
        if self._legend_font is None:
            self._legend_font = get_cached_font(config.Fontsize_Graphlegend)
        return self._legend_font
    
    def create_image(self):
        """Create base image with background."""
        return Image.new("RGBA", (self.width, self.height), (*self.bg_color, 255))
    
    def data_to_pixel(self, x_val, y_val, x_min, x_max, y_min, y_max):
        """Convert data coordinates to pixel coordinates."""
        if x_max == x_min:
            px = self.plot_left
        else:
            px = self.plot_left + (x_val - x_min) / (x_max - x_min) * self.plot_width
        
        if y_max == y_min:
            py = self.plot_bottom
        else:
            py = self.plot_bottom - (y_val - y_min) / (y_max - y_min) * self.plot_height
        
        return int(px), int(py)
    
    def draw_axes(self, draw, x_min, x_max, y_min, y_max, x_label="", y_label="", img=None, y_format_k=False):
        """Draw axes, grid, and labels.
        
        Args:
            y_format_k: If True, format large y-axis values with K/M suffix (e.g. 10K, 1.5M)
        """
        axis_color = (255, 255, 255, 255)
        grid_color = (255, 255, 255, 50)
        
        # Draw axes lines
        draw.line([(self.plot_left, self.plot_bottom), (self.plot_right, self.plot_bottom)], 
                  fill=axis_color, width=1)
        draw.line([(self.plot_left, self.plot_top), (self.plot_left, self.plot_bottom)], 
                  fill=axis_color, width=1)
        
        # X-axis ticks and grid
        num_x_ticks = 6
        for i in range(num_x_ticks + 1):
            x_val = x_min + (x_max - x_min) * i / num_x_ticks
            px, _ = self.data_to_pixel(x_val, 0, x_min, x_max, y_min, y_max)
            
            # Grid line
            draw.line([(px, self.plot_top), (px, self.plot_bottom)], fill=grid_color, width=1)
            
            # Tick label
            label = f"{x_val:.0f}"
            bbox = draw.textbbox((0, 0), label, font=self.tick_font)
            tw = bbox[2] - bbox[0]
            draw.text((px - tw // 2, self.plot_bottom + 5), label, font=self.tick_font, fill=axis_color)
        
        # Y-axis ticks and grid
        num_y_ticks = 5
        for i in range(num_y_ticks + 1):
            y_val = y_min + (y_max - y_min) * i / num_y_ticks
            _, py = self.data_to_pixel(0, y_val, x_min, x_max, y_min, y_max)
            
            # Grid line
            draw.line([(self.plot_left, py), (self.plot_right, py)], fill=grid_color, width=1)
            
            # Tick label - optionally format with K/M suffix
            if y_format_k and abs(y_val) >= 1_000_000:
                label = f"{y_val / 1_000_000:.1f}M"
            elif y_format_k and abs(y_val) >= 1_000:
                label = f"{y_val / 1_000:.0f}K"
            else:
                label = f"{y_val:.0f}"
            bbox = draw.textbbox((0, 0), label, font=self.tick_font)
            tw = bbox[2] - bbox[0]
            draw.text((self.plot_left - tw - 8, py - 6), label, font=self.tick_font, fill=axis_color)
        
        # X-axis label (horizontal, centered below x-axis)
        if x_label:
            bbox = draw.textbbox((0, 0), x_label, font=self.label_font)
            tw = bbox[2] - bbox[0]
            x_pos = self.plot_left + self.plot_width // 2 - tw // 2
            draw.text((x_pos, self.height - int(20 * self.scale)), x_label, font=self.label_font, fill=axis_color)
        
        # Y-axis label (vertical, rotated 90 degrees)
        # Deferred to finalize() so it's pasted on top of all draw operations
        if y_label and img is not None:
            # Measure text with bbox offset compensation
            bbox = draw.textbbox((0, 0), y_label, font=self.label_font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            
            # Create text on solid background (same as graph bg) to avoid alpha issues
            pad = 4
            txt_img = Image.new("RGB", (tw + pad, th + pad), self.bg_color)
            txt_draw = ImageDraw.Draw(txt_img)
            # Offset by -bbox[0], -bbox[1] to compensate for font metrics
            txt_draw.text((pad // 2 - bbox[0], pad // 2 - bbox[1]), y_label, 
                         font=self.label_font, fill=axis_color)
            
            # Rotate 90 degrees counter-clockwise
            rotated = txt_img.rotate(90, expand=True)
            
            # Store for deferred paste in finalize()
            y_center = self.plot_top + self.plot_height // 2
            x_pos = 2
            y_pos = y_center - rotated.height // 2
            self._pending_y_label = (rotated, x_pos, y_pos)
    
    def draw_line(self, draw, x_data, y_data, x_min, x_max, y_min, y_max, 
                  color=(255, 255, 255), width=2, style='solid'):
        """Draw a line on the graph."""
        if len(x_data) < 2:
            return
        
        points = []
        for x, y in zip(x_data, y_data):
            px, py = self.data_to_pixel(x, y, x_min, x_max, y_min, y_max)
            points.append((px, py))
        
        if style == 'solid':
            # Draw solid line
            for i in range(len(points) - 1):
                draw.line([points[i], points[i + 1]], fill=(*color, 230), width=width)
        
        elif style == 'dotted':
            # Draw dotted line (dots every 4 pixels)
            for i in range(len(points) - 1):
                x1, y1 = points[i]
                x2, y2 = points[i + 1]
                length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
                if length < 1:
                    continue
                
                num_dots = max(1, int(length / 6))
                for j in range(num_dots):
                    t = j / num_dots
                    dx = int(x1 + t * (x2 - x1))
                    dy = int(y1 + t * (y2 - y1))
                    draw.ellipse([(dx - 1, dy - 1), (dx + 1, dy + 1)], fill=(*color, 230))
        
        elif style == 'dashed':
            # Draw dashed line
            dash_len = 8
            gap_len = 4
            for i in range(len(points) - 1):
                x1, y1 = points[i]
                x2, y2 = points[i + 1]
                length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
                if length < 1:
                    continue
                
                dx = (x2 - x1) / length
                dy = (y2 - y1) / length
                
                pos = 0
                drawing = True
                while pos < length:
                    if drawing:
                        end_pos = min(pos + dash_len, length)
                        sx = int(x1 + pos * dx)
                        sy = int(y1 + pos * dy)
                        ex = int(x1 + end_pos * dx)
                        ey = int(y1 + end_pos * dy)
                        draw.line([(sx, sy), (ex, ey)], fill=(*color, 230), width=width)
                        pos = end_pos + gap_len
                    else:
                        pos += gap_len
                    drawing = not drawing
        
        elif style == 'dashdot':
            # Draw dash-dot line (long dash, dot, long dash, dot...)
            dash_len = 10
            dot_gap = 4
            gap_len = 4
            for i in range(len(points) - 1):
                x1, y1 = points[i]
                x2, y2 = points[i + 1]
                length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
                if length < 1:
                    continue
                
                dx = (x2 - x1) / length
                dy = (y2 - y1) / length
                
                pos = 0
                phase = 0  # 0=dash, 1=gap, 2=dot, 3=gap
                while pos < length:
                    if phase == 0:  # Dash
                        end_pos = min(pos + dash_len, length)
                        sx = int(x1 + pos * dx)
                        sy = int(y1 + pos * dy)
                        ex = int(x1 + end_pos * dx)
                        ey = int(y1 + end_pos * dy)
                        draw.line([(sx, sy), (ex, ey)], fill=(*color, 230), width=width)
                        pos = end_pos + dot_gap
                        phase = 1
                    elif phase == 1:  # Gap before dot
                        phase = 2
                    elif phase == 2:  # Dot
                        dot_x = int(x1 + pos * dx)
                        dot_y = int(y1 + pos * dy)
                        draw.ellipse([(dot_x - 1, dot_y - 1), (dot_x + 1, dot_y + 1)], fill=(*color, 230))
                        pos += dot_gap
                        phase = 3
                    else:  # Gap after dot
                        phase = 0
        
        elif style == 'loosely_dotted':
            # Draw loosely dotted line (dots with larger spacing)
            for i in range(len(points) - 1):
                x1, y1 = points[i]
                x2, y2 = points[i + 1]
                length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
                if length < 1:
                    continue
                
                num_dots = max(1, int(length / 15))  # Wider spacing than regular dotted
                for j in range(num_dots):
                    t = j / num_dots
                    dx = int(x1 + t * (x2 - x1))
                    dy = int(y1 + t * (y2 - y1))
                    draw.ellipse([(dx - 2, dy - 2), (dx + 2, dy + 2)], fill=(*color, 230))
        
        elif style == 'loosely_dashed':
            # Draw loosely dashed line (larger gaps between dashes)
            dash_len = 10
            gap_len = 12  # Larger gap than regular dashed
            for i in range(len(points) - 1):
                x1, y1 = points[i]
                x2, y2 = points[i + 1]
                length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
                if length < 1:
                    continue
                
                dx = (x2 - x1) / length
                dy = (y2 - y1) / length
                
                pos = 0
                drawing = True
                while pos < length:
                    if drawing:
                        end_pos = min(pos + dash_len, length)
                        sx = int(x1 + pos * dx)
                        sy = int(y1 + pos * dy)
                        ex = int(x1 + end_pos * dx)
                        ey = int(y1 + end_pos * dy)
                        draw.line([(sx, sy), (ex, ey)], fill=(*color, 230), width=width)
                        pos = end_pos + gap_len
                    else:
                        pos += gap_len
                    drawing = not drawing
    
    def draw_legend(self, draw, items, x=None, y=None):
        """
        Draw legend.
        items: list of (label, color, style)
        """
        if not items:
            return
        
        if x is None:
            x = self.plot_left + 10
        if y is None:
            y = self.plot_top + 10
        
        box_width = int(150 * self.scale)
        line_height = int(20 * self.scale)
        box_height = len(items) * line_height + int(10 * self.scale)
        
        # Background
        draw.rectangle([(x, y), (x + box_width, y + box_height)], 
                      fill=(25, 25, 25, 200), outline=(255, 255, 255, 100))
        
        # Items
        for i, (label, color, style) in enumerate(items):
            item_y = y + int(8 * self.scale) + i * line_height
            
            # Line sample
            line_x1 = x + int(8 * self.scale)
            line_x2 = x + int(35 * self.scale)
            line_y = item_y + int(6 * self.scale)
            
            if style == 'solid':
                draw.line([(line_x1, line_y), (line_x2, line_y)], fill=(255, 255, 255, 255), width=max(1, int(3 * self.scale)))
            elif style == 'dotted':
                dot_spacing = max(3, int(5 * self.scale))
                for dx in range(0, line_x2 - line_x1, dot_spacing):
                    r = max(1, int(1 * self.scale))
                    draw.ellipse([(line_x1 + dx - r, line_y - r), (line_x1 + dx + r, line_y + r)], 
                               fill=(255, 255, 255, 255))
            elif style == 'loosely_dotted':
                # Larger dots with wider spacing
                dot_spacing = max(5, int(10 * self.scale))
                for dx in range(0, line_x2 - line_x1, dot_spacing):
                    r = max(1, int(2 * self.scale))
                    draw.ellipse([(line_x1 + dx - r, line_y - r), (line_x1 + dx + r, line_y + r)], 
                               fill=(255, 255, 255, 255))
            elif style == 'dashed':
                draw.line([(line_x1, line_y), (line_x1 + int(8 * self.scale), line_y)], fill=(255, 255, 255, 255), width=max(1, int(2 * self.scale)))
                draw.line([(line_x1 + int(14 * self.scale), line_y), (line_x2, line_y)], fill=(255, 255, 255, 255), width=max(1, int(2 * self.scale)))
            elif style == 'loosely_dashed':
                # Wider gaps between dashes
                draw.line([(line_x1, line_y), (line_x1 + int(8 * self.scale), line_y)], fill=(255, 255, 255, 255), width=max(1, int(2 * self.scale)))
                draw.line([(line_x1 + int(18 * self.scale), line_y), (line_x2, line_y)], fill=(255, 255, 255, 255), width=max(1, int(2 * self.scale)))
            elif style == 'dashdot':
                # Dash
                draw.line([(line_x1, line_y), (line_x1 + int(10 * self.scale), line_y)], fill=(255, 255, 255, 255), width=max(1, int(2 * self.scale)))
                # Dot
                dot_x = line_x1 + int(16 * self.scale)
                r = max(1, int(1 * self.scale))
                draw.ellipse([(dot_x - r, line_y - r), (dot_x + r, line_y + r)], fill=(255, 255, 255, 255))
                # Dash
                draw.line([(line_x1 + int(22 * self.scale), line_y), (line_x2, line_y)], fill=(255, 255, 255, 255), width=max(1, int(2 * self.scale)))
            
            # Label
            draw.text((x + int(42 * self.scale), item_y), label, font=self.legend_font, fill=(255, 255, 255, 255))

    def finalize(self, img):
        """
        Paste deferred y-label onto the image.
        Must be called AFTER all draw operations are complete.
        Uses solid-background paste (no alpha) to guarantee visibility.
        """
        if self._pending_y_label is not None:
            rotated, x_pos, y_pos = self._pending_y_label
            img.paste(rotated, (x_pos, y_pos))
            self._pending_y_label = None


def create_kills_graph_pil(kill_stats, current_time, width, height):
    """
    PIL-based kills graph - much faster than matplotlib.
    Line styles are configurable via config.GRAPH1_UNITS_KILLED_STYLE and
    config.GRAPH1_BUILDINGS_KILLED_STYLE.
    Line widths are configurable via config.GRAPH1_UNITS_KILLED_WIDTH and
    config.GRAPH1_BUILDINGS_KILLED_WIDTH.
    """
    # Get line styles and widths from config
    units_style = getattr(config, 'GRAPH1_UNITS_KILLED_STYLE', 'dotted')
    units_width = getattr(config, 'GRAPH1_UNITS_KILLED_WIDTH', 2)
    buildings_style = getattr(config, 'GRAPH1_BUILDINGS_KILLED_STYLE', 'solid')
    buildings_width = getattr(config, 'GRAPH1_BUILDINGS_KILLED_WIDTH', 3)
    
    renderer = PILGraphRenderer(width, height)
    img = renderer.create_image()
    draw = ImageDraw.Draw(img)
    
    # Collect data
    all_times = []
    all_values = []
    team_data = {}
    
    for team_name, stats in kill_stats.items():
        if not stats.timeline:
            continue
        
        times = [t[0] / 60.0 for t in stats.timeline if t[0] <= current_time]  # Convert to minutes
        killed_units = [t[3] for t in stats.timeline if t[0] <= current_time]
        killed_buildings = [t[4] for t in stats.timeline if t[0] <= current_time]
        
        if times:
            team_data[team_name] = {
                'times': times,
                'units': killed_units,
                'buildings': killed_buildings
            }
            all_times.extend(times)
            all_values.extend(killed_units)
            all_values.extend(killed_buildings)
    
    # Calculate bounds
    x_min = 0
    x_max = max(all_times) if all_times else 1
    y_min = 0
    y_max = max(all_values) if all_values else 1
    y_max = max(y_max, 1)  # Ensure at least 1
    y_max *= 1.1  # Add 10% headroom
    
    # Draw axes (pass img for vertical y-label)
    renderer.draw_axes(draw, x_min, x_max, y_min, y_max, "Time (minutes)", "Kills", img=img)
    
    # Draw lines for each team
    for team_name, data in team_data.items():
        color = GRAPH_COLORS.get(team_name, (255, 255, 255))
        
        # Units killed - use config style and width
        renderer.draw_line(draw, data['times'], data['units'], 
                          x_min, x_max, y_min, y_max, color, width=units_width, style=units_style)
        
        # Buildings killed - use config style and width
        renderer.draw_line(draw, data['times'], data['buildings'],
                          x_min, x_max, y_min, y_max, color, width=buildings_width, style=buildings_style)
    
    # Legend - use config styles
    renderer.draw_legend(draw, [
        ("Units Killed", (255, 255, 255), units_style),
        ("Buildings Killed", (255, 255, 255), buildings_style),
    ])
    
    # Flush draw layer, then composite deferred y-label on top
    del draw
    renderer.finalize(img)
    
    return img


def create_buildings_graph_pil(building_stats, current_time, width, height):
    """
    PIL-based buildings graph - much faster than matplotlib.
    Line styles are configurable via config.GRAPH2_HQ_STYLE and config.GRAPH2_REFS_STYLE.
    Line widths are configurable via config.GRAPH2_HQ_WIDTH and config.GRAPH2_REFS_WIDTH.
    """
    # Get line styles and widths from config
    hq_style = getattr(config, 'GRAPH2_HQ_STYLE', 'solid')
    hq_width = getattr(config, 'GRAPH2_HQ_WIDTH', 3)
    refs_style = getattr(config, 'GRAPH2_REFS_STYLE', 'dashdot')
    refs_width = getattr(config, 'GRAPH2_REFS_WIDTH', 2)
    
    renderer = PILGraphRenderer(width, height)
    img = renderer.create_image()
    draw = ImageDraw.Draw(img)
    
    # Collect data
    all_times = []
    all_values = []
    team_data = {}
    
    for team_name, stats in building_stats.items():
        if not stats.timeline:
            continue
        
        times = [t[0] / 60.0 for t in stats.timeline if t[0] <= current_time]
        hq_current = [t[2] for t in stats.timeline if t[0] <= current_time]
        refs_current = [t[4] for t in stats.timeline if t[0] <= current_time]
        bio_current = [t[6] for t in stats.timeline if t[0] <= current_time]
        
        if times:
            team_data[team_name] = {
                'times': times,
                'hq': hq_current,
                'refs': refs_current,
                'bio': bio_current
            }
            all_times.extend(times)
            all_values.extend(hq_current)
            if team_name == "Alien":
                all_values.extend(bio_current)
            else:
                all_values.extend(refs_current)
    
    # Calculate bounds
    x_min = 0
    x_max = max(all_times) if all_times else 1
    y_min = 0
    y_max = max(all_values) if all_values else 1
    y_max = max(y_max, 1)
    y_max *= 1.1
    
    # Draw axes (pass img for vertical y-label)
    renderer.draw_axes(draw, x_min, x_max, y_min, y_max, "Time (minutes)", "Buildings", img=img)
    
    # Draw lines for each team
    for team_name, data in team_data.items():
        color = GRAPH_COLORS.get(team_name, (255, 255, 255))
        
        # HQ/Nest - use config style and width
        renderer.draw_line(draw, data['times'], data['hq'],
                          x_min, x_max, y_min, y_max, color, width=hq_width, style=hq_style)
        
        # Refs/Bio - use config style and width
        if team_name == "Alien":
            renderer.draw_line(draw, data['times'], data['bio'],
                              x_min, x_max, y_min, y_max, color, width=refs_width, style=refs_style)
        else:
            renderer.draw_line(draw, data['times'], data['refs'],
                              x_min, x_max, y_min, y_max, color, width=refs_width, style=refs_style)
    
    # Legend - use config styles
    renderer.draw_legend(draw, [
        ("HQ/Nest", (255, 255, 255), hq_style),
        ("Refs/Bio", (255, 255, 255), refs_style),
    ])
    
    # Flush draw layer, then composite deferred y-label on top
    del draw
    renderer.finalize(img)
    
    return img


def create_resource_graph_pil(resource_stats, current_time, width, height):
    """
    PIL-based resource status graph showing Collected and Spent resources per team.
    Line styles configurable via config.GRAPH2_COLLECTED_STYLE and config.GRAPH2_SPENT_STYLE.
    Line widths configurable via config.GRAPH2_COLLECTED_WIDTH and config.GRAPH2_SPENT_WIDTH.
    """
    # Get line styles and widths from config
    collected_style = getattr(config, 'GRAPH2_COLLECTED_STYLE', 'solid')
    collected_width = getattr(config, 'GRAPH2_COLLECTED_WIDTH', 2)
    spent_style = getattr(config, 'GRAPH2_SPENT_STYLE', 'loosely_dotted')
    spent_width = getattr(config, 'GRAPH2_SPENT_WIDTH', 3)
    
    renderer = PILGraphRenderer(width, height)
    img = renderer.create_image()
    draw = ImageDraw.Draw(img)
    
    # Collect data
    all_times = []
    all_values = []
    team_data = {}
    
    for team_name, stats in resource_stats.items():
        if not stats.timeline:
            continue
        
        times = [t[0] / 60.0 for t in stats.timeline if t[0] <= current_time]
        collected = [t[1] for t in stats.timeline if t[0] <= current_time]
        spent = [t[2] for t in stats.timeline if t[0] <= current_time]
        
        if times:
            team_data[team_name] = {
                'times': times,
                'collected': collected,
                'spent': spent,
            }
            all_times.extend(times)
            all_values.extend(collected)
            all_values.extend(spent)
    
    # Calculate bounds
    x_min = 0
    x_max = max(all_times) if all_times else 1
    y_min = 0
    y_max = max(all_values) if all_values else 1
    y_max = max(y_max, 1)
    y_max *= 1.1
    
    # Format large resource values with K suffix on y-axis
    # We pass a custom label; the axis auto-formats numbers
    renderer.draw_axes(draw, x_min, x_max, y_min, y_max, "Time (minutes)", "Resources", img=img, y_format_k=True)
    
    # Draw lines for each team
    for team_name, data in team_data.items():
        color = GRAPH_COLORS.get(team_name, (255, 255, 255))
        
        # Collected - solid style
        renderer.draw_line(draw, data['times'], data['collected'],
                          x_min, x_max, y_min, y_max, color, width=collected_width, style=collected_style)
        
        # Spent - dotted style
        renderer.draw_line(draw, data['times'], data['spent'],
                          x_min, x_max, y_min, y_max, color, width=spent_width, style=spent_style)
    
    # Legend
    renderer.draw_legend(draw, [
        ("Collected", (255, 255, 255), collected_style),
        ("Spent", (255, 255, 255), spent_style),
    ])
    
    # Flush draw layer, then composite deferred y-label on top
    del draw
    renderer.finalize(img)
    
    return img


# Configuration flag to choose renderer
USE_PIL_GRAPHS = True  # Set to False to use matplotlib (slower but has markers)


def create_table1_team_stats(kill_stats, building_stats, player_stats, commanders, current_time, width, height):
    """
    Create Table 1: Team Statistics with Icons
    
    Columns:
    - Team Icon
    - Units Lost
    - Units Killed  
    - Bldgs Killed
    - Bldgs Build/Lost
    - Refs/Bio Build/Lost
    - HQs/Nest Build/Lost
    - Tech Level
    - Nodes Build/Lost (Alien only)
    
    Returns:
        PIL Image
    """
    img = Image.new("RGBA", (width, height), (*STATS_BG_COLOR, 255))
    draw = ImageDraw.Draw(img)
    
    # Use scaled fonts from config
    font_header = load_font(config.TABLE1_HEADER_FONT_SIZE)
    font_data = load_font(config.TABLE1_DATA_FONT_SIZE)
    
    # Team logo files
    team_logos = {
        "Sol": "512x512_Sol_Logo-01.png",
        "Centauri": "Centauri_512x512-01-01.png",
        "Alien": "512x512_alien_logo.png"
    }
    
    # Helper function to get current commander from parsed log data
    def get_team_commander(team_name):
        """Get the current commander for this team at current_time."""
        if team_name not in commanders or not commanders[team_name]:
            return "N/A"
        
        # Find the most recent commander change before or at current_time
        team_commanders = commanders[team_name]
        current_commander = None
        
        for time, player_name in team_commanders:
            if time <= current_time:
                current_commander = player_name
            else:
                break  # Commanders are in chronological order
        
        if current_commander:
            # Clip name to 10 characters
            if len(current_commander) > 10:
                return current_commander[:8] + ".."
            return current_commander
        return "N/A"
    
    # Column headers - NO worm stats (those go on scoreboard only)
    scale = config.get_scale_ratio()
    headers = ["Units\nLost", "Units\nKilled", "Bldgs\nKilled", "Bldgs\nBuild/Lost", 
               "Refs/Bio\nBuild/Lost", "HQs/Nest\nBuild/Lost", "Tech\nLevel", "Nodes\nBuild/Lost", "Commander"]
    
    # Get column widths from config (or use defaults)
    base_widths = getattr(config, 'TABLE1_COL_WIDTHS', [55, 55, 55, 85, 85, 85, 45, 85, 90])
    col_widths = [int(w * col1_scale * scale) for w in base_widths]
    row_height = config.TABLE1_ROW_HEIGHT
    header_height = config.TABLE1_HEADER_HEIGHT
    icon_size = config.TABLE1_ICON_SIZE
    
    x_start = 10
    y_pos = 10
    
    # Draw header row (no "Team" header as per requirements)
    x_pos = x_start + icon_size + 10  # Start after icon space
    for i, header in enumerate(headers):
        draw.text((x_pos + col_widths[i]//2, y_pos + 8), header, font=font_header, fill=(200, 200, 200, 255), anchor="mm")
        x_pos += col_widths[i]
    
    y_pos += header_height  # Use smaller header height instead of full row_height
    
    # Draw data rows for each team
    for team_name in ["Sol", "Centauri", "Alien"]:
        if team_name not in kill_stats or team_name not in building_stats:
            continue
        
        x_pos = x_start
        
        # Team logo
        logo_path = os.path.join(config.ICON_DIR, team_logos.get(team_name))
        if os.path.exists(logo_path):
            try:
                logo = Image.open(logo_path).convert("RGBA")
                logo = logo.resize((icon_size, icon_size), Image.BICUBIC)
                
                # Tint logo with team color
                logo_arr = np.array(logo)
                team_color = GRAPH_COLORS.get(team_name, (255, 255, 255))
                
                # Apply team color to white/light pixels
                r = logo_arr[..., 0]
                g = logo_arr[..., 1]
                b = logo_arr[..., 2]
                a = logo_arr[..., 3]
                
                # Mask for bright pixels (logo areas)
                avg_brightness = (r.astype(np.float32) + g.astype(np.float32) + b.astype(np.float32)) / 3.0
                bright_mask = (avg_brightness > 100) & (a > 0)
                
                logo_arr[..., 0][bright_mask] = team_color[0]
                logo_arr[..., 1][bright_mask] = team_color[1]
                logo_arr[..., 2][bright_mask] = team_color[2]
                
                logo = Image.fromarray(logo_arr, mode="RGBA")
                img.alpha_composite(logo, (x_pos, y_pos))
            except Exception as e:
                logging.warning(f"Could not load logo for {team_name}: {e}")
        
        x_pos += icon_size + 10
        
        # Get kill stats
        kill_stats_tuple = kill_stats[team_name].get_stats_at_time(current_time)
        
        # Handle both old format (4 values) and new format (6 values) for backward compatibility
        if len(kill_stats_tuple) >= 6:
            lost_u, lost_b, killed_u, killed_b, _, _ = kill_stats_tuple[:6]  # Ignore worm stats here
        else:
            lost_u, lost_b, killed_u, killed_b = kill_stats_tuple[:4]
        
        # Get building stats
        (hq_built, hq_current, refs_built, refs_current, bio_built, bio_current,
         nodes_built, nodes_lost, tech_level, total_built) = \
            building_stats[team_name].get_stats_at_time(current_time)


        
        # Calculate totalss
        if team_name == "Alien":
            resource_build = bio_built
            resource_lost = bio_built - bio_current
        else:
            resource_build = refs_built
            resource_lost = refs_built - refs_current
        
        hq_lost = hq_built - hq_current

        # Total buildings built: every structure that ever started construction
        bldgs_build = total_built

        
        # Get current commander for this team
        commander = get_team_commander(team_name)
        
        # Data for this team (NO worm stats - those go on scoreboard)
        data = [
            str(lost_u),                                    # Units Lost
            str(killed_u),                                  # Units Killed
            str(killed_b),                                  # Bldgs Killed
            f"{bldgs_build}/{lost_b}",                     # Bldgs Build/Lost
            f"{resource_build}/{resource_lost}",           # Refs/Bio Build/Lost
            f"{hq_built}/{hq_lost}",                       # HQs/Nest Build/Lost
            str(tech_level),                                # Tech Level
            f"{nodes_built}/{nodes_lost}" if team_name == "Alien" else "-",  # Nodes (Alien only)
            commander,                                      # Commander
        ]
        
        color = GRAPH_COLORS.get(team_name, (255, 255, 255))
        
        # Draw each cell
        for i, value in enumerate(data):
            draw.text((x_pos + col_widths[i]//2, y_pos + row_height//2), value, 
                     font=font_data, fill=(*color, 255), anchor="mm")
            x_pos += col_widths[i]
        
        y_pos += row_height
    
    return img




def create_table2_playerboard(player_stats, unit_kill_stats, current_time, width, height):
    """
    Create Table 2: Player Leaderboard / Achievements
    
    UPDATED: Properly filters AI units per requirement
    - Only human players as attackers (except "Deadliest unit")
    - AI victims are allowed for most stats
    - Name clipping to max length
    - Line wrapping for long entries (Sniper God(ess))
    - Height checking to prevent bottom cutoff
    
    Awards:
    - Who's the boss: Human player kills (AI victims OK)
    - Suicide King: Human player suicides
    - Deathwish: Human player deaths (killed by anyone)
    - Griefmaster: Human player teamkills
    - Biggest Troll: Human kills same human most
    - Sniper God(ess): Human longest range (AI victims OK)
    - Harvesterbuster: Human harvester kills (AI victims OK)
    - Most Buildings killed: Human building kills (excludes nodes)
    - NodeGrinder: Human node kills (AI victims OK)
    - Shrimpfetish: Human shrimp kills (AI victims OK)
    - Deadliest unit: ALL units (AI + human)
    
    Returns:
        PIL Image
    """
    img = Image.new("RGBA", (width, height), (*STATS_BG_COLOR, 255))
    draw = ImageDraw.Draw(img)
    
    # Use scaled settings from config
    # Reduce label font size by 2 to fit all entries
    font_label = load_font(max(8, config.TABLE2_LABEL_FONT_SIZE - 2))
    font_data = load_font(config.TABLE2_DATA_FONT_SIZE)
    font_header = load_font(config.TABLE2_LABEL_FONT_SIZE + int(4 * config.get_scale_ratio()))
    
    y_pos = config.TABLE2_Y_START
    x_label = config.TABLE2_X_LABEL
    # Reduce gap between label and data by ~10% (keep 90% of original gap)
    original_gap = config.TABLE2_X_DATA - config.TABLE2_X_LABEL
    x_data = config.TABLE2_X_LABEL + int(original_gap * 0.90)
    # Reduce line height slightly to fit more entries
    line_height = int(config.TABLE2_LINE_HEIGHT * 0.92)
    
    # Calculate available width for data text (reduced since chat takes right half)
    # Width is already passed as reduced (about half of stats panel)
    data_width = width - x_data - 5  # 5px margin on right
    
    # Shorter name limit since space is tighter now
    # But ensure we have room for " -> X (Nx)" suffix
    max_name_len = min(TABLE2_MAX_NAME_LENGTH, 10)
    
    # Add Silica Logo and "Achievements" header
    logo_path = os.path.join(config.ICON_DIR, "Silica_Logo.png")
    header_height = int(40 * config.get_scale_ratio())
    logo_size = int(32 * config.get_scale_ratio())
    if os.path.exists(logo_path):
        try:
            logo = Image.open(logo_path).convert("RGBA")
            logo = logo.resize((logo_size, logo_size), Image.BICUBIC)
            img.alpha_composite(logo, (x_label, y_pos))
            # Draw "Achievements" text next to logo
            draw.text((x_label + logo_size + 10, y_pos + 5), "Achievements", font=font_header, fill=(255, 255, 255, 255))
        except Exception as e:
            # Fallback: just draw text
            draw.text((x_label, y_pos + 5), "Achievements", font=font_header, fill=(255, 255, 255, 255))
    else:
        draw.text((x_label, y_pos + 5), "Achievements", font=font_header, fill=(255, 255, 255, 255))
    
    y_pos += header_height + config.TABLE2_HEADER_SPACING  # Extra spacing after header
    
    # Filter to only human players
    human_players = {name: player for name, player in player_stats.items() if not is_ai_unit(name)}
    
    def clip_name(name, max_len=None):
        """Clip name to maximum length."""
        if max_len is None:
            max_len = max_name_len
        if len(name) > max_len:
            return name[:max_len-2] + ".."
        return name
    
    def draw_entry(label, data_text, allow_wrap=False):
        """Draw an achievement entry, optionally wrapping long data text.
        Returns the y position after drawing (advances by line_height or more)."""
        nonlocal y_pos
        
        # Check if we have space (prevent bottom cutoff)
        if y_pos + line_height > height - 5:
            return False  # No more space
        
        draw.text((x_label, y_pos), label, font=font_label, fill=(200, 200, 200, 255))
        
        if allow_wrap:
            # Check if text fits in available width
            bbox = draw.textbbox((0, 0), data_text, font=font_data)
            text_width = bbox[2] - bbox[0]
            
            if text_width > data_width:
                # Need to wrap - find a good break point
                # For Sniper God(ess), split before the parentheses
                if '(' in data_text:
                    parts = data_text.split('(', 1)
                    line1 = parts[0].rstrip()
                    line2 = '(' + parts[1] if len(parts) > 1 else ''
                    
                    draw.text((x_data, y_pos), line1, font=font_data, fill=(255, 255, 255, 255))
                    y_pos += line_height
                    
                    if y_pos + line_height <= height - 5 and line2:
                        # Draw continuation line indented
                        draw.text((x_data + 10, y_pos), line2, font=font_data, fill=(200, 200, 200, 255))
                        y_pos += line_height
                else:
                    # Simple truncation if no good break point
                    draw.text((x_data, y_pos), data_text[:30] + "..", font=font_data, fill=(255, 255, 255, 255))
                    y_pos += line_height
            else:
                draw.text((x_data, y_pos), data_text, font=font_data, fill=(255, 255, 255, 255))
                y_pos += line_height
        else:
            draw.text((x_data, y_pos), data_text, font=font_data, fill=(255, 255, 255, 255))
            y_pos += line_height
        
        return True
    
    # Helper function to get stats up to current_time for HUMAN PLAYERS ONLY
    def get_player_stats_at_time(player):
        """Get player stats only counting events up to current_time."""
        stats = {
            'total_kills': sum(1 for k in player.kill_events if k.time <= current_time),
            'building_kills': sum(1 for k in player.kill_events if k.time <= current_time and k.is_structure and k.victim_unit != "Node"),  # Exclude nodes
            'harvester_kills': sum(1 for k in player.kill_events if k.time <= current_time and "Harvester" in k.victim_unit),
            'node_kills': sum(1 for k in player.kill_events if k.time <= current_time and k.victim_unit == "Node"),
            'shrimp_kills': sum(1 for k in player.kill_events if k.time <= current_time and k.victim_unit == "Shrimp"),
            'hq_kills': sum(1 for k in player.kill_events if k.time <= current_time and k.victim_unit == "Headquarters"),
            'nest_kills': sum(1 for k in player.kill_events if k.time <= current_time and k.victim_unit == "Nest"),
            'suicide_deaths': sum(1 for d in player.death_events if d.time <= current_time and d.death_type == "suicide"),
            'total_deaths': sum(1 for d in player.death_events if d.time <= current_time),
            'teamkills': sum(1 for k in player.kill_events if k.time <= current_time and k.attacker_team == k.victim_team and not is_ai_unit(k.victim_name)),  # Teamkills only vs humans
        }
        
        # Calculate longest range kill up to current_time
        longest = None
        for kill in player.kill_events:
            if kill.time > current_time:
                continue
            if kill.attacker_x is not None and kill.x is not None:
                range_dist = math.sqrt((kill.x - kill.attacker_x)**2 + (kill.y - kill.attacker_y)**2)
                if longest is None or range_dist > longest[0]:
                    longest = (range_dist, kill.attacker_unit, kill.victim_unit, kill.time)
        stats['longest_range'] = longest
        
        # Calculate kills by victim up to current_time (ONLY HUMAN VICTIMS)
        kills_by_victim = defaultdict(int)
        for kill in player.kill_events:
            if kill.time <= current_time and not is_ai_unit(kill.victim_name):
                kills_by_victim[kill.victim_name] += 1
        stats['kills_by_victim'] = kills_by_victim
        
        return stats
    
    # Helper function to get top human player
    def get_top_player(stat_key, default="N/A"):
        if not human_players:
            return default
        try:
            player_stats_at_time = {name: get_player_stats_at_time(p) for name, p in human_players.items()}
            
            top_name = max(player_stats_at_time.keys(), key=lambda n: player_stats_at_time[n].get(stat_key, 0))
            value = player_stats_at_time[top_name].get(stat_key, 0)
            
            if value > 0:
                return f"{clip_name(top_name)} -> {value}"
            return default
        except (ValueError, AttributeError):
            return default
    
    # Who's the boss
    if not draw_entry("Who's the boss:", get_top_player('total_kills')):
        return img
    
    # Suicide King
    if not draw_entry("Suicide King:", get_top_player('suicide_deaths')):
        return img
    
    # Deathwish (human player deaths - can be killed by anyone including AI)
    if not draw_entry("Deathwish:", get_top_player('total_deaths')):
        return img
    
    # Griefmaster (human player teamkills vs other humans)
    if not draw_entry("Griefmaster:", get_top_player('teamkills')):
        return img
    
    # Biggest Troll (human killed same human most times) - allow wrapping
    troll_text = "N/A"
    try:
        if human_players:
            player_stats_at_time = {name: get_player_stats_at_time(p) for name, p in human_players.items()}
            
            top_troll = None
            max_same_victim_kills = 0
            victim_name = ""
            
            for name, stats in player_stats_at_time.items():
                if stats['kills_by_victim']:
                    victim, count = max(stats['kills_by_victim'].items(), key=lambda x: x[1])
                    if count > max_same_victim_kills:
                        max_same_victim_kills = count
                        top_troll = name
                        victim_name = victim
            
            if top_troll and max_same_victim_kills > 1:
                troll_text = f"{clip_name(top_troll)} -> {clip_name(victim_name)} ({max_same_victim_kills}x)"
    except Exception as e:
        logging.warning(f"Error calculating troll: {e}")
    if not draw_entry("Biggest Troll:", troll_text, allow_wrap=True):
        return img
    
    # Sniper God(ess) (human longest range, AI victims OK) - allow wrapping
    sniper_text = "N/A"
    try:
        if human_players:
            player_stats_at_time = {name: get_player_stats_at_time(p) for name, p in human_players.items()}
            
            top_sniper = None
            max_range = 0
            longest_shot = None
            
            for name, stats in player_stats_at_time.items():
                if stats['longest_range'] and stats['longest_range'][0] > max_range:
                    max_range = stats['longest_range'][0]
                    top_sniper = name
                    longest_shot = stats['longest_range']
            
            if longest_shot:
                range_m, weapon, victim, _ = longest_shot
                sniper_text = f"{clip_name(top_sniper)} -> {range_m:.0f}m ({normalize_unit_name(weapon)} vs {normalize_unit_name(victim)})"
    except Exception as e:
        logging.warning(f"Error calculating sniper: {e}")
    if not draw_entry("Sniper God(ess):", sniper_text, allow_wrap=True):
        return img
    
    # Harvesterbuster
    if not draw_entry("Harvesterbuster:", get_top_player('harvester_kills')):
        return img
    
    # Smasher (Most Buildings killed, excludes nodes)
    if not draw_entry("Smasher:", get_top_player('building_kills')):
        return img
    
    # NodeGrinder
    if not draw_entry("NodeGrinder:", get_top_player('node_kills')):
        return img
    
    # No Home (human player HQ kills)
    if not draw_entry("No Home:", get_top_player('hq_kills')):
        return img
    
    # Exterminator (human player Nest kills)
    if not draw_entry("Exterminator:", get_top_player('nest_kills')):
        return img
    
    # Shrimpfetish
    if not draw_entry("Shrimpfetish:", get_top_player('shrimp_kills')):
        return img
    
    # Deadliest unit (ALL units including AI)
    deadliest_text = "N/A"
    try:
        # Count ALL kills from ALL players (human + AI) up to current_time
        unit_kills_at_time = defaultdict(int)
        for player in player_stats.values():  # Include AI players here!
            for kill in player.kill_events:
                if kill.time <= current_time and kill.attacker_unit and kill.attacker_unit != "Unknown":
                    unit_kills_at_time[kill.attacker_unit] += 1
        
        if unit_kills_at_time:
            unit, kills = max(unit_kills_at_time.items(), key=lambda x: x[1])
            deadliest_text = f"{normalize_unit_name(unit)} -> {kills}"
    except Exception as e:
        logging.warning(f"Error calculating deadliest unit: {e}")
    draw_entry("Deadliest unit:", deadliest_text)
    
    return img




def create_stats_table(stats_dict, current_time, width, height):
    """
    OLD TABLE - NOW REPLACED BY TABLE 1 AND TABLE 2
    This function is kept for backwards compatibility but not used.
    
    Returns:
        PIL Image
    """
    img = Image.new("RGBA", (width, height), (*STATS_BG_COLOR, 255))
    draw = ImageDraw.Draw(img)
    
    font_header = load_font(16)
    font_data = load_font(14)
    
    # Headers
    headers = ["Team", "Lost\nUnits", "Lost\nBldgs", "Killed\nUnits", "Killed\nBldgs"]
    col_widths = [100, 90, 90, 90, 90]
    row_height = 35
    
    x_pos = 10
    y_pos = 10
    
    # Draw header row
    for i, header in enumerate(headers):
        draw.text((x_pos, y_pos), header, font=font_header, fill=(200, 200, 200, 255))
        x_pos += col_widths[i]
    
    y_pos += row_height
    
    # Draw data rows
    for team_name, stats in stats_dict.items():
        lost_u, lost_b, killed_u, killed_b = stats.get_stats_at_time(current_time)
        
        color = GRAPH_COLORS.get(team_name, (255, 255, 255))
        
        x_pos = 10
        
        # Team name
        draw.text((x_pos, y_pos), team_name, font=font_data, fill=(*color, 255))
        x_pos += col_widths[0]
        
        # Stats
        for val in [lost_u, lost_b, killed_u, killed_b]:
            draw.text((x_pos, y_pos), str(val), font=font_data, fill=(255, 255, 255, 255))
            x_pos += col_widths[1]
        
        y_pos += row_height
    
    return img




def render_stats_panel_impl(kill_stats, building_stats, player_stats, unit_kill_stats, commanders, current_time, width, height, resource_stats=None):
    """
    Render the complete stats panel with 2 graphs + 2 tables.
    (Implementation - use render_stats_panel for caching)
    
    Layout:
    - Graph 1: Kill Statistics (top)
    - Graph 2: Building Statistics OR Resource Status (middle) - controlled by config.GRAPH2_MODE
    - Table 1: Team Statistics (below Graph 2)
    - Table 2: Player Leaderboard (below Table 1 with extra spacing)
    """
    panel = Image.new("RGBA", (width, height), (*STATS_BG_COLOR, 255))
    
    # Use scaled heights from config
    graph_height = config.STATS_GRAPH_HEIGHT
    table1_height = config.TABLE1_HEIGHT
    table2_height = config.TABLE2_HEIGHT
    table1_to_table2_gap = config.TABLE1_TO_TABLE2_GAP
    table2_y_offset = config.TABLE2_Y_OFFSET
    
    # Graph 1: Kills (Units + Buildings killed)
    graph1_y = 10
    if USE_PIL_GRAPHS:
        graph1_img = create_kills_graph_pil(kill_stats, current_time, width - 20, graph_height)
    else:
        graph1_img = create_kills_graph(kill_stats, current_time, width - 20, graph_height)
    panel.paste(graph1_img, (10, graph1_y))
    
    # Graph 2: Buildings or Resources (controlled by config.GRAPH2_MODE)
    graph2_y = graph1_y + graph_height + 10
    graph2_mode = getattr(config, 'GRAPH2_MODE', 'buildings')
    
    if graph2_mode == "resources" and resource_stats is not None:
        # Resource status graph (Collected & Spent per team)
        graph2_img = create_resource_graph_pil(resource_stats, current_time, width - 20, graph_height)
    else:
        # Original buildings graph (HQ/Nest, Refs/Bio)
        if USE_PIL_GRAPHS:
            graph2_img = create_buildings_graph_pil(building_stats, current_time, width - 20, graph_height)
        else:
            graph2_img = create_buildings_graph(building_stats, current_time, width - 20, graph_height)
    panel.paste(graph2_img, (10, graph2_y))
    
    # Table 1: Team Statistics (scaled gap after graphs)
    table1_y = graph2_y + graph_height + int(60 * config.get_scale_ratio())
    table1_img = create_table1_team_stats(kill_stats, building_stats, player_stats, commanders, current_time, width, table1_height)
    panel.alpha_composite(table1_img, (10, table1_y))
    
    # Table 2: Player Leaderboard / Achievements (reduced width - chat takes right half)
    table2_y = table1_y + table1_height + table1_to_table2_gap + table2_y_offset
    # Give achievements ~55% of width (chat gets ~45%)
    achievements_width = int((width - 20) * 0.55)
    table2_img = create_table2_playerboard(player_stats, unit_kill_stats, current_time, achievements_width, table2_height)
    panel.alpha_composite(table2_img, (10, table2_y))
    
    return panel


def render_stats_panel(kill_stats, building_stats, player_stats, unit_kill_stats, commanders, current_time, width, height, resource_stats=None):
    """
    Wrapper that calls render_stats_panel_impl.
    Caching is handled by the RenderCache class in render_frame.
    """
    return render_stats_panel_impl(kill_stats, building_stats, player_stats, unit_kill_stats, commanders, current_time, width, height, resource_stats=resource_stats)




def render_frame(base_map, buildings, kills, kill_stats, building_stats, player_stats, unit_kill_stats, commanders, t, heat_overlay_rgba=None, world_extent=WORLD_EXTENT, timing_detail=None, frame_num=0, resources=None, victory_info=None, t_end=None, total_frames=0, map_name=None, log_date=None, chat_messages=None, resource_stats=None, unit_positions=None, dying_units=None):
    """
    Render one frame at game time t (seconds).
    Layout: [MAP | KILLBAR | STATS PANEL]
    
    Args:
        timing_detail: Optional dict to store detailed timing breakdown
        frame_num: Current frame number (for cache invalidation)
        resources: List of Resource namedtuples
        victory_info: VictoryInfo namedtuple or None
        t_end: End time of game (for victory screen timing)
        total_frames: Total number of frames (for victory screen)
        map_name: Map name to display (for cleanlog mode)
        log_date: Date string to display (for cleanlog mode, format: "DD/MM")
    """
    import time as time_module
    
    def record_time(name, start):
        if timing_detail is not None:
            timing_detail[name] = timing_detail.get(name, 0) + (time_module.perf_counter() - start)
        return time_module.perf_counter()
    
    t_start_time = time_module.perf_counter()
    
    # Get render cache
    cache = get_render_cache()
    
    # Map dimensions
    map_w, map_h = base_map.size
    
    # Create full frame: map + killbar + stats
    total_width = map_w + config.KILLBAR_WIDTH + config.STATS_WIDTH
    frame = Image.new("RGBA", (total_width, config.VIDEO_HEIGHT), (20, 20, 20, 255))
    
    t_start_time = record_time('frame_create', t_start_time)
    
    # === MAP SECTION ===
    map_layer = base_map.copy().convert("RGBA")
    
    if heat_overlay_rgba is not None:
        map_layer = Image.alpha_composite(map_layer, heat_overlay_rgba)
    
    frame.paste(map_layer, (0, 0))
    
    t_start_time = record_time('map_composite', t_start_time)
    
    # Draw on map (buildings, kills, etc.)
    draw = ImageDraw.Draw(frame, "RGBA")
    
    # --- Resources ---
    if resources and config.ENABLE_RESOURCE_DISPLAY:
        for res in resources:
            # Skip if not yet spawned
            if res.spawn_t is not None and t < res.spawn_t:
                continue
            
            # Check if depleted
            is_depleted = res.depleted_t is not None and t >= res.depleted_t
            
            # Skip if depleted beyond flash duration
            if is_depleted and t > res.depleted_t + config.RESOURCE_FLASH_DURATION:
                continue
            
            # Determine status (flash when depleted)
            if is_depleted and t <= res.depleted_t + config.RESOURCE_FLASH_DURATION:
                status = "flash"
            else:
                status = "complete"
            
            # Get icon name based on type
            if "Balterium" in res.resource_type:
                icon_name = "Resource_BalteriumField"
                color = config.RESOURCE_COLORS.get("Balterium", (128, 0, 128))
            else:
                icon_name = "Resource_Organics"
                color = config.RESOURCE_COLORS.get("Biotics", (80, 80, 80))
            
            # Get icon with custom color tinting
            icon = get_resource_icon(icon_name, color, status, config.RESOURCE_ICON_SCALE)
            
            x_px, y_px = world_to_pixel(res.x, res.y, map_w, map_h, world_extent)
            
            if icon is not None:
                iw, ih = icon.size
                frame.alpha_composite(icon, (int(x_px - iw / 2), int(y_px - ih / 2)))
            else:
                # Fallback circle
                r = 8
                draw.ellipse((x_px - r, y_px - r, x_px + r, y_px + r), fill=(*color, 150))
    
    t_start_time = record_time('resources', t_start_time)
    
    # --- Buildings ---
    for b in buildings.values():
        if b.start_t is None and b.complete_t is None and b.destroy_t is None and b.sold_t is None:
            continue

        if b.start_t is not None and t < b.start_t:
            continue

        # Building was sold - don't render after sold time
        if b.sold_t is not None and t >= b.sold_t:
            continue

        # Building was destroyed
        if b.destroy_t is not None:
            if t > b.destroy_t + DESTROY_FLASH_DURATION:
                continue

            if b.destroy_t <= t <= b.destroy_t + DESTROY_FLASH_DURATION:
                status = "flash"
            else:
                if b.complete_t is not None and t >= b.complete_t:
                    status = "complete"
                else:
                    status = "construction"
        else:
            if b.complete_t is not None and t >= b.complete_t:
                status = "complete"
            else:
                status = "construction"

        icon = get_icon(b.name, b.team, status, config.ICON_SCALE)
        x_px, y_px = world_to_pixel(b.x, b.y, map_w, map_h, world_extent)

        if icon is not None:
            iw, ih = icon.size
            frame.alpha_composite(icon, (int(x_px - iw / 2), int(y_px - ih / 2)))
        else:
            col = TEAM_COLORS.get(b.team, (255, 255, 255))
            r = 4
            draw.ellipse((x_px - r, y_px - r, x_px + r, y_px + r), fill=(col[0], col[1], col[2], 200))

    t_start_time = record_time('buildings', t_start_time)

    # --- Unit Positions (from .srpl data) ---
    if unit_positions:
        dying_set = set(dying_units or [])
        # Only render units (buildings already rendered from log data)
        units_only = [up for up in unit_positions if up.get("is_unit", True)]
        for up in units_only:
            team = up.get("team_name", "")
            type_name = up.get("type_name", "")
            x_px, y_px = world_to_pixel(up["x"], up["y"], map_w, map_h, world_extent)
            is_player = up.get("controller_name") is not None
            eid = up.get("entity_id")
            is_dying = eid in dying_set

            # Convert display name to ICON_MAP key (remove spaces, handle special cases)
            icon_key = type_name.replace(" ", "")
            if icon_key == "HornedCrab":
                icon_key = "CrabHorned"

            # Scale units like kill icons in the base mod: soldiers smaller, vehicles/structures larger
            if is_soldier(icon_key):
                unit_scale = config.ICON_SCALE * config.KILL_SOLDIER_SCALE
            else:
                unit_scale = config.ICON_SCALE * config.KILL_ICON_SCALE

            # Dying units: flash white
            if is_dying:
                icon = get_icon(icon_key, team, "flash", unit_scale)
            else:
                icon = get_icon(icon_key, team, "complete", unit_scale)

            if icon is not None:
                # AI units: very slightly transparent
                if not is_player and not is_dying:
                    icon = icon.copy()
                    alpha_band = icon.split()[3]
                    alpha_band = alpha_band.point(lambda a: int(a * 0.88))
                    icon.putalpha(alpha_band)
                iw, ih = icon.size
                frame.alpha_composite(icon, (int(x_px - iw / 2), int(y_px - ih / 2)))

                # Player name label above the icon
                if is_player:
                    pname = up["controller_name"]
                    name_font = get_cached_font(config.KILL_NUMBER_FONT_SIZE)
                    bbox = name_font.getbbox(pname)
                    tw = bbox[2] - bbox[0]
                    th = bbox[3] - bbox[1]
                    nx = int(x_px - tw / 2)
                    ny = int(y_px - ih / 2 - th - 2)
                    # Dark outline for readability
                    for ox, oy in ((-1,-1),(-1,1),(1,-1),(1,1),(0,-1),(0,1),(-1,0),(1,0)):
                        draw.text((nx+ox, ny+oy), pname, font=name_font, fill=(0, 0, 0, 220))
                    team_col = TEAM_COLORS.get(team, (255, 255, 255))
                    draw.text((nx, ny), pname, font=name_font, fill=(team_col[0], team_col[1], team_col[2], 255))
            else:
                # Fallback: colored dot (white if dying)
                col = (255, 255, 255) if is_dying else TEAM_COLORS.get(team, (200, 200, 200))
                r = 3 if is_player else 2
                alpha = 255 if is_dying else (200 if is_player else 100)
                draw.ellipse((x_px - r, y_px - r, x_px + r, y_px + r),
                             fill=(col[0], col[1], col[2], alpha))

    t_start_time = record_time('unit_positions', t_start_time)

    # --- Kill Icons and Attack Lines ---
    if ENABLE_KILL_ICONS:
        for ev in kills:
            dt = t - ev.time
            if dt < 0 or dt > KILL_SHOW_SECONDS:
                continue

            # ===== ATTACK LINE =====
            if ENABLE_ATTACK_LINES and dt <= ATTACK_LINE_DRAW_SECONDS:
                progress = dt / ATTACK_LINE_DRAW_SECONDS if ATTACK_LINE_DRAW_SECONDS > 0 else 1.0
                progress = min(1.0, progress)
                
                time_remaining = ATTACK_LINE_DRAW_SECONDS - dt
                line_is_flash = time_remaining <= ATTACK_LINE_FLASH_SECONDS
                
                ax_px, ay_px = world_to_pixel(ev.attacker_x, ev.attacker_y, map_w, map_h, world_extent)
                vx_px, vy_px = world_to_pixel(ev.x, ev.y, map_w, map_h, world_extent)
                
                current_x = ax_px + (vx_px - ax_px) * progress
                current_y = ay_px + (vy_px - ay_px) * progress
                
                if line_is_flash:
                    line_color = (255, 255, 255, 255)
                else:
                    team_col = TEAM_COLORS.get(ev.attacker_team, (255, 255, 255))
                    line_color = (*team_col, 200)
                
                draw.line([(ax_px, ay_px), (current_x, current_y)], fill=line_color, width=config.ATTACK_LINE_WIDTH)

            # ===== VICTIM ICON =====
            time_remaining = KILL_SHOW_SECONDS - dt
            victim_is_flash = time_remaining <= KILL_FLASH_SECONDS
            victim_status = "flash" if victim_is_flash else "complete"

            if is_soldier(ev.victim_unit):
                victim_icon_scale = config.ICON_SCALE * config.KILL_SOLDIER_SCALE
            else:
                victim_icon_scale = config.ICON_SCALE * config.KILL_ICON_SCALE

            victim_icon = get_icon(ev.victim_unit, ev.victim_team, victim_status, victim_icon_scale)
            vx_px, vy_px = world_to_pixel(ev.x, ev.y, map_w, map_h, world_extent)

            if victim_icon is not None:
                iw, ih = victim_icon.size
                frame.alpha_composite(victim_icon, (int(vx_px - iw / 2), int(vy_px - ih / 2)))
            else:
                col = TEAM_COLORS.get(ev.victim_team, (255, 255, 255))
                r = 6
                draw.ellipse((vx_px - r, vy_px - r, vx_px + r, vy_px + r), fill=(col[0], col[1], col[2], 220))

            # ===== KILL NUMBER ABOVE VICTIM =====
            if SHOW_KILL_NUMBERS_ON_MAP:
                number_font = load_font(config.KILL_NUMBER_FONT_SIZE)
                kill_num_str = f"{ev.kill_number}"
                
                bbox = draw.textbbox((0, 0), kill_num_str, font=number_font)
                text_w = bbox[2] - bbox[0]
                
                text_x = vx_px - text_w // 2
                text_y = vy_px + config.KILL_NUMBER_OFFSET_Y
                
                draw.text((text_x, text_y), kill_num_str, font=number_font, fill=(*KILL_NUMBER_COLOR, 255))

            # ===== ATTACKER ICON =====
            attacker_status = "complete"

            if is_soldier(ev.attacker_unit):
                attacker_icon_scale = config.ICON_SCALE * config.KILL_SOLDIER_SCALE
            else:
                attacker_icon_scale = config.ICON_SCALE * config.KILL_ICON_SCALE

            attacker_icon = get_icon(ev.attacker_unit, ev.attacker_team, attacker_status, attacker_icon_scale)
            ax_px, ay_px = world_to_pixel(ev.attacker_x, ev.attacker_y, map_w, map_h, world_extent)

            if attacker_icon is not None:
                iw, ih = attacker_icon.size
                frame.alpha_composite(attacker_icon, (int(ax_px - iw / 2), int(ay_px - ih / 2)))
            else:
                col = TEAM_COLORS.get(ev.attacker_team, (255, 255, 255))
                r = 6
                draw.ellipse((ax_px - r, ay_px - r, ax_px + r, ay_px + r), fill=(col[0], col[1], col[2], 220))

    t_start_time = record_time('kill_icons', t_start_time)

    # --- Clock top-right ---
    font = load_font(config.CLOCK_FONT_SIZE)
    mm = int(t // 60)
    ss = int(t % 60)
    time_str = f"{mm:02d}:{ss:02d}"
    text_color = (255, 255, 255, 230)

    bbox = draw.textbbox((0, 0), time_str, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    x_text = map_w - tw - config.CLOCK_MARGIN
    y_text = config.CLOCK_MARGIN

    draw.rectangle((x_text - config.CLOCK_BOX_MARGIN, y_text - config.CLOCK_BOX_MARGIN, 
                   x_text + tw + config.CLOCK_BOX_MARGIN, y_text + th + config.CLOCK_BOX_MARGIN), 
                   fill=(0, 0, 0, 120))
    draw.text((x_text, y_text), time_str, font=font, fill=text_color)

    # --- Map info overlay (for cleanlog) - top-left ---
    if map_name or log_date:
        map_info_font = load_font(getattr(config, 'MAP_INFO_FONT_SIZE', 20))
        map_info_margin = getattr(config, 'MAP_INFO_MARGIN', 10)
        
        # Build info text: "DD/MM - MapName" or just what's available
        info_parts = []
        if log_date:
            info_parts.append(log_date)
        if map_name:
            info_parts.append(map_name)
        info_text = " - ".join(info_parts) if info_parts else ""
        
        if info_text:
            bbox = draw.textbbox((0, 0), info_text, font=map_info_font)
            info_tw = bbox[2] - bbox[0]
            info_th = bbox[3] - bbox[1]
            
            # Position: top-left with margin
            info_x = map_info_margin
            info_y = map_info_margin
            
            # Background box
            draw.rectangle((info_x - config.CLOCK_BOX_MARGIN, info_y - config.CLOCK_BOX_MARGIN,
                           info_x + info_tw + config.CLOCK_BOX_MARGIN, info_y + info_th + config.CLOCK_BOX_MARGIN),
                           fill=(0, 0, 0, 120))
            draw.text((info_x, info_y), info_text, font=map_info_font, fill=text_color)

    t_start_time = record_time('clock', t_start_time)

    # === VICTORY SCREEN ===
    # Show victory message for last N frames of game
    if victory_info and t_end and config.ENABLE_VICTORY_SCREEN:
        # Calculate if we're in the victory screen period
        victory_screen_duration = config.VICTORY_SCREEN_FRAMES * config.FRAME_STEP
        if t >= t_end - victory_screen_duration:
            # Draw semi-transparent overlay on map
            overlay = Image.new("RGBA", (map_w, map_h), (0, 0, 0, config.VICTORY_BG_ALPHA))
            frame.alpha_composite(overlay, (0, 0))
            
            # Prepare victory text
            victory_font = load_font(config.VICTORY_FONT_SIZE)
            sub_font = load_font(int(config.VICTORY_FONT_SIZE * 0.6))
            
            if victory_info.winning_team:
                # Victory message
                team_color = TEAM_COLORS.get(victory_info.winning_team, (255, 255, 255))
                main_text = f"{victory_info.winning_team} VICTORY!"
                
                # Commander line
                if victory_info.commander:
                    sub_text = f"Commander: {victory_info.commander}"
                else:
                    sub_text = ""
            else:
                # No winner (map change, etc.)
                team_color = (200, 200, 200)
                main_text = f"GAME ENDED"
                sub_text = f"({victory_info.end_type})"
            
            # Draw main text centered on map
            draw = ImageDraw.Draw(frame, "RGBA")
            
            bbox = draw.textbbox((0, 0), main_text, font=victory_font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            x_main = (map_w - tw) // 2
            y_main = (map_h - th) // 2 - int(30 * config.get_scale_ratio())
            
            # Draw shadow/outline for visibility
            for dx, dy in [(-2, -2), (-2, 2), (2, -2), (2, 2), (0, -2), (0, 2), (-2, 0), (2, 0)]:
                draw.text((x_main + dx, y_main + dy), main_text, font=victory_font, fill=(0, 0, 0, 255))
            draw.text((x_main, y_main), main_text, font=victory_font, fill=(*team_color, 255))
            
            # Draw sub text
            if sub_text:
                bbox_sub = draw.textbbox((0, 0), sub_text, font=sub_font)
                tw_sub = bbox_sub[2] - bbox_sub[0]
                x_sub = (map_w - tw_sub) // 2
                y_sub = y_main + th + int(20 * config.get_scale_ratio())
                
                for dx, dy in [(-1, -1), (-1, 1), (1, -1), (1, 1)]:
                    draw.text((x_sub + dx, y_sub + dy), sub_text, font=sub_font, fill=(0, 0, 0, 255))
                draw.text((x_sub, y_sub), sub_text, font=sub_font, fill=(255, 255, 255, 255))

    t_start_time = record_time('victory_screen', t_start_time)

    # === KILLBAR SECTION (CACHED) ===
    if ENABLE_KILLBAR:
        # Killbar uses full height of the column
        killbar_panel = cache.get_killbar(frame_num, kills, t, config.KILLBAR_WIDTH, config.VIDEO_HEIGHT, map_w)
        frame.alpha_composite(killbar_panel, (map_w, 0))

    t_start_time = record_time('killbar', t_start_time)

    # === STATS PANEL (CACHED) ===
    if ENABLE_STATS_PANEL:
        # Get update interval from config
        update_interval = getattr(config, 'GRAPH_UPDATE_INTERVAL', 5)
        
        # Use cached stats panel - only regenerates every N frames
        stats_panel = cache.get_stats_panel(
            frame_num, kill_stats, building_stats, player_stats,
            unit_kill_stats, commanders, t, config.STATS_WIDTH, config.VIDEO_HEIGHT, update_interval,
            resource_stats=resource_stats
        )
        frame.alpha_composite(stats_panel, (map_w + config.KILLBAR_WIDTH, 0))

    t_start_time = record_time('stats_panel', t_start_time)
    
    # === CHAT PANEL (next to achievements in stats area) ===
    if ENABLE_CHAT_PANEL:
        # Calculate position: right side of stats panel, aligned with achievements
        # Get table2_y position (where achievements start)
        graph_height = config.STATS_GRAPH_HEIGHT
        table1_height = config.TABLE1_HEIGHT
        table1_to_table2_gap = config.TABLE1_TO_TABLE2_GAP
        table2_y_offset = config.TABLE2_Y_OFFSET
        
        graph1_y = 10
        graph2_y = graph1_y + graph_height + 10
        table1_y = graph2_y + graph_height + int(60 * config.get_scale_ratio())
        table2_y = table1_y + table1_height + table1_to_table2_gap + table2_y_offset
        
        # Chat panel takes ~45% of stats area (achievements gets ~55%)
        # Position it at the right side, starting at achievements level
        achievements_width = int(config.STATS_WIDTH * 0.55)
        chat_width = config.STATS_WIDTH - achievements_width - 10  # 10px gap between
        chat_height = config.VIDEO_HEIGHT - table2_y - 10  # Leave small margin at bottom
        chat_x = map_w + config.KILLBAR_WIDTH + achievements_width + 10  # After achievements + gap
        
        # Render chat panel
        chat_panel = cache.get_chat_panel(chat_messages, t, chat_width, chat_height, 0)
        frame.alpha_composite(chat_panel, (chat_x, table2_y))
    
    t_start_time = record_time('chat_panel', t_start_time)

    return frame





def make_heatmap_image(base_map, kills, world_extent=WORLD_EXTENT, out_path=None):
    """Simple static image with semi-transparent colored circles at each kill position."""
    if out_path is None or not kills:
        return

    img = base_map.copy().convert("RGBA")
    draw = ImageDraw.Draw(img, "RGBA")
    w, h = img.size

    for ev in kills:
        team_col = TEAM_COLORS.get(ev.victim_team, (255, 255, 255))
        x_px, y_px = world_to_pixel(ev.x, ev.y, w, h, world_extent)
        r = 18
        draw.ellipse(
            (x_px - r, y_px - r, x_px + r, y_px + r),
            fill=(team_col[0], team_col[1], team_col[2], HEATMAP_ALPHA)
        )

    img.save(out_path)
    print(f"Static kill heatmap (team colors) written to: {out_path}")


def render_scoreboard(player_stats, kill_stats, width, height, victory_info=None):
    """
    Render end-game scoreboard showing all players sorted by team.
    
    Shows for each player:
    - Unit kills
    - Structure kills  
    - Deaths
    
    With team totals at top of each team section.
    
    Args:
        player_stats: dict of PlayerStats objects
        kill_stats: dict of TeamStats objects
        width: Frame width
        height: Frame height
        victory_info: VictoryInfo object (optional, for highlighting winner)
    
    Returns:
        PIL Image
    """
    # Get settings from config
    header_font_size = getattr(config, 'SCOREBOARD_HEADER_FONT_SIZE', 32)
    team_font_size = getattr(config, 'SCOREBOARD_TEAM_FONT_SIZE', 26)
    player_font_size = getattr(config, 'SCOREBOARD_PLAYER_FONT_SIZE', 18)
    row_height = getattr(config, 'SCOREBOARD_ROW_HEIGHT', 28)
    team_header_height = getattr(config, 'SCOREBOARD_TEAM_HEADER_HEIGHT', 45)
    bg_alpha = getattr(config, 'SCOREBOARD_BG_ALPHA', 220)
    max_players = getattr(config, 'SCOREBOARD_MAX_PLAYERS_PER_TEAM', 25)
    
    # Create image with semi-transparent dark background
    img = Image.new("RGBA", (width, height), (20, 20, 20, bg_alpha))
    draw = ImageDraw.Draw(img, "RGBA")
    
    # Load fonts
    font_header = load_font(header_font_size)
    font_team = load_font(team_font_size)
    font_player = load_font(player_font_size)
    font_small = load_font(player_font_size - 2)
    
    # Group players by team
    teams_order = ["Sol", "Centauri", "Alien"]
    team_players = {team: [] for team in teams_order}
    
    for player_name, stats in player_stats.items():
        # Skip AI units
        if is_ai_unit(player_name):
            continue
        
        team = stats.team
        if team in team_players:
            # Calculate stats
            unit_kills = stats.unit_kills
            building_kills = stats.building_kills
            total_deaths = stats.total_deaths
            worm_kills = getattr(stats, 'worm_kills', 0)
            worm_deaths = getattr(stats, 'worm_deaths', 0)
            
            team_players[team].append({
                'name': player_name,
                'unit_kills': unit_kills,
                'building_kills': building_kills,
                'deaths': total_deaths,
                'total_kills': unit_kills + building_kills,
                'worm_kills': worm_kills,
                'worm_deaths': worm_deaths,
            })
    
    # Sort players by total kills (descending)
    for team in teams_order:
        team_players[team].sort(key=lambda p: p['total_kills'], reverse=True)
        team_players[team] = team_players[team][:max_players]  # Limit players
    
    # Calculate team totals
    team_totals = {}
    for team in teams_order:
        totals = {
            'unit_kills': sum(p['unit_kills'] for p in team_players[team]),
            'building_kills': sum(p['building_kills'] for p in team_players[team]),
            'deaths': sum(p['deaths'] for p in team_players[team]),
            'worm_kills': sum(p['worm_kills'] for p in team_players[team]),
            'worm_deaths': sum(p['worm_deaths'] for p in team_players[team]),
        }
        team_totals[team] = totals
    
    # Layout calculations
    # Count active teams (teams with players)
    active_teams = [t for t in teams_order if team_players[t]]
    num_teams = len(active_teams)
    
    if num_teams == 0:
        # No players, just return empty scoreboard
        draw.text((width // 2, height // 2), "No player data", font=font_header, 
                  fill=(255, 255, 255, 255), anchor="mm")
        return img
    
    # Header
    header_y = 30
    title = "FINAL SCOREBOARD"
    if victory_info and victory_info.winning_team:
        title = f"VICTORY: {victory_info.winning_team.upper()}"
    
    draw.text((width // 2, header_y), title, font=font_header, 
              fill=(255, 255, 255, 255), anchor="mm")
    
    # Determine column layout based on number of teams
    margin = 40
    col_gap = 30
    total_gap = col_gap * (num_teams - 1)
    col_width = (width - 2 * margin - total_gap) // num_teams
    
    start_y = header_y + 50
    
    # Column headers - now includes Worm Kills and Worm Deaths
    col_headers = ["Player", "Units", "Bldgs", "Deaths", "WormK", "WormD"]
    col_positions = [0.0, 0.42, 0.56, 0.70, 0.82, 0.92]  # Relative positions within column
    
    # Draw each team column
    for team_idx, team in enumerate(active_teams):
        team_color = TEAM_COLORS.get(team, (255, 255, 255))
        
        # Calculate column x position
        col_x = margin + team_idx * (col_width + col_gap)
        
        # Team header background
        is_winner = victory_info and victory_info.winning_team == team
        header_bg_color = (*team_color, 180) if is_winner else (*team_color, 100)
        draw.rectangle(
            [col_x, start_y, col_x + col_width, start_y + team_header_height],
            fill=header_bg_color
        )
        
        # Team name and totals
        totals = team_totals[team]
        team_text = f"{team}"
        totals_text = f"U:{totals['unit_kills']}  B:{totals['building_kills']}  D:{totals['deaths']}  WK:{totals['worm_kills']}  WD:{totals['worm_deaths']}"
        
        draw.text((col_x + col_width // 2, start_y + 12), team_text, font=font_team,
                  fill=(255, 255, 255, 255), anchor="mm")
        draw.text((col_x + col_width // 2, start_y + 34), totals_text, font=font_small,
                  fill=(220, 220, 220, 255), anchor="mm")
        
        # Column headers row
        header_row_y = start_y + team_header_height + 5
        for i, header in enumerate(col_headers):
            x_pos = col_x + int(col_positions[i] * col_width)
            draw.text((x_pos, header_row_y), header, font=font_small,
                      fill=(180, 180, 180, 255))
        
        # Player rows
        player_start_y = header_row_y + row_height
        
        for p_idx, player in enumerate(team_players[team]):
            row_y = player_start_y + p_idx * row_height
            
            # Alternate row background
            if p_idx % 2 == 0:
                draw.rectangle(
                    [col_x, row_y, col_x + col_width, row_y + row_height - 2],
                    fill=(40, 40, 40, 150)
                )
            
            # Player name (truncate if too long)
            name = player['name']
            if len(name) > 18:
                name = name[:16] + ".."
            
            # Draw player data
            x_name = col_x + int(col_positions[0] * col_width)
            x_units = col_x + int(col_positions[1] * col_width)
            x_bldgs = col_x + int(col_positions[2] * col_width)
            x_deaths = col_x + int(col_positions[3] * col_width)
            x_wormk = col_x + int(col_positions[4] * col_width)
            x_wormd = col_x + int(col_positions[5] * col_width)
            
            text_y = row_y + 4
            
            draw.text((x_name, text_y), name, font=font_player, fill=(*team_color, 255))
            draw.text((x_units, text_y), str(player['unit_kills']), font=font_player, 
                      fill=(255, 255, 255, 255))
            draw.text((x_bldgs, text_y), str(player['building_kills']), font=font_player,
                      fill=(255, 255, 255, 255))
            draw.text((x_deaths, text_y), str(player['deaths']), font=font_player,
                      fill=(255, 200, 200, 255))
            # Worm stats - yellow/orange for visibility
            draw.text((x_wormk, text_y), str(player['worm_kills']), font=font_player,
                      fill=(255, 220, 100, 255))
            draw.text((x_wormd, text_y), str(player['worm_deaths']), font=font_player,
                      fill=(255, 180, 100, 255))
    
    # Footer with game info
    footer_y = height - 40
    footer_text = "Press any key to continue..."
    draw.text((width // 2, footer_y), footer_text, font=font_small,
              fill=(120, 120, 120, 255), anchor="mm")
    
    return img


