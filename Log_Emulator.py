# -*- coding: utf-8 -*-
"""
Log Emulator for MapReplay Live Service Testing

This tool replays historical clean log files to simulate a live game server.
It writes log lines to a file at configurable speeds, allowing you to test
the MapReplay_Live service in accelerated time.

Features:
- Adjustable playback speed (1x = real-time, 10x = 10x faster, etc.)
- Respects original timestamps for realistic timing
- Can start from any point in the log
- Supports midnight rollover simulation
- Interactive speed control during playback

Usage:
    python Log_Emulator.py <input_log> [options]

Examples:
    # Real-time playback
    python Log_Emulator.py L20251214.log --speed 1

    # 10x speed (1 hour of game = 6 minutes)
    python Log_Emulator.py L20251214.log --speed 10

    # 60x speed (1 hour of game = 1 minute)  
    python Log_Emulator.py L20251214.log --speed 60

    # Start from a specific game
    python Log_Emulator.py L20251214.log --speed 30 --start-line 1000

Author: MapReplay System
Version: 1.0.0
"""

import os
import sys
import re
import time
import json
import struct
import argparse
import threading
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Tuple


# ============================================================
# CONFIGURATION
# ============================================================

class EmulatorConfig:
    """Configuration for the log emulator."""
    
    # Emulator sandbox. Everything the emulator produces lives under here so it
    # never writes into - or clears - the real server's UserData directories.
    # MapReplay_Service switches its watchers to these paths while an emulation
    # session is running (see EmulationMarker below).
    EMU_ROOT = Path(__file__).parent / "Emulator"

    # Default output directory for the emulated game log (L<date>.log).
    DEFAULT_OUTPUT_DIR = EMU_ROOT / "logs"

    # Read-only pool of the game's real .srpl replays. The emulator looks up the
    # recording that matches each replayed game here, but never writes to it.
    DEFAULT_SRPL_SRC_DIR = Path(__file__).parent.parent / "UserData" / "ReplayLogs"

    # Directory the emulator streams its matching .srpl copy into (unit
    # positions), mirroring the layout of UserData/ReplayLogs.
    DEFAULT_SRPL_DIR = EMU_ROOT / "ReplayLogs"

    # Marker file that tells the live service an emulation session is active.
    # Its mtime is refreshed periodically as a heartbeat.
    EMU_MARKER = EMU_ROOT / "emulation.active"

    # How often the marker's heartbeat is refreshed, in seconds. The service
    # uses a timeout several times this value before declaring it stale.
    HEARTBEAT_INTERVAL = 5.0

    # How close (seconds) an .srpl file's start time must be to a game's
    # Round_Start to be considered the match for that game.
    SRPL_MATCH_TOLERANCE = 180

    # Prefix for the emulator's streamed copy so it is easy to identify/clean up
    # and never clobbers a real replay.
    SRPL_EMU_PREFIX = "EMU_"

    # Default playback speed multiplier
    DEFAULT_SPEED = 10.0

    # Minimum delay between lines (even at max speed)
    MIN_LINE_DELAY = 0.001  # 1ms minimum

    # Batch size for writing lines with same timestamp
    BATCH_SAME_TIMESTAMP = True


# ============================================================
# EMULATION MARKER
# ============================================================

class EmulationMarker:
    """
    Announces a running emulation session to MapReplay_Service.

    While the marker exists the service reads the emulated log/SRPL directories
    instead of the real UserData ones. The file's mtime doubles as a heartbeat:
    a background thread touches it every HEARTBEAT_INTERVAL seconds and the
    service ignores a marker that has gone stale. That way an emulator killed
    the hard way - console window closed, machine reset, no clean shutdown -
    releases the service on its own instead of pinning it to a dead session.

    Detecting the session by marker rather than by scanning for a running
    Run_Emulator.bat also keeps it working when Log_Emulator.py is started
    directly (from a shell, an IDE, or another script), which is how it is
    usually run during development.
    """

    def __init__(self, marker_path: Path, log_dir: Path, srpl_dir: Path,
                 source_log: Path, speed: float,
                 interval: float = EmulatorConfig.HEARTBEAT_INTERVAL):
        self.marker_path = Path(marker_path)
        self.log_dir = Path(log_dir)
        self.srpl_dir = Path(srpl_dir)
        self.source_log = Path(source_log)
        self.speed = speed
        self.interval = interval
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _payload(self) -> str:
        return json.dumps({
            "pid": os.getpid(),
            "started": datetime.now().isoformat(timespec="seconds"),
            "heartbeat": datetime.now().isoformat(timespec="seconds"),
            "log_dir": str(self.log_dir),
            "srpl_dir": str(self.srpl_dir),
            "source_log": str(self.source_log),
            "speed": self.speed,
        }, indent=2)

    def _write(self):
        tmp = self.marker_path.with_suffix(self.marker_path.suffix + ".tmp")
        tmp.write_text(self._payload(), encoding="utf-8")
        # Atomic replace so the service never reads a half-written marker.
        os.replace(tmp, self.marker_path)

    def _run(self):
        while not self._stop.wait(self.interval):
            try:
                self._write()
            except Exception as e:
                print(f"[EMU MARKER] Heartbeat failed: {e}")

    def start(self):
        self.marker_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._write()
        except Exception as e:
            print(f"[EMU MARKER] Could not create marker {self.marker_path}: {e}")
            print("[EMU MARKER] The live service will keep watching the real server log.")
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        print(f"Emulation marker: {self.marker_path}")

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        try:
            self.marker_path.unlink()
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"[EMU MARKER] Could not remove marker: {e}")


# ============================================================
# TIME PARSER
# ============================================================

class TimeParser:
    """Parses timestamps from clean log format."""
    
    # Pattern: [HH:MM:SS.mmm] (standard format)
    TIMESTAMP_PATTERN = re.compile(r'\[(\d{2}):(\d{2}):(\d{2})\.(\d{3})\]')
    
    # Pattern: L MM/DD/YYYY - HH:MM:SS: (cleanlog format)
    CLEANLOG_PATTERN = re.compile(r'L \d{2}/\d{2}/\d{4} - (\d{2}):(\d{2}):(\d{2}):')
    
    # Pattern for date in log: L MM/DD/YYYY - HH:MM:SS:
    DATE_PATTERN = re.compile(r'L (\d{2})/(\d{2})/(\d{4}) - (\d{2}):(\d{2}):(\d{2}):')
    
    @classmethod
    def parse_timestamp(cls, line: str) -> Optional[float]:
        """Extract timestamp from log line as seconds since midnight."""
        # Try standard format first [HH:MM:SS.mmm]
        match = cls.TIMESTAMP_PATTERN.search(line)
        if match:
            h, m, s, ms = map(int, match.groups())
            return h * 3600 + m * 60 + s + ms / 1000.0
        
        # Try cleanlog format: L MM/DD/YYYY - HH:MM:SS:
        match = cls.CLEANLOG_PATTERN.search(line)
        if match:
            h, m, s = map(int, match.groups())
            return h * 3600 + m * 60 + s
        
        return None
    
    @classmethod
    def parse_date(cls, line: str) -> Optional[datetime]:
        """Extract date from log line."""
        match = cls.DATE_PATTERN.search(line)
        if not match:
            return None
        
        month, day, year, h, m, s = map(int, match.groups())
        return datetime(year, month, day, h, m, s)
    
    @classmethod
    def format_timestamp(cls, seconds: float) -> str:
        """Format seconds since midnight as HH:MM:SS.mmm"""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


# ============================================================
# SRPL STREAMER
# ============================================================
#
# The live MapReplay service overlays unit movement (and AI-vs-AI kill /
# harvester / detailed-unit stats) from the game's native .srpl replay, which
# it reads from UserData/ReplayLogs. It only accepts an .srpl whose mtime is
# within ~120s and whose data grows over time (frame generation is driven by
# new SRPL ticks). Historical .srpl files are always "too old", so replaying a
# log alone produces videos with NO unit movement.
#
# The streamer fixes this: for each game the emulator replays, it locates the
# matching .srpl, rewrites its header start-timestamp to "now" (so the service
# computes a ~0 time offset), and dribbles its records into
# ReplayLogs/EMU_<name>.srpl paced by the SAME speed multiplier as the log — so
# SRPL tick T becomes visible exactly when the emulated log reaches game-time T.

# SRPL filename pattern: YYYYMMDD_HHMMSS_MapName.srpl
SRPL_NAME_RE = re.compile(r'^(\d{8})_(\d{6})_(.+)\.srpl$', re.IGNORECASE)


def _read_srpl_string(data: bytes, off: int) -> Tuple[str, int]:
    """Read a uint8-length-prefixed UTF-8 string from a bytes buffer."""
    n = data[off]
    off += 1
    s = data[off:off + n].decode("utf-8", errors="replace")
    return s, off + n


def load_srpl_records(path: Path):
    """
    Read an .srpl file and split it into individually-releasable records, each
    tagged with the game-time (seconds) at which it should become visible.

    Registration/setup records (before the first TickFrame) and header release
    at t=0. Each TickFrame and later interleaved record releases at the game
    time of the most-recently-seen tick, mirroring how the game wrote it live.

    Returns (header_bytes, records) where header_bytes is the full header and
    records is a list of (release_seconds, raw_record_bytes). Raises ValueError
    on a bad file.
    """
    with open(path, "rb") as f:
        data = f.read()

    if data[:4] != b"SRPL":
        raise ValueError("Bad SRPL magic")

    off = 4
    version = data[off]; off += 1
    tick_interval_ms = struct.unpack_from("<H", data, off)[0]; off += 2
    _map, off = _read_srpl_string(data, off)   # map_name
    _gt, off = _read_srpl_string(data, off)    # game_type
    off += 8                                    # start_timestamp (int64)
    header = data[:off]

    def t2s(tick: int) -> float:
        return tick * tick_interval_ms / 1000.0

    records: List[Tuple[float, bytes]] = []
    cur_tick = 0
    n = len(data)

    while off < n:
        rstart = off
        rt = data[off]; off += 1

        if rt == 0xFF:                                    # EndOfReplay
            records.append((t2s(cur_tick), data[rstart:off]))
            break
        elif rt == 0x01:                                  # TypeRegister
            off += 1                                      # type_id
            slen = data[off]; off += 1 + slen
        elif rt == 0x02:                                  # EntityRegister
            off += 6 if version >= 2 else 5               # eid,team,tid,is_unit[,ctrl]
            off += 4                                       # reg_x, reg_y
            if version >= 3:
                off += 2                                   # z
        elif rt == 0x03:                                  # PlayerRegister
            off += 2                                       # pid, team
            slen = data[off]; off += 1 + slen
        elif rt == 0x04:                                  # PlayerControl
            off += 5
        elif rt == 0x10:                                  # TickFrame
            tick, count = struct.unpack_from("<HH", data, off); off += 4
            cur_tick = tick
            off += count * (8 if version >= 3 else 6)
        elif rt in (0x20, 0x30):                          # Unit/Building destroyed
            off += 6
        else:
            # Unknown record: stop cleanly, keep what we have.
            break

        records.append((t2s(cur_tick), data[rstart:off]))

    return header, records


def find_matching_srpl(srpl_dir: Path, map_name: str, game_dt: datetime,
                       tolerance_s: int) -> Optional[Path]:
    """
    Find the .srpl whose filename timestamp is closest to a game's Round_Start.

    Matches by map name and a start time within `tolerance_s`. Ignores the
    emulator's own EMU_ copies. Returns the path or None.
    """
    if not srpl_dir.is_dir() or not map_name:
        return None

    best_path = None
    best_delta = float("inf")
    for fname in os.listdir(srpl_dir):
        if fname.startswith(EmulatorConfig.SRPL_EMU_PREFIX):
            continue
        m = SRPL_NAME_RE.match(fname)
        if not m:
            continue
        if m.group(3).lower() != map_name.lower():
            continue
        try:
            f_dt = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
        except ValueError:
            continue
        delta = abs((f_dt - game_dt).total_seconds())
        if delta < best_delta:
            best_delta = delta
            best_path = srpl_dir / fname

    if best_path is not None and best_delta <= tolerance_s:
        return best_path
    return None


class SrplStreamer:
    """
    Streams a matching .srpl into the ReplayLogs dir, paced to a shared speed.

    One streamer instance is reused across games; start() switches to a new
    source .srpl (stopping any previous stream first). Pacing mirrors the log
    emulator's own loop so log and SRPL stay in lock-step even when the speed
    is changed live.
    """

    def __init__(self, srpl_dir: Path, get_speed):
        self.srpl_dir = Path(srpl_dir)
        self.get_speed = get_speed          # callable -> current speed multiplier
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._drain = threading.Event()   # write the remainder without pacing
        self._dst_path: Optional[Path] = None

    def start(self, src_path: Path, map_name: str):
        """Begin streaming src_path. Stops any previous stream first."""
        self.stop()
        try:
            header, records = load_srpl_records(src_path)
        except Exception as e:
            print(f"  [SRPL] Failed to read {src_path.name}: {e}")
            return False

        # Rewrite the 8-byte header start_timestamp to "now" so the service
        # computes a near-zero time offset (game._start_unix is time.time()).
        new_header = header[:-8] + struct.pack("<q", int(time.time()))

        self._dst_path = self.srpl_dir / (EmulatorConfig.SRPL_EMU_PREFIX + src_path.name)
        try:
            self.srpl_dir.mkdir(parents=True, exist_ok=True)
            # Write header synchronously so the file exists the instant the
            # service processes the same Round_Start line.
            with open(self._dst_path, "wb") as out:
                out.write(new_header)
                out.flush()
        except Exception as e:
            print(f"  [SRPL] Failed to create {self._dst_path}: {e}")
            self._dst_path = None
            return False

        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, args=(records,), daemon=True
        )
        self._thread.start()
        dur = records[-1][0] if records else 0.0
        print(f"  [SRPL] Streaming {src_path.name} -> {self._dst_path.name} "
              f"({len(records)} records, {dur/60:.1f} min)")
        return True

    def _run(self, records: List[Tuple[float, bytes]]):
        """Append records to the dst file, paced by release time / speed."""
        dst = self._dst_path
        last_rel = 0.0
        last_real = time.time()
        try:
            out = open(dst, "ab")
        except Exception as e:
            print(f"  [SRPL] Cannot open {dst} for append: {e}")
            return
        try:
            for rel, raw in records:
                if self._stop.is_set():
                    break
                delta = rel - last_rel
                # _drain skips pacing so the tail is written as fast as the disk
                # allows; the service only cares that the records arrive.
                if delta > 0 and not self._drain.is_set():
                    speed = max(self.get_speed(), 0.001)
                    target = last_real + delta / speed
                    while not self._stop.is_set() and not self._drain.is_set():
                        remaining = target - time.time()
                        if remaining <= 0:
                            break
                        time.sleep(min(remaining, 0.2))
                last_rel = rel
                last_real = time.time()
                out.write(raw)
                out.flush()
        finally:
            try:
                out.close()
            except Exception:
                pass

    def finish(self, timeout: float = 30.0):
        """
        Let the current stream write out whatever is left, unpaced.

        Called on Round_Win. The streamer paces itself off the same speed
        multiplier as the log, but it also has to write and flush every record,
        so at high speeds it runs slightly behind the log emitter - at 50x it
        was ~750 ticks (2.5 min of game) short when the round ended. Cutting it
        off there truncates the .srpl, and because the service drives frame
        generation off SRPL ticks, the replay simply freezes at that point.
        Draining first costs a moment and keeps the recording complete.
        """
        if self._thread and self._thread.is_alive():
            self._drain.set()
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                print("  [SRPL] Stream did not drain in time; stopping it")
        self._thread = None
        self._drain.clear()

    def stop(self):
        """
        Stop the current stream. The written file is deliberately KEPT.

        It used to be deleted here, which broke every game after the first in a
        multi-game run: the emulator races ahead at the configured speed while
        the service renders far slower, so by the time the service reached game
        2's Round_Start that game's .srpl had already been unlinked when game 3
        started. Only game 1 survived, and only by accident - Windows refuses to
        unlink a file the service still holds open.

        Leftovers are cleaned by sweep_stale() at the start of the next run, so
        nothing accumulates across sessions.
        """
        if self._thread and self._thread.is_alive():
            self._stop.set()
            self._thread.join(timeout=3)
        self._thread = None
        self._dst_path = None

    def sweep_stale(self):
        """Remove leftover EMU_ files from previous runs (best effort)."""
        if not self.srpl_dir.is_dir():
            return
        for fname in os.listdir(self.srpl_dir):
            if fname.startswith(EmulatorConfig.SRPL_EMU_PREFIX):
                try:
                    (self.srpl_dir / fname).unlink()
                except Exception:
                    pass


# ============================================================
# LOG EMULATOR
# ============================================================

class LogEmulator:
    """Emulates a live game server by replaying historical logs."""
    
    def __init__(self, input_path: Path, output_dir: Path, speed: float = 10.0,
                 srpl_dir: Optional[Path] = None, enable_srpl: bool = True,
                 srpl_out_dir: Optional[Path] = None):
        self.input_path = input_path
        self.output_dir = output_dir
        self.speed = speed

        self.lines: List[str] = []
        self.timestamps: List[Optional[float]] = []

        self.running = False
        self.paused = False
        self.current_line = 0
        self.lines_written = 0

        # Statistics
        self.start_time: Optional[float] = None
        self.log_start_time: Optional[float] = None

        # Output file
        self.output_file = None
        self.output_path: Optional[Path] = None

        # Speed control thread
        self.control_thread: Optional[threading.Thread] = None

        # Session marker for the live service (created in run())
        self.marker: Optional[EmulationMarker] = None

        # SRPL streaming (feeds unit positions to the live service).
        # Source and destination are deliberately different directories: the
        # source is the server's real ReplayLogs (read-only), the destination is
        # the emulator sandbox. Sharing one directory made the streamer sweep
        # and write EMU_ files into the server's own replay folder.
        self.enable_srpl = enable_srpl
        self.srpl_dir = Path(srpl_dir) if srpl_dir else EmulatorConfig.DEFAULT_SRPL_SRC_DIR
        self.srpl_out_dir = Path(srpl_out_dir) if srpl_out_dir else EmulatorConfig.DEFAULT_SRPL_DIR
        self.srpl_streamer: Optional[SrplStreamer] = None
        self._srpl_current_map = "Unknown"   # last "Loading map" seen while emitting
        self._srpl_re_loading = re.compile(r'Loading map "([^"]+)"')
        self._srpl_re_round_start = re.compile(r'World triggered "Round_Start"')
        self._srpl_re_round_win = re.compile(r'World triggered "Round_Win"')
    
    def load_log(self, start_line: int = 0) -> bool:
        """Load the input log file."""
        print(f"Loading log file: {self.input_path}")
        
        try:
            with open(self.input_path, 'r', encoding='utf-8', errors='ignore') as f:
                all_lines = f.readlines()
        except Exception as e:
            print(f"Error loading log file: {e}")
            return False
        
        # Seed the current map from the lines we are about to skip.
        #
        # The SRPL streamer normally learns the map from 'Loading map "X"' lines
        # as it emits them, but the game selector starts a slice at
        # round_start_line - 50 whenever the map load was more than 100 lines
        # back. Those slices contain no 'Loading map' line, so the map stayed
        # "Unknown" and the .srpl lookup - which filters on map name - silently
        # found nothing. Reading the history first makes the lookup work no
        # matter where the slice begins.
        # Line numbers from find_games_in_log()/--select-game are 1-based, so the
        # slice has to start one earlier. Using them directly as a 0-based index
        # dropped the very first line of the slice - which is the 'Loading map'
        # line the selector deliberately started at, leaving the live service
        # with Map: Unknown and no frames at all.
        skip = max(0, start_line - 1)

        if skip > 0:
            for line in reversed(all_lines[:skip]):
                m = self._srpl_re_loading.search(line)
                if m:
                    self._srpl_current_map = m.group(1)
                    print(f"Map from log history: {self._srpl_current_map}")
                    break

        # Skip to start line
        all_lines = all_lines[skip:]
        
        # Parse timestamps for all lines
        self.lines = []
        self.timestamps = []
        
        last_time = None
        time_offset = 0
        
        for line in all_lines:
            line = line.rstrip('\r\n')
            if not line:
                continue
            
            self.lines.append(line)
            
            # Parse timestamp
            ts = TimeParser.parse_timestamp(line)
            
            # Handle midnight rollover (compare RAW timestamps, not adjusted)
            if ts is not None and last_time is not None:
                if ts < last_time - 3600:  # More than 1 hour backwards
                    time_offset += 86400
                    print(f"  Detected midnight rollover at line {len(self.lines)}")
            
            if ts is not None:
                last_time = ts  # Track RAW time for rollover detection
                ts += time_offset  # Then adjust for storage
            
            self.timestamps.append(ts)
        
        print(f"Loaded {len(self.lines)} lines")
        
        # Find time range
        valid_times = [t for t in self.timestamps if t is not None]
        if valid_times:
            duration = valid_times[-1] - valid_times[0]
            print(f"Log duration: {duration:.1f}s ({duration/60:.1f} min)")
            print(f"At {self.speed}x speed: {duration/self.speed:.1f}s ({duration/self.speed/60:.1f} min)")
        
        return True
    
    def get_output_filename(self) -> str:
        """Generate output filename based on current date."""
        return f"L{datetime.now().strftime('%Y%m%d')}.log"
    
    def open_output_file(self) -> bool:
        """Open the output log file."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        filename = self.get_output_filename()
        self.output_path = self.output_dir / filename
        
        try:
            # Open in append mode
            self.output_file = open(self.output_path, 'a', encoding='utf-8')
            print(f"Writing to: {self.output_path}")
            return True
        except Exception as e:
            print(f"Error opening output file: {e}")
            return False
    
    def close_output_file(self):
        """Close the output file."""
        if self.output_file:
            try:
                self.output_file.close()
            except:
                pass
            self.output_file = None
    
    def write_line(self, line: str):
        """Write a line to the output file."""
        if self.output_file:
            self.output_file.write(line + '\n')
            self.output_file.flush()  # Ensure immediate write
            self.lines_written += 1

    def _srpl_on_line(self, line: str):
        """
        Drive the SRPL streamer off the log lines as they are emitted so the
        streamed .srpl stays in lock-step with the log.

        - "Loading map" updates the current map.
        - "Round_Start" starts streaming the matching .srpl (anchored to now).
        - "Round_Win" stops the current stream.
        """
        if not self.srpl_streamer:
            return

        m = self._srpl_re_loading.search(line)
        if m:
            self._srpl_current_map = m.group(1)
            return

        if self._srpl_re_round_start.search(line):
            game_dt = TimeParser.parse_date(line)  # full date+time from the line
            if game_dt is None:
                print("  [SRPL] Round_Start without a parseable date; skipping SRPL")
                return
            src = find_matching_srpl(
                self.srpl_dir, self._srpl_current_map, game_dt,
                EmulatorConfig.SRPL_MATCH_TOLERANCE,
            )
            if src is None:
                print(f"  [SRPL] No matching .srpl for {self._srpl_current_map} "
                      f"@ {game_dt:%H:%M:%S} (within "
                      f"{EmulatorConfig.SRPL_MATCH_TOLERANCE}s)")
            else:
                self.srpl_streamer.start(src, self._srpl_current_map)
            return

        if self._srpl_re_round_win.search(line):
            # Drain rather than cut: see SrplStreamer.finish()
            self.srpl_streamer.finish()

    def start_control_thread(self):
        """Start the keyboard control thread."""
        def control_loop():
            print("\n--- Controls ---")
            print("  +/=  : Increase speed")
            print("  -    : Decrease speed")
            print("  p    : Pause/Resume")
            print("  s    : Show status")
            print("  q    : Quit")
            print("----------------\n")
            
            while self.running:
                try:
                    # Non-blocking input on Windows
                    if sys.platform == 'win32':
                        import msvcrt
                        if msvcrt.kbhit():
                            key = msvcrt.getch().decode('utf-8', errors='ignore').lower()
                            self.handle_key(key)
                    else:
                        # Unix-like systems
                        import select
                        if select.select([sys.stdin], [], [], 0.1)[0]:
                            key = sys.stdin.read(1).lower()
                            self.handle_key(key)
                    
                    time.sleep(0.1)
                except:
                    time.sleep(0.1)
        
        self.control_thread = threading.Thread(target=control_loop, daemon=True)
        self.control_thread.start()
    
    def handle_key(self, key: str):
        """Handle keyboard input."""
        if key in ['+', '=']:
            self.speed = min(self.speed * 1.5, 1000)
            print(f"\n>>> Speed: {self.speed:.1f}x")
        elif key == '-':
            self.speed = max(self.speed / 1.5, 0.1)
            print(f"\n>>> Speed: {self.speed:.1f}x")
        elif key == 'p':
            self.paused = not self.paused
            print(f"\n>>> {'PAUSED' if self.paused else 'RESUMED'}")
        elif key == 's':
            self.print_status()
        elif key == 'q':
            print("\n>>> Stopping...")
            self.running = False
    
    def print_status(self):
        """Print current status."""
        if self.log_start_time is not None and self.current_line < len(self.timestamps):
            current_ts = self.timestamps[self.current_line]
            if current_ts:
                log_elapsed = current_ts - self.log_start_time
                real_elapsed = time.time() - self.start_time if self.start_time else 0
                
                print(f"\n--- Status ---")
                print(f"  Line: {self.current_line}/{len(self.lines)} ({100*self.current_line/len(self.lines):.1f}%)")
                print(f"  Log time: {TimeParser.format_timestamp(current_ts)} ({log_elapsed:.0f}s)")
                print(f"  Real time: {real_elapsed:.1f}s")
                print(f"  Speed: {self.speed:.1f}x (effective: {log_elapsed/max(real_elapsed,0.1):.1f}x)")
                print(f"  Lines written: {self.lines_written}")
                print(f"--------------\n")
    
    def run(self) -> bool:
        """Run the emulator."""
        if not self.lines:
            print("No lines loaded!")
            return False
        
        if not self.open_output_file():
            return False
        
        self.running = True
        self.start_time = time.time()
        self.current_line = 0
        self.lines_written = 0
        
        # Find first valid timestamp
        self.log_start_time = None
        for ts in self.timestamps:
            if ts is not None:
                self.log_start_time = ts
                break
        
        # Start control thread
        self.start_control_thread()

        # Announce the session so the live service switches to the emulator dirs
        self.marker = EmulationMarker(
            EmulatorConfig.EMU_MARKER,
            self.output_dir,
            self.srpl_dir,
            self.input_path,
            self.speed,
        )
        self.marker.start()

        # Prepare SRPL streaming (feeds unit positions to the live service)
        if self.enable_srpl:
            self.srpl_streamer = SrplStreamer(self.srpl_out_dir, lambda: self.speed)
            self.srpl_streamer.sweep_stale()
            print(f"SRPL source: {self.srpl_dir}")
            print(f"SRPL stream out: {self.srpl_out_dir}")
        else:
            print("SRPL streaming disabled (--no-srpl)")

        print(f"\nStarting playback at {self.speed}x speed...")
        print("Press 's' for status, 'q' to quit\n")
        
        last_log_time = self.log_start_time
        last_real_time = self.start_time
        
        try:
            while self.running and self.current_line < len(self.lines):
                # Handle pause
                while self.paused and self.running:
                    time.sleep(0.1)
                
                if not self.running:
                    break
                
                line = self.lines[self.current_line]
                ts = self.timestamps[self.current_line]
                
                # Calculate delay based on timestamp difference
                if ts is not None and last_log_time is not None:
                    log_delta = ts - last_log_time
                    
                    if log_delta > 0:
                        # Calculate required real-time delay
                        real_delay = log_delta / self.speed
                        
                        # Apply delay (but respect minimum)
                        if real_delay > EmulatorConfig.MIN_LINE_DELAY:
                            # Calculate how long we should have waited
                            target_real_time = last_real_time + real_delay
                            current_real_time = time.time()
                            
                            sleep_time = target_real_time - current_real_time
                            if sleep_time > 0:
                                time.sleep(sleep_time)
                    
                    last_log_time = ts
                    last_real_time = time.time()
                
                # Write the line
                self.write_line(line)
                # Drive SRPL streaming off the same line stream
                if self.srpl_streamer:
                    self._srpl_on_line(line)
                self.current_line += 1
                
                # Progress indicator every 1000 lines
                if self.current_line % 1000 == 0:
                    pct = 100 * self.current_line / len(self.lines)
                    print(f"  Progress: {self.current_line}/{len(self.lines)} ({pct:.1f}%)")
            
            print(f"\nPlayback complete!")
            print(f"  Lines written: {self.lines_written}")
            print(f"  Real time elapsed: {time.time() - self.start_time:.1f}s")
            
        except KeyboardInterrupt:
            print("\n\nPlayback interrupted by user")
        
        finally:
            self.running = False
            self.close_output_file()
            if self.srpl_streamer:
                self.srpl_streamer.stop()
            if self.marker:
                self.marker.stop()

        return True


# ============================================================
# GAME SELECTOR
# ============================================================

def find_games_in_log(log_path: Path) -> List[Tuple[int, str, str, float, int]]:
    """
    Find all games in a log file.
    
    Returns:
        List of (start_line, map_name, gametype, duration_seconds, round_start_line)
        
        start_line = Line to start emulation from (Loading map or a bit before Round_Start)
        round_start_line = Actual Round_Start line (for reference)
    """
    games = []
    current_game = None
    current_map = "Unknown"
    last_loading_map_line = None
    
    re_round_start = re.compile(r'World triggered "Round_Start".*\(gametype "([^"]+)"\)')
    re_loading_map = re.compile(r'Loading map "([^"]+)"')
    re_round_win = re.compile(r'World triggered "Round_Win"')
    
    # For midnight rollover handling
    last_raw_time = None
    time_offset = 0
    
    # Also track lines before Round_Start for cases without Loading map
    LINES_BEFORE_ROUND_START = 50  # Include this many lines before Round_Start if no Loading map
    
    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line_num, line in enumerate(f, 1):
            # Parse timestamp with midnight rollover handling
            raw_ts = TimeParser.parse_timestamp(line)
            ts = None
            if raw_ts is not None:
                if last_raw_time is not None and raw_ts < last_raw_time - 3600:
                    time_offset += 86400  # Add 24 hours
                last_raw_time = raw_ts
                ts = raw_ts + time_offset
            
            # Track map changes
            m_map = re_loading_map.search(line)
            if m_map:
                current_map = m_map.group(1)
                last_loading_map_line = line_num
            
            # Game start
            m_start = re_round_start.search(line)
            if m_start:
                if current_game:
                    # Previous game ended by new start
                    if ts and current_game['start_ts']:
                        duration = ts - current_game['start_ts']
                        games.append((
                            current_game['emulate_from_line'],
                            current_game['map'],
                            current_game['gametype'],
                            duration,
                            current_game['round_start_line']
                        ))
                
                # Determine where to start emulation from
                if last_loading_map_line and last_loading_map_line > (line_num - 100):
                    # Loading map was recent - start from there
                    emulate_from = last_loading_map_line
                else:
                    # No recent Loading map - start some lines before Round_Start
                    emulate_from = max(1, line_num - LINES_BEFORE_ROUND_START)
                
                current_game = {
                    'emulate_from_line': emulate_from,
                    'round_start_line': line_num,
                    'map': current_map,
                    'gametype': m_start.group(1),
                    'start_ts': ts,
                }
                
                # Reset for next game
                last_loading_map_line = None
            
            # Game end
            if re_round_win.search(line):
                if current_game:
                    if ts and current_game['start_ts']:
                        duration = ts - current_game['start_ts']
                        games.append((
                            current_game['emulate_from_line'],
                            current_game['map'],
                            current_game['gametype'],
                            duration,
                            current_game['round_start_line']
                        ))
                    current_game = None
    
    # Handle last game if still running
    if current_game and current_game['start_ts']:
        # Use last timestamp as end
        if ts and current_game['start_ts']:
            duration = ts - current_game['start_ts']
            games.append((
                current_game['emulate_from_line'],
                current_game['map'],
                current_game['gametype'],
                duration,
                current_game['round_start_line']
            ))
    
    return games


def select_game_interactive(log_path: Path) -> Optional[int]:
    """Let user select a game to start from."""
    games = find_games_in_log(log_path)
    
    if not games:
        print("No games found in log file.")
        return 0
    
    print(f"\nFound {len(games)} games in log:\n")
    print(f"{'#':<4} {'Start':<8} {'Map':<20} {'Type':<8} {'Duration':<10} {'Note':<15}")
    print("-" * 75)
    
    for i, (start_line, map_name, gametype, duration, round_start_line) in enumerate(games):
        dur_str = f"{duration/60:.1f} min"
        # Shorten gametype
        gt_short = gametype.replace("HUMANS_VS_HUMANS_VS_ALIENS", "HvHvA")
        gt_short = gt_short.replace("HUMANS_VS_ALIENS", "HvA")
        gt_short = gt_short.replace("HUMANS2_VS_ALIENS", "H2vA")
        gt_short = gt_short.replace("HUMANS_VS_HUMANS", "HvH")
        
        # Note about start line vs round start
        if start_line < round_start_line:
            note = f"(+map info)"
        else:
            note = ""
        
        print(f"{i+1:<4} {start_line:<8} {map_name:<20} {gt_short:<8} {dur_str:<10} {note:<15}")
    
    print()
    print("Note: 'Start' shows where emulation begins (includes Loading map event if available)")
    print()
    
    while True:
        try:
            choice = input("Select game number (0 for start of file, Enter for last game): ").strip()
            
            if choice == "":
                return games[-1][0] - 1 if games else 0  # start_line is index 0
            
            choice = int(choice)
            
            if choice == 0:
                return 0
            elif 1 <= choice <= len(games):
                return games[choice - 1][0] - 1  # start_line is index 0
            else:
                print("Invalid choice.")
        except ValueError:
            print("Please enter a number.")
        except KeyboardInterrupt:
            return None


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Log Emulator - Replay historical logs for testing MapReplay_Live",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s game.log                    # 10x speed (default)
  %(prog)s game.log --speed 1          # Real-time playback
  %(prog)s game.log --speed 60         # 60x speed (1 hour = 1 minute)
  %(prog)s game.log --select-game      # Interactive game selection
  %(prog)s game.log --start-line 5000  # Start from line 5000

During playback:
  +/=  : Increase speed
  -    : Decrease speed  
  p    : Pause/Resume
  s    : Show status
  q    : Quit
"""
    )
    
    parser.add_argument(
        "input_log",
        type=Path,
        help="Path to the historical log file to replay"
    )
    
    parser.add_argument(
        "--output-dir", "-o",
        type=Path,
        default=None,
        help="Output directory for emulated log (default: ../UserData/logs/)"
    )
    
    parser.add_argument(
        "--speed", "-s",
        type=float,
        default=EmulatorConfig.DEFAULT_SPEED,
        help=f"Playback speed multiplier (default: {EmulatorConfig.DEFAULT_SPEED})"
    )
    
    parser.add_argument(
        "--start-line", "-l",
        type=int,
        default=0,
        help="Line number to start from (default: 0)"
    )
    
    parser.add_argument(
        "--select-game", "-g",
        action="store_true",
        help="Interactively select which game to start from"
    )
    
    parser.add_argument(
        "--clear-output", "-c",
        action="store_true",
        help="Clear existing output log file before starting"
    )

    parser.add_argument(
        "--no-srpl",
        action="store_true",
        help="Do NOT stream a matching .srpl (replays will lack unit movement)"
    )

    parser.add_argument(
        "--srpl-dir",
        type=Path,
        default=None,
        help="Directory holding .srpl replays (default: ../UserData/ReplayLogs/)"
    )

    args = parser.parse_args()
    
    # Validate input file
    if not args.input_log.exists():
        print(f"Error: Input file not found: {args.input_log}")
        sys.exit(1)
    
    # Set output directory
    output_dir = args.output_dir
    if output_dir is None:
        output_dir = EmulatorConfig.DEFAULT_OUTPUT_DIR
    
    print("=" * 60)
    print("  Log Emulator for MapReplay Live Testing")
    print("=" * 60)
    # Source pool of real recordings to look matches up in - NOT the sandbox the
    # emulator streams into (EmulatorConfig.DEFAULT_SRPL_DIR).
    srpl_dir = args.srpl_dir if args.srpl_dir else EmulatorConfig.DEFAULT_SRPL_SRC_DIR
    srpl_out_dir = EmulatorConfig.DEFAULT_SRPL_DIR

    print(f"Input:  {args.input_log}")
    print(f"Output: {output_dir}")
    print(f"Speed:  {args.speed}x")
    print(f"SRPL:   {'disabled' if args.no_srpl else f'{srpl_dir} -> {srpl_out_dir}'}")
    print(f"Marker: {EmulatorConfig.EMU_MARKER}")
    print()
    
    # Game selection
    start_line = args.start_line
    if args.select_game:
        selected = select_game_interactive(args.input_log)
        if selected is None:
            print("Cancelled.")
            sys.exit(0)
        start_line = selected
    
    if start_line > 0:
        print(f"Starting from line: {start_line}")
    
    # Clear output if requested.
    #
    # Truncate rather than unlink: a MapReplay service that is already following
    # this file holds an open handle on it, and Windows refuses to delete an open
    # file. Truncating works regardless, and the service's watcher already
    # detects a shrunken file and rewinds to the start.
    if args.clear_output:
        output_file = output_dir / f"L{datetime.now().strftime('%Y%m%d')}.log"
        if output_file.exists():
            try:
                with open(output_file, "w", encoding="utf-8"):
                    pass
                print(f"Cleared: {output_file}")
            except Exception as e:
                print(f"Could not clear {output_file}: {e}")
                sys.exit(1)
    
    # Create and run emulator
    emulator = LogEmulator(
        input_path=args.input_log,
        output_dir=output_dir,
        speed=args.speed,
        srpl_dir=srpl_dir,
        srpl_out_dir=srpl_out_dir,
        enable_srpl=not args.no_srpl,
    )
    
    if not emulator.load_log(start_line):
        sys.exit(1)
    
    print()
    input("Press Enter to start playback...")
    print()
    
    success = emulator.run()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
