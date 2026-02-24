# -*- coding: utf-8 -*-
"""
Log Parser Module

Functions for parsing game log files.
Supports two log formats:
  - "latestlog": Standard MelonLoader format [HH:MM:SS.mmm]
  - "cleanlog": Clean log format L MM/DD/YYYY - HH:MM:SS:
"""

import re
from collections import defaultdict
import logging
from data_models import Building, KillEvent, DeathEvent, Resource, VictoryInfo, ChatMessage, ResourceStatusEvent
from config import WORLD_EXTENT
from icon_config import normalize_unit_name, ICON_MAP

# Import LOG_FORMAT with fallback default
try:
    from config import LOG_FORMAT
except ImportError:
    LOG_FORMAT = "latestlog"


def parse_time_to_seconds(line: str, log_format: str = None) -> float:
    """
    Extract timestamp from a log line and convert to absolute seconds.
    
    Supports two formats:
      - latestlog: [HH:MM:SS.mmm] -> seconds with milliseconds
      - cleanlog: L MM/DD/YYYY - HH:MM:SS: -> seconds (no milliseconds)
    
    Args:
        line: Log line to parse
        log_format: "latestlog" or "cleanlog". If None, uses config.LOG_FORMAT
    
    Returns:
        float: Time in seconds, or None if no timestamp found
    """
    if log_format is None:
        log_format = LOG_FORMAT
    
    if log_format == "cleanlog":
        # Format: L MM/DD/YYYY - HH:MM:SS:
        m = re.search(r'L \d{2}/\d{2}/\d{4} - (\d{2}):(\d{2}):(\d{2}):', line)
        if not m:
            return None
        h, m_, s = map(int, m.groups())
        return h * 3600 + m_ * 60 + s
    else:
        # Format: [HH:MM:SS.mmm]
        m = re.search(r"\[(\d{2}):(\d{2}):(\d{2})\.(\d{3})\]", line)
        if not m:
            return None
        h, m_, s, ms = map(int, m.groups())
        return h * 3600 + m_ * 60 + s + ms / 1000.0


def detect_log_format(lines: list) -> str:
    """
    Auto-detect the log format from the first few lines.
    
    Args:
        lines: List of log lines
    
    Returns:
        str: "latestlog" or "cleanlog"
    """
    for line in lines[:20]:  # Check first 20 lines
        if re.search(r'L \d{2}/\d{2}/\d{4} - \d{2}:\d{2}:\d{2}:', line):
            return "cleanlog"
        if re.search(r'\[\d{2}:\d{2}:\d{2}\.\d{3}\]', line):
            return "latestlog"
    return "latestlog"  # Default


def world_to_pixel(x, y, img_w, img_h, extent=WORLD_EXTENT):
    """Map world coordinates [-extent, extent] to image pixels."""
    px = (x + extent) / (2 * extent) * img_w
    py = (1 - (y + extent) / (2 * extent)) * img_h
    return int(round(px)), int(round(py))


def parse_buildings_and_kills_from_log(log_path: str, gametype_filter: str = None, game_index: int = 0, log_format: str = None):
    """
    Parse the given log for a single game.
    
    Args:
        log_path: Path to log file
        gametype_filter: Optional game type to filter for (e.g., "HUMANS_VS_HUMANS_VS_ALIENS", 
                        "HUMANS2_VS_ALIENS"). If None, matches any game type.
        game_index: Which game to parse (0 = first matching game, 1 = second, etc.)
        log_format: "latestlog", "cleanlog", or None for auto-detect
    
    Returns tuple of 12 elements:
        buildings, kills, deaths, commanders, team_tech_events, 
        resources, victory_info, t_start, t_end, game_info, chat_messages, resource_status_events
        
    game_info is a dict with:
        - 'date': Date string (DD/MM/YYYY or None)
        - 'time': Time string (HH:MM:SS or None)  
        - 'gametype': Game type string
        - 'gametype_short': Short game type (HvHvA, HvA, HvH)
    """
    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    # Auto-detect log format if not specified
    if log_format is None:
        log_format = detect_log_format(lines)
        logging.info(f"Auto-detected log format: {log_format}")

    in_game = False
    t0 = None
    t_end = None
    games_found = 0  # Count of matching games we've found
    
    # Midnight rollover handling
    last_raw_time = None  # Track raw time before offset
    time_offset = 0  # Accumulated offset for midnight rollovers
    
    # Game info to extract
    game_info = {
        'date': None,
        'time': None,
        'gametype': None,
        'gametype_short': None,
        'start_line': None,
    }

    tmp = defaultdict(lambda: {
        "team": None, "name": None, "x": None, "y": None,
        "start_t": None, "complete_t": None, "destroy_t": None, "sold_t": None,
    })
    
    resource_tmp = {}
    kills = []
    kill_counter = 0

    # Regex patterns - gametype filter is optional
    if gametype_filter:
        re_round_start = re.compile(r'World triggered "Round_Start" \(gamemode "MP_Strategy"\) \(gametype "%s"\)' % re.escape(gametype_filter))
    else:
        re_round_start = re.compile(r'World triggered "Round_Start" \(gamemode "MP_Strategy"\) \(gametype "[^"]+"\)')
    
    # Also track any Round_Start for end detection
    re_any_round_start = re.compile(r'World triggered "Round_Start"')
    
    # Regex to extract gametype from any Round_Start
    re_gametype = re.compile(r'\(gametype "([^"]+)"\)')
    
    re_round_win = re.compile(r'World triggered "Round_Win"')
    re_queued_map = re.compile(r'Queued map:')
    # Match admin endround command, not player chat containing "endround"
    re_endround = re.compile(r'\[Admin Mod\].*command.*endround', re.IGNORECASE)
    
    re_construction = re.compile(
        r'Team "([^"]+)" triggered "construction_(start|complete)" '
        r'\(building_name "([^"]+)"\) \(building_position "([^"]+)"\)'
    )
    
    re_structure_sold = re.compile(
        r'Team "([^"]+)" triggered "structure_sold" '
        r'\(building_name "([^"]+)"\) \(building_position "([^"]+)"\)'
    )
    
    re_tech_change = re.compile(r'Team "(?P<team>[^"]+)" triggered "technology_change" \(tier "(?P<tier>\d+)"\)')
    
    re_struct_kill = re.compile(
        r'"([^"<]+)<([^>]*)><[^>]*><([^">]*)>" triggered "structure_kill" '
        r'\(structure "([^"]+)"\).*?\(struct_team "([^"]*)"\).*?\(building_position "([^"]+)"\)'
    )
    
    re_unit_kill = re.compile(
        r'"(?P<att_name>[^"<]+)<[^>]*><[^>]*><(?P<att_team>[^">]*)>" '
        r'killed "(?P<v_name>[^"<]+)<[^>]*><[^>]*><(?P<v_team>[^">]*)>" '
        r'with "(?P<weapon>[^"]+)" \(dmgtype "[^"]*"\) '
        r'\(victim "(?P<victim_unit>[^"]+)"\) '
        r'\(attacker_position "(?P<att_pos>[^"]+)"\) '
        r'\(victim_position "(?P<v_pos>[^"]+)"\)'
    )
    
    re_suicide = re.compile(r'"(?P<player_name>[^"<]+)<[^>]*><[^>]*><(?P<team>[^">]*)>" committed suicide')
    re_commander = re.compile(r'"(?P<player_name>[^"<]+)<[^>]*><[^>]*><(?P<team>[^">]*)>" changed role to "Commander"')
    re_victory = re.compile(r'Team "(?P<team>[^"]+)" triggered "Victory"')
    re_resource_spawned = re.compile(r'World triggered "Resource_Spawned" \(type "(?P<type>[^"]+)"\s*\) \(amount "(?P<amount>\d+)"\) \(position "(?P<pos>[^"]+)"\)')
    re_resource_depleted = re.compile(r'World triggered "Resource_Depleted".*?\(position "(?P<pos>[^"]+)"\)')
    
    # Chat message patterns - only player messages (say and say_team)
    re_chat_say = re.compile(r'"(?P<player_name>[^"<]+)<[^>]*><[^>]*><(?P<team>[^">]*)>" say "(?P<message>.+)"')
    re_chat_say_team = re.compile(r'"(?P<player_name>[^"<]+)<[^>]*><[^>]*><(?P<team>[^">]*)>" say_team "(?P<message>.+)"')
    
    # Resource status pattern
    re_resource_status = re.compile(r'Team "(?P<team>[^"]+)" triggered "resource_status" \(collected "(?P<collected>\d+)"\) \(spent "(?P<spent>\d+)"\)')


    deaths = []
    commanders = {}
    team_tech_events = defaultdict(list)
    victory_info = None
    chat_messages = []
    resource_status_events = []

    for line in lines:
        raw_time = parse_time_to_seconds(line, log_format)
        if raw_time is None:
            continue
        
        # Handle midnight rollover (time goes backwards significantly)
        # This happens when the game crosses midnight (23:59 -> 00:00)
        if last_raw_time is not None:
            if raw_time < last_raw_time - 3600:  # More than 1 hour backwards = midnight
                time_offset += 86400  # Add 24 hours
                logging.info(f"Midnight rollover detected at raw_time={raw_time:.0f}s, adding 24h offset (total offset: {time_offset}s)")
        
        last_raw_time = raw_time
        t_abs = raw_time + time_offset  # Apply accumulated offset

        # Check for victory (can appear before Round_Win)
        m_victory = re_victory.search(line)
        if m_victory and in_game:
            winning_team = m_victory.group("team")
            t = t_abs - t0 if t0 else 0
            commander = None
            if winning_team in commanders and commanders[winning_team]:
                commander = commanders[winning_team][-1][1]
            victory_info = VictoryInfo(winning_team, commander, "Victory", t)

        # Check for Round_Start
        # Use specific gametype filter for starting a game, but any Round_Start ends current game
        if in_game and re_any_round_start.search(line):
            # Any Round_Start while in game = end of current game
            t = t_abs - t0 if t0 else 0
            t_end = t
            if victory_info is None:
                victory_info = VictoryInfo(None, None, "NewRound", t)
            break
        
        if not in_game and re_round_start.search(line):
            # Found a matching Round_Start
            if games_found == game_index:
                # This is the game we want to parse
                in_game = True
                t0 = t_abs
                game_info['start_line'] = line
                
                # Extract gametype
                gametype_match = re_gametype.search(line)
                if gametype_match:
                    game_info['gametype'] = gametype_match.group(1)
                    # Convert to short form
                    gt = game_info['gametype']
                    if gt == "HUMANS_VS_HUMANS_VS_ALIENS":
                        game_info['gametype_short'] = "HvHvA"
                    elif gt == "HUMANS_VS_ALIENS" or gt == "HUMANS2_VS_ALIENS":
                        game_info['gametype_short'] = "HvA"
                    elif gt == "HUMANS_VS_HUMANS":
                        game_info['gametype_short'] = "HvH"
                    else:
                        game_info['gametype_short'] = gt[:10]  # Truncate long names
                
                # Extract date/time from line
                if log_format == "cleanlog":
                    # CleanLog format: L MM/DD/YYYY - HH:MM:SS:
                    cleanlog_match = re.search(r'L (\d{2})/(\d{2})/(\d{4}) - (\d{2}):(\d{2}):(\d{2}):', line)
                    if cleanlog_match:
                        month, day, year, hour, minute, second = cleanlog_match.groups()
                        game_info['date'] = f"{day}/{month}/{year}"
                        game_info['time'] = f"{hour}:{minute}"
                else:
                    # LatestLog format: [HH:MM:SS.mmm]
                    latestlog_match = re.search(r'\[(\d{2}):(\d{2}):(\d{2})\.\d{3}\]', line)
                    if latestlog_match:
                        hour, minute, second = latestlog_match.groups()
                        game_info['time'] = f"{hour}:{minute}"
                        # LatestLog doesn't have date info
                
            games_found += 1
            continue

        if not in_game:
            # Parse resources before round starts
            m_res = re_resource_spawned.search(line)
            if m_res:
                res_type = m_res.group("type").strip()
                amount = int(m_res.group("amount"))
                pos_str = m_res.group("pos")
                try:
                    parts = pos_str.split()
                    x, y = float(parts[0]), float(parts[1])
                    key = (round(x, 1), round(y, 1))
                    resource_tmp[key] = {"type": res_type, "amount": amount, "x": x, "y": y, "spawn_t": 0.0, "depleted_t": None}
                except:
                    pass
            continue

        t = t_abs - t0

        # End conditions
        if re_round_win.search(line) or re_queued_map.search(line) or re_endround.search(line):
            t_end = t
            if victory_info is None:
                if re_queued_map.search(line):
                    victory_info = VictoryInfo(None, None, "MapChange", t)
                else:
                    victory_info = VictoryInfo(None, None, "RoundEnd", t)
            break
        
        # Resource spawned
        m_res = re_resource_spawned.search(line)
        if m_res:
            res_type = m_res.group("type").strip()
            amount = int(m_res.group("amount"))
            pos_str = m_res.group("pos")
            try:
                parts = pos_str.split()
                x, y = float(parts[0]), float(parts[1])
                key = (round(x, 1), round(y, 1))
                resource_tmp[key] = {"type": res_type, "amount": amount, "x": x, "y": y, "spawn_t": t, "depleted_t": None}
            except:
                pass
            continue
        
        # Resource depleted
        m_depleted = re_resource_depleted.search(line)
        if m_depleted:
            pos_str = m_depleted.group("pos")
            try:
                parts = pos_str.split()
                x, y = float(parts[0]), float(parts[1])
                key = (round(x, 1), round(y, 1))
                if key in resource_tmp:
                    resource_tmp[key]["depleted_t"] = t
            except:
                pass
            continue
        
        # Commander changes
        m_cmd = re_commander.search(line)
        if m_cmd:
            player_name = m_cmd.group("player_name")
            team = m_cmd.group("team")
            if team and team != "Unknown":
                if team not in commanders:
                    commanders[team] = []
                commanders[team].append((t, player_name))
            continue
        
        # Chat messages (say and say_team) - only player messages
        m_chat_team = re_chat_say_team.search(line)
        if m_chat_team:
            player_name = m_chat_team.group("player_name")
            team = m_chat_team.group("team")
            message = m_chat_team.group("message")
            # Only include messages from players with a team (not server or empty team)
            if team and team not in ("", "Unknown"):
                chat_messages.append(ChatMessage(t, player_name, team, message, True))
            continue
        
        m_chat = re_chat_say.search(line)
        if m_chat:
            player_name = m_chat.group("player_name")
            team = m_chat.group("team")
            message = m_chat.group("message")
            # Only include messages from players with a team (not server or empty team)
            if team and team not in ("", "Unknown"):
                chat_messages.append(ChatMessage(t, player_name, team, message, False))
            continue
        
        # Tech change
        m_tech = re_tech_change.search(line)
        if m_tech:
            team = m_tech.group("team")
            tier = int(m_tech.group("tier"))
            team_tech_events[team].append((t, tier))
            continue

        # Resource status
        m_res_status = re_resource_status.search(line)
        if m_res_status:
            team = m_res_status.group("team")
            collected = int(m_res_status.group("collected"))
            spent = int(m_res_status.group("spent"))
            resource_status_events.append(ResourceStatusEvent(t, team, collected, spent))
            continue

        # Construction
        m_c = re_construction.search(line)
        if m_c:
            team, status, name, pos_str = m_c.group(1), m_c.group(2), m_c.group(3), m_c.group(4)
            try:
                parts = pos_str.split()
                x, y = float(parts[0]), float(parts[1])
            except:
                continue
            key = (team, name, x, y)
            rec = tmp[key]
            rec["team"], rec["name"], rec["x"], rec["y"] = team, name, x, y
            if status == "start" and rec["start_t"] is None:
                rec["start_t"] = t
            elif status == "complete" and rec["complete_t"] is None:
                rec["complete_t"] = t
            continue

        # Structure sold
        m_sold = re_structure_sold.search(line)
        if m_sold:
            team, name, pos_str = m_sold.group(1), m_sold.group(2), m_sold.group(3)
            try:
                parts = pos_str.split()
                x, y = float(parts[0]), float(parts[1])
            except:
                continue
            key = (team, name, x, y)
            rec = tmp[key]
            if rec["team"] is None:
                rec["team"], rec["name"], rec["x"], rec["y"] = team, name, x, y
            if rec["sold_t"] is None:
                rec["sold_t"] = t
            continue

        # Structure kill
        m_s = re_struct_kill.search(line)
        if m_s:
            attacker_name, attacker_steamid, attacker_team = m_s.group(1), m_s.group(2), m_s.group(3) or "Unknown"
            struct_name, victim_team, pos_str = m_s.group(4), m_s.group(5) or "Unknown", m_s.group(6)
            weapon_match = re.search(r'\(weapon "([^"]+)"\)', line)
            attacker_unit = weapon_match.group(1) if weapon_match else "Unknown"
            try:
                parts = pos_str.split()
                x, y = float(parts[0]), float(parts[1])
            except:
                continue
            key = (victim_team, struct_name, x, y)
            rec = tmp[key]
            if rec["team"] is None:
                rec["team"], rec["name"], rec["x"], rec["y"] = victim_team, struct_name, x, y
            if rec["destroy_t"] is None:
                rec["destroy_t"] = t
            # Skip AI structure kills (no steamID = AI attacker)
            if not attacker_steamid:
                continue
            kill_counter += 1
            kills.append(KillEvent(t, x, y, victim_team, struct_name, attacker_team, attacker_unit, x, y, attacker_name, struct_name, True, kill_counter))
            continue

        # Unit kill
        m_k = re_unit_kill.search(line)
        if m_k:
            attacker_name = m_k.group("att_name")
            attacker_team = m_k.group("att_team") or "Unknown"
            victim_name = m_k.group("v_name")
            victim_team = m_k.group("v_team") or "Unknown"
            weapon = m_k.group("weapon")
            victim_unit = m_k.group("victim_unit")
            try:
                v_parts = m_k.group("v_pos").split()
                vx, vy = float(v_parts[0]), float(v_parts[1])
                a_parts = m_k.group("att_pos").split()
                ax, ay = float(a_parts[0]), float(a_parts[1])
            except:
                continue
            kill_counter += 1
            kills.append(KillEvent(t, vx, vy, victim_team, victim_unit, attacker_team, weapon, ax, ay, attacker_name, victim_name, False, kill_counter))
            deaths.append(DeathEvent(t, victim_name, victim_team, "teamkill" if attacker_team == victim_team else "killed", vx, vy))
            continue

        # Suicide
        m_suicide = re_suicide.search(line)
        if m_suicide:
            player_name = m_suicide.group("player_name")
            team = m_suicide.group("team") or "Unknown"
            deaths.append(DeathEvent(t, player_name, team, "suicide", None, None))
            continue

    # Infer t_end
    if t_end is None:
        t_end = 0.0
        for rec in tmp.values():
            for field in ("start_t", "complete_t", "destroy_t", "sold_t"):
                if rec[field] is not None:
                    t_end = max(t_end, rec[field])
        for k in kills:
            t_end = max(t_end, k.time)

    # Convert to namedtuples
    buildings = {}
    for key, rec in tmp.items():
        if rec["start_t"] is None and rec["complete_t"] is None and rec["destroy_t"] is None and rec["sold_t"] is None:
            continue
        buildings[key] = Building(rec["team"], rec["name"], rec["x"], rec["y"], rec["start_t"], rec["complete_t"], rec["destroy_t"], rec["sold_t"])
    
    resources = [Resource(r["type"], r["x"], r["y"], r["amount"], r["spawn_t"], r["depleted_t"]) for r in resource_tmp.values()]

    print(f"Parsed {len(buildings)} buildings, {len(kills)} kills, {len(deaths)} deaths, {len(resources)} resources, {len(chat_messages)} chat messages, {len(resource_status_events)} resource status events")
    if victory_info:
        print(f"Game end: {victory_info.end_type}" + (f" - Winner: {victory_info.winning_team}" if victory_info.winning_team else ""))
    print(f"Game length: {t_end:.1f}s")
    if game_info['gametype']:
        print(f"Game type: {game_info['gametype']} ({game_info['gametype_short']})")
    if game_info['date']:
        print(f"Game date: {game_info['date']} {game_info['time']}")

    return buildings, kills, deaths, commanders, team_tech_events, resources, victory_info, 0.0, t_end, game_info, chat_messages, resource_status_events


def list_games_in_log(log_path: str):
    """
    List all games found in a log file (simple version).
    For more detailed detection including end reasons, use detect_games_in_log().
    
    Returns list of dicts with game info:
        [{
            'line_num': int,
            'start_time': str (HH:MM:SS),
            'gametype': str,
            'map_name': str,
            'duration_estimate': float (seconds, rough estimate),
            'index': int (overall game index),
        }, ...]
    """
    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    
    re_round_start = re.compile(r'World triggered "Round_Start" \(gamemode "MP_Strategy"\) \(gametype "(?P<gametype>[^"]+)"\)')
    re_loading_map = re.compile(r'Loading map "(?P<map>[^"]+)"')
    
    games = []
    last_time = None
    current_map = "Unknown"
    
    for i, line in enumerate(lines, 1):
        # Track map changes
        m_map = re_loading_map.search(line)
        if m_map:
            current_map = m_map.group('map')
        
        m = re_round_start.search(line)
        if m:
            t_abs = parse_time_to_seconds(line)
            gametype = m.group('gametype')
            
            # Update duration estimate for previous game
            if games and last_time is not None and t_abs is not None:
                games[-1]['duration_estimate'] = t_abs - last_time
            
            # Extract time string from line
            time_match = re.search(r'\[(\d{2}:\d{2}:\d{2})\.\d{3}\]', line)
            time_str = time_match.group(1) if time_match else "??:??:??"
            
            game_info = {
                'line_num': i,
                'start_time': time_str,
                'gametype': gametype,
                'map_name': current_map,
                'duration_estimate': None,  # Will be updated when next game starts
                'index': len(games),  # Overall index
            }
            
            games.append(game_info)
            last_time = t_abs
    
    return games


def detect_games_in_log(log_path: str, min_duration: float = 0):
    """
    Detect all games in a log file with detailed end condition tracking.
    
    This function properly handles:
    - Round_Win endings
    - Victory triggers (with winning team)
    - Map changes (Queued map)
    - Admin endround commands
    - Round_Start on same map (game transition without explicit end)
    - Midnight rollover (time going backwards)
    
    Args:
        log_path: Path to log file
        min_duration: Minimum game duration in seconds (games shorter are marked but included)
    
    Returns:
        List of game dicts:
        [{
            'start_line': int,
            'end_line': int or None,
            'start_time': str (HH:MM:SS),
            'end_time': str (HH:MM:SS) or None,
            'gametype': str,
            'map_name': str,
            'duration': float (seconds) or None,
            'end_reason': str ('Round_Win', 'Victory', 'MapChange', 'AdminEnd', 'NewRound', 'LogEnd', None),
            'winner': str or None (team name if Victory detected),
            'next_map': str or None (if MapChange),
            'valid': bool (True if duration >= min_duration),
        }, ...]
    """
    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    
    # Regex patterns
    re_round_start = re.compile(r'World triggered "Round_Start" \(gamemode "MP_Strategy"\) \(gametype "(?P<gametype>[^"]+)"\)')
    re_round_win = re.compile(r'World triggered "Round_Win"')
    re_victory = re.compile(r'Team "(?P<team>[^"]+)" triggered "Victory"')
    re_queued_map = re.compile(r'Queued map:\s*(?P<map>\S+)|Queued map:\s*(?P<map2>[^\s]+)\s+with')
    re_loading_map = re.compile(r'Loading map "(?P<map>[^"]+)"')
    re_endround = re.compile(r'\[Admin Mod\].*command.*endround', re.IGNORECASE)
    
    games = []
    current_game = None
    current_map = "Unknown"
    last_time = None
    time_offset = 0  # For midnight rollover
    pending_victory = None  # Store victory info until game ends
    
    for i, line in enumerate(lines, 1):
        t_abs = parse_time_to_seconds(line)
        
        # Handle midnight rollover (time goes backwards significantly)
        if t_abs is not None and last_time is not None:
            if t_abs < last_time - 3600:  # More than 1 hour backwards = midnight
                time_offset += 86400  # Add 24 hours
        
        if t_abs is not None:
            t_abs += time_offset
            last_time = t_abs
        
        # Extract time string
        time_match = re.search(r'\[(\d{2}:\d{2}:\d{2})\.\d{3}\]', line)
        time_str = time_match.group(1) if time_match else None
        
        # Track map changes (Loading map)
        m_map = re_loading_map.search(line)
        if m_map:
            current_map = m_map.group('map')
        
        # Check for Victory (store it, will be associated with game end)
        m_victory = re_victory.search(line)
        if m_victory and current_game:
            pending_victory = m_victory.group('team')
        
        # Check for Queued map (map change)
        m_queued = re_queued_map.search(line)
        next_map_name = None
        if m_queued:
            next_map_name = m_queued.group('map') or m_queued.group('map2')
        
        # Check for Round_Start
        m_start = re_round_start.search(line)
        if m_start:
            # If we have a current game, this Round_Start ends it
            if current_game:
                current_game['end_line'] = i
                current_game['end_time'] = time_str
                if t_abs and current_game.get('start_t'):
                    current_game['duration'] = t_abs - current_game['start_t']
                
                # End reason: NewRound (same map, no explicit end)
                if current_game['end_reason'] is None:
                    current_game['end_reason'] = 'NewRound'
                
                # Apply pending victory
                if pending_victory and current_game['end_reason'] in ('NewRound', None):
                    current_game['winner'] = pending_victory
                    current_game['end_reason'] = 'Victory'
                
                # Check validity
                if current_game['duration']:
                    current_game['valid'] = current_game['duration'] >= min_duration
                
                games.append(current_game)
                pending_victory = None
            
            # Start new game
            current_game = {
                'start_line': i,
                'end_line': None,
                'start_time': time_str,
                'end_time': None,
                'start_t': t_abs,  # Internal use
                'gametype': m_start.group('gametype'),
                'map_name': current_map,
                'duration': None,
                'end_reason': None,
                'winner': None,
                'next_map': None,
                'valid': False,
            }
            continue
        
        # Check for end conditions (only if in a game)
        if current_game:
            ended = False
            
            # Round_Win
            if re_round_win.search(line):
                current_game['end_reason'] = 'Round_Win'
                if pending_victory:
                    current_game['winner'] = pending_victory
                    current_game['end_reason'] = 'Victory'
                ended = True
            
            # Admin endround
            elif re_endround.search(line):
                current_game['end_reason'] = 'AdminEnd'
                ended = True
            
            # Map change (Queued map)
            elif m_queued:
                current_game['end_reason'] = 'MapChange'
                current_game['next_map'] = next_map_name
                ended = True
            
            if ended:
                current_game['end_line'] = i
                current_game['end_time'] = time_str
                if t_abs and current_game.get('start_t'):
                    current_game['duration'] = t_abs - current_game['start_t']
                
                # Check validity
                if current_game['duration']:
                    current_game['valid'] = current_game['duration'] >= min_duration
                
                games.append(current_game)
                current_game = None
                pending_victory = None
    
    # Handle game still in progress at end of log
    if current_game:
        current_game['end_reason'] = 'LogEnd'
        if last_time and current_game.get('start_t'):
            current_game['duration'] = last_time - current_game['start_t']
        if current_game['duration']:
            current_game['valid'] = current_game['duration'] >= min_duration
        games.append(current_game)
    
    # Clean up internal fields
    for game in games:
        game.pop('start_t', None)
    
    return games


def get_game_index(log_path: str, gametype_filter: str = None, map_filter: str = None, min_duration: float = 300):
    """
    Find the index of a specific game matching filters.
    
    Args:
        log_path: Path to log file
        gametype_filter: Game type to match (e.g., "HUMANS2_VS_ALIENS")
        map_filter: Map name to match (e.g., "GreatErg")
        min_duration: Minimum game duration in seconds (default 5 minutes)
    
    Returns:
        game_index to use with parse_buildings_and_kills_from_log, or None if not found
    """
    games = list_games_in_log(log_path)
    
    matching_index = 0
    for game in games:
        # Check gametype filter
        if gametype_filter and game['gametype'] != gametype_filter:
            continue
        
        # Check map filter
        if map_filter and game['map_name'] != map_filter:
            continue
        
        # Check minimum duration
        if game['duration_estimate'] and game['duration_estimate'] < min_duration:
            matching_index += 1
            continue
        
        # This game matches - but we need to return the index within filtered games
        # for use with parse_buildings_and_kills_from_log
        return matching_index
        
        matching_index += 1
    
    return None
