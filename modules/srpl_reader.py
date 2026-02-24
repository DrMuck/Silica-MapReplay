# -*- coding: utf-8 -*-
"""
SRPL Reader Module - Parses .srpl binary replay files for MapReplay integration.

Provides unit/building position data at any game time, indexed by tick.
Supports format v1 (no player info) and v2 (with player tracking).
"""

import struct
import os
import logging

logger = logging.getLogger(__name__)

# Team index -> team name (matches Silica's Team.Index)
TEAM_NAMES = {
    0: "Alien",
    1: "Wildlife",
    2: "GM",
    3: "Centauri",
    4: "Sol",
    255: "Unknown",
}


def _read_string(f):
    """Read a uint8-length-prefixed UTF-8 string."""
    length = struct.unpack("B", f.read(1))[0]
    return f.read(length).decode("utf-8", errors="replace")


class SrplEntity:
    """A registered entity (unit or building) from the replay."""
    __slots__ = ("entity_id", "team_idx", "team_name", "type_name",
                 "is_unit", "controller_id", "controller_name", "reg_x", "reg_y")

    def __init__(self, entity_id, team_idx, type_name, is_unit, controller_id, x, y):
        self.entity_id = entity_id
        self.team_idx = team_idx
        self.team_name = TEAM_NAMES.get(team_idx, "Unknown")
        self.type_name = type_name
        self.is_unit = is_unit
        self.controller_id = controller_id
        self.controller_name = None  # filled in after parsing
        self.reg_x = x
        self.reg_y = y


class SrplReplay:
    """Parsed .srpl replay with time-indexed position lookups."""

    def __init__(self):
        self.version = 0
        self.tick_interval_ms = 2000
        self.map_name = ""
        self.game_type = ""
        self.start_timestamp = 0

        self.types = {}       # type_id -> type_name
        self.entities = {}    # entity_id -> SrplEntity
        self.players = {}     # player_id -> (team_idx, player_name)

        # Tick data: tick_number -> {entity_id: (x, y)}
        self.ticks = {}
        self.tick_numbers = []  # sorted list of tick numbers

        # Destruction events: list of (tick, victim_id, attacker_id, is_building)
        self.destructions = []

        # Control changes: list of (tick, entity_id, player_id)
        self.control_changes = []

        # Derived
        self.max_tick = 0
        self.duration_seconds = 0.0

    def tick_to_seconds(self, tick):
        """Convert tick number to game time in seconds."""
        return tick * self.tick_interval_ms / 1000.0

    def seconds_to_tick(self, seconds):
        """Convert game time in seconds to nearest tick number."""
        return round(seconds * 1000.0 / self.tick_interval_ms)

    def get_controller_at_tick(self, entity_id, tick):
        """Get the controlling player ID for an entity at a given tick."""
        entity = self.entities.get(entity_id)
        if entity is None:
            return 0
        # Start with registration-time controller
        current = entity.controller_id
        # Apply control changes up to this tick
        for ct, eid, pid in self.control_changes:
            if ct > tick:
                break
            if eid == entity_id:
                current = pid
        return current

    def get_positions_at_time(self, t):
        """
        Get all unit positions at game time t (seconds).

        Returns list of dicts with keys:
            entity_id, team_name, type_name, is_unit, x, y,
            controller_name (or None for AI)
        """
        tick = self.seconds_to_tick(t)

        # Find the closest tick <= requested tick
        best_tick = None
        for tn in self.tick_numbers:
            if tn <= tick:
                best_tick = tn
            else:
                break

        if best_tick is None:
            return []

        positions = self.ticks.get(best_tick, {})
        result = []
        for eid, (x, y) in positions.items():
            entity = self.entities.get(eid)
            if entity is None:
                continue
            # Resolve current controller
            ctrl_id = self.get_controller_at_tick(eid, tick)
            ctrl_name = None
            if ctrl_id > 0:
                pinfo = self.players.get(ctrl_id)
                if pinfo:
                    ctrl_name = pinfo[1]
            result.append({
                "entity_id": eid,
                "team_name": entity.team_name,
                "team_idx": entity.team_idx,
                "type_name": entity.type_name,
                "is_unit": entity.is_unit,
                "x": x,
                "y": y,
                "controller_name": ctrl_name,
            })
        return result

    def get_unit_positions_at_time(self, t):
        """Get only unit (not building) positions at game time t."""
        return [p for p in self.get_positions_at_time(t) if p["is_unit"]]

    def get_destroyed_before(self, t):
        """Get entity IDs destroyed before time t."""
        tick = self.seconds_to_tick(t)
        return {d[1] for d in self.destructions if d[0] <= tick}


def parse_srpl(filepath):
    """
    Parse an .srpl replay file and return an SrplReplay object.

    Args:
        filepath: Path to .srpl file

    Returns:
        SrplReplay object with all data indexed for time-based lookups
    """
    replay = SrplReplay()
    size = os.path.getsize(filepath)
    logger.info(f"Parsing SRPL: {filepath} ({size:,} bytes)")

    with open(filepath, "rb") as f:
        # Header
        magic = f.read(4)
        if magic != b"SRPL":
            raise ValueError(f"Bad magic: {magic!r} (expected b'SRPL')")

        replay.version = struct.unpack("B", f.read(1))[0]
        replay.tick_interval_ms = struct.unpack("<H", f.read(2))[0]
        replay.map_name = _read_string(f)
        replay.game_type = _read_string(f)
        replay.start_timestamp = struct.unpack("<q", f.read(8))[0]

        while True:
            rec = f.read(1)
            if not rec:
                logger.warning("Unexpected end of file (no 0xFF terminator)")
                break

            rec_type = struct.unpack("B", rec)[0]

            if rec_type == 0xFF:  # EndOfReplay
                break

            elif rec_type == 0x01:  # TypeRegister
                type_id = struct.unpack("B", f.read(1))[0]
                type_name = _read_string(f)
                replay.types[type_id] = type_name

            elif rec_type == 0x02:  # EntityRegister
                if replay.version >= 2:
                    eid, team, tid, is_unit, ctrl = struct.unpack("<HBBBB", f.read(6))
                else:
                    eid, team, tid, is_unit = struct.unpack("<HBBB", f.read(5))
                    ctrl = 0
                x, y = struct.unpack("<hh", f.read(4))
                type_name = replay.types.get(tid, f"type#{tid}")
                entity = SrplEntity(eid, team, type_name, bool(is_unit), ctrl, x, y)
                replay.entities[eid] = entity

            elif rec_type == 0x03:  # PlayerRegister (v2+)
                pid, team = struct.unpack("BB", f.read(2))
                pname = _read_string(f)
                replay.players[pid] = (team, pname)

            elif rec_type == 0x04:  # PlayerControl (v2+)
                tick, eid, pid = struct.unpack("<HHB", f.read(5))
                replay.control_changes.append((tick, eid, pid))

            elif rec_type == 0x10:  # TickFrame
                tick, count = struct.unpack("<HH", f.read(4))
                positions = {}
                for _ in range(count):
                    eid, x, y = struct.unpack("<Hhh", f.read(6))
                    positions[eid] = (x, y)
                replay.ticks[tick] = positions
                if tick > replay.max_tick:
                    replay.max_tick = tick

            elif rec_type == 0x20:  # UnitDestroyed
                tick, vid, aid = struct.unpack("<HHH", f.read(6))
                replay.destructions.append((tick, vid, aid, False))

            elif rec_type == 0x30:  # BuildingDestroyed
                tick, bid, aid = struct.unpack("<HHH", f.read(6))
                replay.destructions.append((tick, bid, aid, True))

            else:
                logger.warning(f"Unknown record type 0x{rec_type:02X} at offset {f.tell()-1}")
                break

    # Post-processing: link player names to entities
    for entity in replay.entities.values():
        if entity.controller_id > 0:
            pinfo = replay.players.get(entity.controller_id)
            if pinfo:
                entity.controller_name = pinfo[1]

    # Sort tick numbers and control changes for lookups
    replay.tick_numbers = sorted(replay.ticks.keys())
    replay.control_changes.sort(key=lambda x: x[0])
    replay.duration_seconds = replay.tick_to_seconds(replay.max_tick)

    logger.info(
        f"SRPL parsed: v{replay.version}, map={replay.map_name}, "
        f"ticks={len(replay.ticks)}, entities={len(replay.entities)}, "
        f"players={len(replay.players)}, duration={replay.duration_seconds:.0f}s"
    )
    return replay


class LiveSrplReader:
    """
    Incremental .srpl reader for live games.

    Opens the file while C# is still writing (FileShare.Read),
    reads new records on each refresh() call, handles EOF and
    partial records gracefully.
    """

    def __init__(self, filepath):
        self.filepath = filepath
        self._f = None
        self.replay = SrplReplay()
        self._header_read = False
        self._finished = False  # True after 0xFF EndOfReplay
        self._needs_sort = False

    def open(self):
        """Open the file for incremental reading. Returns True on success."""
        try:
            self._f = open(self.filepath, "rb")
            self._read_header()
            self._header_read = True
            logger.info(f"LiveSrplReader opened: {self.filepath}")
            return True
        except Exception as e:
            logger.error(f"LiveSrplReader open failed: {e}")
            self._f = None
            return False

    def _read_header(self):
        """Read the SRPL header (called once on open)."""
        f = self._f
        magic = f.read(4)
        if magic != b"SRPL":
            raise ValueError(f"Bad magic: {magic!r}")
        self.replay.version = struct.unpack("B", f.read(1))[0]
        self.replay.tick_interval_ms = struct.unpack("<H", f.read(2))[0]
        self.replay.map_name = _read_string(f)
        self.replay.game_type = _read_string(f)
        self.replay.start_timestamp = struct.unpack("<q", f.read(8))[0]

    def refresh(self):
        """
        Read all new records available since the last call.

        Returns the number of new records read.
        Safe to call frequently - returns 0 if no new data.
        """
        if not self._f or self._finished:
            return 0

        f = self._f
        records_read = 0

        while True:
            pos_before = f.tell()

            try:
                rec = f.read(1)
                if not rec:
                    # EOF - no more data yet, rewind to retry next time
                    f.seek(pos_before)
                    break

                rec_type = struct.unpack("B", rec)[0]

                if rec_type == 0xFF:  # EndOfReplay
                    self._finished = True
                    break

                elif rec_type == 0x01:  # TypeRegister
                    data = f.read(1)
                    if len(data) < 1:
                        f.seek(pos_before); break
                    type_id = struct.unpack("B", data)[0]
                    type_name = self._safe_read_string(f, pos_before)
                    if type_name is None:
                        break
                    self.replay.types[type_id] = type_name
                    records_read += 1

                elif rec_type == 0x02:  # EntityRegister
                    if self.replay.version >= 2:
                        data = f.read(6)
                        if len(data) < 6:
                            f.seek(pos_before); break
                        eid, team, tid, is_unit, ctrl = struct.unpack("<HBBBB", data)
                    else:
                        data = f.read(5)
                        if len(data) < 5:
                            f.seek(pos_before); break
                        eid, team, tid, is_unit = struct.unpack("<HBBB", data)
                        ctrl = 0
                    data2 = f.read(4)
                    if len(data2) < 4:
                        f.seek(pos_before); break
                    x, y = struct.unpack("<hh", data2)
                    type_name = self.replay.types.get(tid, f"type#{tid}")
                    entity = SrplEntity(eid, team, type_name, bool(is_unit), ctrl, x, y)
                    if ctrl > 0:
                        pinfo = self.replay.players.get(ctrl)
                        if pinfo:
                            entity.controller_name = pinfo[1]
                    self.replay.entities[eid] = entity
                    records_read += 1

                elif rec_type == 0x03:  # PlayerRegister
                    data = f.read(2)
                    if len(data) < 2:
                        f.seek(pos_before); break
                    pid, team = struct.unpack("BB", data)
                    pname = self._safe_read_string(f, pos_before)
                    if pname is None:
                        break
                    self.replay.players[pid] = (team, pname)
                    records_read += 1

                elif rec_type == 0x04:  # PlayerControl
                    data = f.read(5)
                    if len(data) < 5:
                        f.seek(pos_before); break
                    tick, eid, pid = struct.unpack("<HHB", data)
                    self.replay.control_changes.append((tick, eid, pid))
                    self._needs_sort = True
                    records_read += 1

                elif rec_type == 0x10:  # TickFrame
                    data = f.read(4)
                    if len(data) < 4:
                        f.seek(pos_before); break
                    tick, count = struct.unpack("<HH", data)
                    needed = count * 6
                    payload = f.read(needed)
                    if len(payload) < needed:
                        f.seek(pos_before); break
                    positions = {}
                    for i in range(count):
                        off = i * 6
                        eid, x, y = struct.unpack("<Hhh", payload[off:off+6])
                        positions[eid] = (x, y)
                    self.replay.ticks[tick] = positions
                    if tick > self.replay.max_tick:
                        self.replay.max_tick = tick
                    self._needs_sort = True
                    records_read += 1

                elif rec_type == 0x20:  # UnitDestroyed
                    data = f.read(6)
                    if len(data) < 6:
                        f.seek(pos_before); break
                    tick, vid, aid = struct.unpack("<HHH", data)
                    self.replay.destructions.append((tick, vid, aid, False))
                    records_read += 1

                elif rec_type == 0x30:  # BuildingDestroyed
                    data = f.read(6)
                    if len(data) < 6:
                        f.seek(pos_before); break
                    tick, bid, aid = struct.unpack("<HHH", data)
                    self.replay.destructions.append((tick, bid, aid, True))
                    records_read += 1

                else:
                    # Unknown record type - can't continue safely
                    logger.warning(f"LiveSrplReader: unknown record 0x{rec_type:02X} at offset {pos_before}")
                    f.seek(pos_before)
                    break

            except Exception:
                # Any read error - rewind and try next time
                f.seek(pos_before)
                break

        # Post-processing if we read anything
        if records_read > 0 and self._needs_sort:
            self.replay.tick_numbers = sorted(self.replay.ticks.keys())
            self.replay.control_changes.sort(key=lambda x: x[0])
            self.replay.duration_seconds = self.replay.tick_to_seconds(self.replay.max_tick)
            self._needs_sort = False

        return records_read

    def _safe_read_string(self, f, rewind_pos):
        """Read a length-prefixed string, returning None (and rewinding) if incomplete."""
        len_byte = f.read(1)
        if len(len_byte) < 1:
            f.seek(rewind_pos)
            return None
        length = struct.unpack("B", len_byte)[0]
        data = f.read(length)
        if len(data) < length:
            f.seek(rewind_pos)
            return None
        return data.decode("utf-8", errors="replace")

    def close(self):
        """Close the file."""
        if self._f:
            try:
                self._f.close()
            except Exception:
                pass
            self._f = None

    @property
    def is_finished(self):
        """True if EndOfReplay marker was read."""
        return self._finished


def find_srpl_for_game(srpl_dir, map_name, game_start_unix):
    """
    Find the .srpl file that matches a game by map name and start time.

    Looks for files matching the pattern: YYYYMMDD_HHMMSS_MapName.srpl
    Returns the closest match within 60 seconds of the game start time.

    Args:
        srpl_dir: Directory containing .srpl files
        map_name: Map name to match
        game_start_unix: Unix timestamp of game start

    Returns:
        Path to matching .srpl file, or None
    """
    if not os.path.isdir(srpl_dir):
        return None

    best_path = None
    best_delta = float("inf")

    for fname in os.listdir(srpl_dir):
        if not fname.endswith(".srpl"):
            continue
        if map_name and map_name not in fname:
            continue

        fpath = os.path.join(srpl_dir, fname)
        try:
            with open(fpath, "rb") as f:
                magic = f.read(4)
                if magic != b"SRPL":
                    continue
                f.read(1)  # version
                f.read(2)  # tick_interval_ms
                _read_string(f)  # map_name
                _read_string(f)  # game_type
                ts = struct.unpack("<q", f.read(8))[0]

            delta = abs(ts - game_start_unix)
            if delta < best_delta and delta < 60:
                best_delta = delta
                best_path = fpath
        except Exception:
            continue

    return best_path
