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
    
    # Default output directory (same as MapReplay_Live expects)
    # This should point to: SilicaDedicatedServer/UserData/logs/
    DEFAULT_OUTPUT_DIR = Path(__file__).parent.parent / "UserData" / "logs"
    
    # Default playback speed multiplier
    DEFAULT_SPEED = 10.0
    
    # Minimum delay between lines (even at max speed)
    MIN_LINE_DELAY = 0.001  # 1ms minimum
    
    # Batch size for writing lines with same timestamp
    BATCH_SAME_TIMESTAMP = True


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
# LOG EMULATOR
# ============================================================

class LogEmulator:
    """Emulates a live game server by replaying historical logs."""
    
    def __init__(self, input_path: Path, output_dir: Path, speed: float = 10.0):
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
    
    def load_log(self, start_line: int = 0) -> bool:
        """Load the input log file."""
        print(f"Loading log file: {self.input_path}")
        
        try:
            with open(self.input_path, 'r', encoding='utf-8', errors='ignore') as f:
                all_lines = f.readlines()
        except Exception as e:
            print(f"Error loading log file: {e}")
            return False
        
        # Skip to start line
        all_lines = all_lines[start_line:]
        
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
    print(f"Input:  {args.input_log}")
    print(f"Output: {output_dir}")
    print(f"Speed:  {args.speed}x")
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
    
    # Clear output if requested
    if args.clear_output:
        output_file = output_dir / f"L{datetime.now().strftime('%Y%m%d')}.log"
        if output_file.exists():
            output_file.unlink()
            print(f"Cleared: {output_file}")
    
    # Create and run emulator
    emulator = LogEmulator(
        input_path=args.input_log,
        output_dir=output_dir,
        speed=args.speed
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
