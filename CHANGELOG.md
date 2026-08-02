# Changelog

## 2026-08-02

### Fix: killbar stopped showing events entirely
- `KillbarScrollBuffer.get_killbar()` decided "has anything changed?" by counting
  only **non-structure** kills, while `_filter_kills_for_killbar()` displays
  structure kills too. Silica stopped logging unit kills around 2026-07-07, so
  that counter sat at 0 for whole rounds, the cached (empty) panel was returned
  every frame and the killbar never repainted — despite the log being full of
  `structure_kill` lines. Now counts every kill up to the current time.

### Emulator: dedicated sandbox instead of the server's UserData
- The emulator wrote its replayed log into `UserData/logs/L<today>.log` and its
  streamed SRPL into `UserData/ReplayLogs`, i.e. straight into the live server's
  own directories. `--clear-output` deleted the **real** server log for today.
- Everything now lives under `Mod MapReplay/Emulator/` (`logs/`, `ReplayLogs/`,
  `emulation.active`). The `.srpl` **source** pool stays `UserData/ReplayLogs`,
  read-only — source and destination are separate settings now.
- `--clear-output` truncates in place rather than unlinking, since a following
  service holds the file open and Windows will not delete an open file.

### Service: follows the emulator in and out of its sandbox
- Detected via a heartbeat marker the emulator maintains, not by scanning for a
  running `Run_Emulator.bat` — the marker also covers `Log_Emulator.py` started
  directly, and a stale heartbeat releases the service if the emulator is killed.
- The parser clock is reset on a directory switch or truncation. Without it the
  emulated log (starting at, say, 18:25) looked like a backwards jump from the
  live log, the rollover heuristic added 86400s to every game time, and the SRPL
  lookup then landed past the end of the recording — **no units on the map**.
- Emulated streams use `time_offset = 0` instead of a wall-clock difference. The
  emulator writes the SRPL header exactly when it emits `Round_Start`, so tick 0
  is game time 0 by construction; under fast playback the service reads that line
  minutes later and the lag would be applied as a bogus shift.
- The emulated log is drained before returning to the live log, so the backlog
  left when the emulator exits (including the `Round_Win` that finalizes the
  video) is not discarded.

### Emulator: complete SRPL streams, and multi-game runs
- `Round_Win` now drains the remaining SRPL records unpaced instead of cutting
  the stream. At 50x the writer ran ~750 ticks behind, truncating the `.srpl`;
  since frame generation is SRPL-tick-driven the replay simply froze there.
- Streamed files are kept until the next run sweeps them, rather than being
  deleted when the next game starts. The emulator races ahead of rendering, so
  deleting on rotation left every game after the first with no SRPL at all.
- The 120s freshness check is skipped for emulated streams (a later game's file
  is legitimately minutes old by the time rendering reaches it), and games are
  paired with the oldest unused `EMU_` file for their map. Both are gated on the
  SRPL directory being the emulator sandbox, so live recording is unaffected by
  leftover `EMU_` files in `UserData/ReplayLogs`.

### Emulator: off-by-one dropped the map line
- `--start-line` / `--select-game` line numbers are 1-based but were used as a
  0-based slice index, so the slice lost its own first line — which is the
  `Loading map "X"` line the selector deliberately starts at. The service never
  learned the map, sat at `Map: Unknown` and produced no frames.
- The current map is also seeded from the skipped history, so the `.srpl` lookup
  works no matter where the slice begins (6 of 33 games previously found no SRPL).

## 2026-07-09

### Fix: Log Emulator now streams the matching .srpl (unit movement)
- Frame generation in the live service is SRPL-tick-driven and it rejects any
  `.srpl` whose mtime is > 120s old ("SRPL file too old, skipping"). The emulator
  only replayed the text log, so historical SRPLs were always rejected and
  emulated replays rendered with **no unit movement** and none of the SRPL-only
  panels (detailed unit stats, AI-vs-AI kills, harvester stats).
- `Log_Emulator.py` now streams the matching `.srpl` alongside the log, paced to
  the **same** speed multiplier: on each emitted `Round_Start` it finds the SRPL
  for that map+time in `UserData/ReplayLogs`, rewrites its header start-timestamp
  to "now" (so the service computes a ~0 time offset), and dribbles its records
  into `ReplayLogs/EMU_<name>.srpl` so SRPL tick T becomes visible exactly when
  the log reaches game-time T. Stops the stream on `Round_Win`.
- New flags: `--no-srpl` (replay log only, old behaviour) and `--srpl-dir PATH`
  (override the ReplayLogs location). Stale `EMU_*.srpl` files are swept at
  startup.

## 2026-04-12

### Wildlife stats now fully tracked
- Added `"Wildlife"` to the default `teams=` list in all statistics builders
  (`build_building_stats_from_log`, `build_stats_from_kills`, `build_all_stats_from_log`,
  `build_resource_stats_from_log`, `build_kill_stats_from_srpl`,
  `build_harvester_stats_from_srpl`). Previously Wildlife was silently dropped.
- `MapReplay_Service.py`: pass explicit 4-team list to `build_all_stats_from_log`
  and `build_resource_stats_from_log` so Wildlife buildings (Nests) and resource
  status events are included.
- `renderer.py` team-stats table: Wildlife row now shows real Nest build/lost
  counts and overall Bldgs Build/Lost from `building_stats` instead of hardcoded
  `"-"` (tech / harvesters / nodes remain `-` since they don't apply).
- Discord webhook post: commander line now includes the Wildlife commander
  (guarded against `None` entries).

### Fix: phantom short replay after match end
- `MapReplay_Service.py`: added a 30s cooldown after `Round_Win` during which
  trailing gameplay events (final `resource_status` ticks, mop-up kills,
  `construction_complete` from post-match cleanup) can no longer trigger the
  auto-detect path and start a phantom "new game". Legitimate back-to-back
  rounds (typical gap > 1 min) are unaffected.
