# -*- coding: utf-8 -*-
"""
Data Models Module

All data structures: namedtuples and statistics classes.
"""

from collections import namedtuple, defaultdict
import logging
import math

Building = namedtuple(
    "Building",
    ["team", "name", "x", "y", "start_t", "complete_t", "destroy_t", "sold_t"]
)

KillEvent = namedtuple(
    "KillEvent",
    ["time", "x", "y", "victim_team", "victim_unit", "attacker_team", "attacker_unit", 
     "attacker_x", "attacker_y", "attacker_name", "victim_name", "is_structure", "kill_number"]
)

DeathEvent = namedtuple(
    "DeathEvent",
    ["time", "player_name", "team", "death_type", "x", "y"]  # death_type: "suicide", "killed", "teamkill"
)

# Resource patch on the map
Resource = namedtuple(
    "Resource",
    ["resource_type", "x", "y", "amount", "spawn_t", "depleted_t"]  # resource_type: "Balterium" or "Biotics"
)

# Victory/end game info
VictoryInfo = namedtuple(
    "VictoryInfo",
    ["winning_team", "commander", "end_type", "time"]  # end_type: "Victory", "MapChange", "EndRound", etc.
)

# Chat message from players
ChatMessage = namedtuple(
    "ChatMessage",
    ["time", "player_name", "team", "message", "is_team_chat"]  # is_team_chat: True for say_team, False for say
)

# Resource status snapshot per team (collected & spent totals)
ResourceStatusEvent = namedtuple(
    "ResourceStatusEvent",
    ["time", "team", "collected", "spent"]
)

# === Si_KingOfTheHill (KGT / King of the Galactic Teleport) events ===

# Position + radii of the central capture point. Emitted once per round on KoH spawn.
KohSpawn = namedtuple(
    "KohSpawn",
    ["time", "x", "z", "capture_radius", "exclusion_radius", "win_threshold"]
)

# Perimeter ring of outposts around the capture zone. Positions are not enumerated
# individually; derive as `count` points evenly around (center_x, center_z) at `radius`.
OutpostRing = namedtuple(
    "OutpostRing",
    ["time", "center_x", "center_z", "radius", "count", "bury_depth"]
)

# Ownership change. previous_team == "none" on first capture of the round.
KohKingChange = namedtuple(
    "KohKingChange",
    ["time", "team", "previous_team", "progress_pct"]
)

# Milestone progress crossing (25 / 50 / 75 / 95 %).
KohProgress = namedtuple(
    "KohProgress",
    ["time", "team", "pct", "accumulated", "threshold"]
)

# Final win event (separate from the existing Victory line — KGT-specific).
KohWin = namedtuple(
    "KohWin",
    ["time", "winner"]
)


class TeamStats:
    """Track statistics for a single team throughout the match."""
    
    def __init__(self, team_name):
        self.team_name = team_name
        
        # Cumulative counts over time
        # Timeline: (time, lost_units, lost_buildings, killed_units, killed_buildings, worm_kills, worm_deaths)
        self.timeline = []
        
        # Current counts
        self.lost_units = 0
        self.lost_buildings = 0
        self.killed_units = 0
        self.killed_buildings = 0
        
        # Greatworm stats
        self.worm_kills = 0      # Number of Greatworms killed by this team
        self.worm_deaths = 0     # Number of team members killed by Greatworms
    
    def record_loss(self, time, is_structure, killed_by_worm=False):
        """Record a loss for this team."""
        if is_structure:
            self.lost_buildings += 1
            logging.debug(f"[{self.team_name}] t={time:.1f}s - Building lost (total: {self.lost_buildings})")
        else:
            self.lost_units += 1
            if killed_by_worm:
                self.worm_deaths += 1
                logging.debug(f"[{self.team_name}] t={time:.1f}s - Unit killed by Greatworm (total worm deaths: {self.worm_deaths})")
        self._save_snapshot(time)
    
    def record_kill(self, time, is_structure, is_teamkill=False, is_worm_kill=False):
        """
        Record a kill by this team.
        
        Args:
            time: Game time in seconds
            is_structure: Whether the kill was a building
            is_teamkill: If True, this was a team kill (don't count as a kill)
            is_worm_kill: If True, the victim was a Greatworm
        """
        if is_teamkill:
            # Team kills don't count as kills for the attacker
            logging.debug(f"[{self.team_name}] t={time:.1f}s - TEAMKILL {'building' if is_structure else 'unit'} (not counted as kill)")
            return
        
        if is_worm_kill:
            self.worm_kills += 1
            logging.debug(f"[{self.team_name}] t={time:.1f}s - Greatworm killed (total worm kills: {self.worm_kills})")
        elif is_structure:
            self.killed_buildings += 1
        else:
            self.killed_units += 1
        self._save_snapshot(time)
    
    def _save_snapshot(self, time):
        """Save current state to timeline."""
        self.timeline.append((
            time,
            self.lost_units,
            self.lost_buildings,
            self.killed_units,
            self.killed_buildings,
            self.worm_kills,
            self.worm_deaths
        ))
    
    def get_stats_at_time(self, time):
        """Get stats at a specific time (finds closest snapshot <= time)."""
        if not self.timeline:
            return (0, 0, 0, 0, 0, 0)  # 6 values now
        
        # Find last entry before or at this time
        for i in range(len(self.timeline) - 1, -1, -1):
            if self.timeline[i][0] <= time:
                return self.timeline[i][1:]  # Return everything except time
        
        return (0, 0, 0, 0, 0, 0)  # 6 values now
    




class BuildingStats:
    """Track building statistics for a single team throughout the match."""
    
    def __init__(self, team_name):
        self.team_name = team_name
        self.timeline = []  # List of (time, hq_built, hq_current, refs_built, refs_current, bio_built, bio_current, nodes_built, nodes_lost, tech_level)
        
        # Cumulative counts
        self.hq_built = 0           # Total HQs/Nests started
        self.hq_destroyed = 0       # Total HQs/Nests destroyed (by enemy or team kill)
        self.hq_sold = 0            # Total HQs/Nests sold (voluntary removal)
        
        self.refs_built = 0         # Total Refineries started
        self.refs_destroyed = 0     # Total Refineries destroyed
        self.refs_sold = 0          # Total Refineries sold
        
        self.bio_built = 0          # Total Bio Caches started (Alien only)
        self.bio_destroyed = 0      # Total Bio Caches destroyed
        self.bio_sold = 0           # Total Bio Caches sold
        
        self.nodes_built = 0        # Total Nodes started (Alien only)
        self.nodes_lost = 0         # Total Nodes destroyed
        
        self.tech_level = 0         # Highest tech level achieved
        self.total_built = 0 
        
        # Building type mappings
        self.hq_types = {"Headquarters", "Nest"}
        self.refinery_types = {"Refinery"}
        self.bio_types = {"BioCache"}
        self.node_types = {"Node"}
        
        # Tech level buildings (order matters!)
        self.tech_buildings = [
            "Barracks",           # Tech 1
            "LightFactory",       # Tech 2
            "HeavyFactory",       # Tech 3
            "AirFactory",         # Tech 4
            "UltraHeavyFactory",  # Tech 5
        ]
    
    def record_construction_start(self, building_name, time):
        """Record when a building construction starts."""
        
        self.total_built += 1
        if building_name in self.hq_types:
            self.hq_built += 1
            logging.debug(f"[{self.team_name}] t={time:.1f}s - HQ #{self.hq_built} started: {building_name}")
        elif building_name in self.refinery_types:
            self.refs_built += 1
            logging.debug(f"[{self.team_name}] t={time:.1f}s - Refinery #{self.refs_built} started: {building_name}")
        elif building_name in self.bio_types:
            self.bio_built += 1
            logging.debug(f"[{self.team_name}] t={time:.1f}s - BioCache #{self.bio_built} started: {building_name}")
        elif building_name in self.node_types:
            self.nodes_built += 1
            logging.debug(f"[{self.team_name}] t={time:.1f}s - Node #{self.nodes_built} started: {building_name}")
        
        # Check tech level
        if building_name in self.tech_buildings:
            tech_idx = self.tech_buildings.index(building_name) + 1
            if tech_idx > self.tech_level:
                self.tech_level = tech_idx
                logging.debug(f"[{self.team_name}] t={time:.1f}s - Tech Level {tech_idx} reached: {building_name}")
        
        self._save_snapshot(time)
    
    def record_destruction(self, building_name, time):
        """Record when a building is destroyed (by combat)."""
        if building_name in self.hq_types:
            self.hq_destroyed += 1
            logging.debug(f"[{self.team_name}] t={time:.1f}s - HQ destroyed (total destroyed: {self.hq_destroyed})")
        elif building_name in self.refinery_types:
            self.refs_destroyed += 1
            logging.debug(f"[{self.team_name}] t={time:.1f}s - Refinery destroyed (total destroyed: {self.refs_destroyed})")
        elif building_name in self.bio_types:
            self.bio_destroyed += 1
            logging.debug(f"[{self.team_name}] t={time:.1f}s - BioCache destroyed (total destroyed: {self.bio_destroyed})")
        elif building_name in self.node_types:
            self.nodes_lost += 1
            logging.debug(f"[{self.team_name}] t={time:.1f}s - Node destroyed (total destroyed: {self.nodes_lost})")
        
        self._save_snapshot(time)
    
    def record_sold(self, building_name, time):
        """Record when a building is sold (voluntary removal, not destruction)."""
        if building_name in self.hq_types:
            self.hq_sold += 1
            logging.debug(f"[{self.team_name}] t={time:.1f}s - HQ SOLD (total sold: {self.hq_sold})")
        elif building_name in self.refinery_types:
            self.refs_sold += 1
            logging.debug(f"[{self.team_name}] t={time:.1f}s - Refinery SOLD (total sold: {self.refs_sold})")
        elif building_name in self.bio_types:
            self.bio_sold += 1
            logging.debug(f"[{self.team_name}] t={time:.1f}s - BioCache SOLD (total sold: {self.bio_sold})")
        # Note: Nodes cannot be sold in game
        
        self._save_snapshot(time)
    
    def _save_snapshot(self, time):
        """Save current state to timeline."""
        # Calculate current counts (built - destroyed - sold)
        hq_current = max(0, self.hq_built - self.hq_destroyed - self.hq_sold)
        refs_current = max(0, self.refs_built - self.refs_destroyed - self.refs_sold)
        bio_current = max(0, self.bio_built - self.bio_destroyed - self.bio_sold)
        
        self.timeline.append((
            time,
            self.hq_built,
            hq_current,
            self.refs_built,
            refs_current,
            self.bio_built,
            bio_current,
            self.nodes_built,
            self.nodes_lost,
            self.tech_level,
            self.total_built,
        ))
    
    def get_stats_at_time(self, time):
        """Get building stats at a specific time."""
        # Wenn es noch keine Snapshots gibt: alles 0
        # Reihenfolge:
        # hq_built, hq_current,
        # refs_built, refs_current,
        # bio_built, bio_current,
        # nodes_built, nodes_lost,
        # tech_level, total_built
        if not self.timeline:
            return (0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    
        # Letzten Eintrag suchen, dessen Zeit <= current_time ist
        for i in range(len(self.timeline) - 1, -1, -1):
            if self.timeline[i][0] <= time:
                return self.timeline[i][1:]  # alles auÃƒÆ’Ã…Â¸er der Zeit
    
        # Falls alle EintrÃƒÆ’Ã‚Â¤ge NACH current_time liegen (z.B. ganz am Anfang des Spiels)
        return (0, 0, 0, 0, 0, 0, 0, 0, 0, 0)

            
    def record_tech_change(self, tier, time):
        """Record a technology_change event from the log (tiers can go up to 8)."""
        if tier > self.tech_level:
            self.tech_level = tier
        self._save_snapshot(time)






class PlayerStats:
    """Track detailed statistics for individual players."""
    
    def __init__(self, player_name, team):
        self.player_name = player_name
        self.team = team
        
        # Kill statistics
        self.total_kills = 0
        self.unit_kills = 0
        self.building_kills = 0
        self.harvester_kills = 0
        self.node_kills = 0
        self.shrimp_kills = 0
        self.worm_kills = 0      # Greatworms killed by this player
        
        # Death statistics
        self.total_deaths = 0
        self.suicide_deaths = 0
        self.worm_deaths = 0     # Times killed by Greatworm
        
        # Team kill statistics
        self.teamkills = 0
        
        # Kill details (for specific achievements)
        self.kills_by_victim = defaultdict(int)  # {victim_name: count}
        self.longest_range_kill = None  # (range, weapon, victim_unit, time)
        
        # Detailed kill records
        self.kill_events = []  # List of KillEvent objects
        self.death_events = []  # List of DeathEvent objects


class ResourceStats:
    """Track resource collected/spent for a single team throughout the match."""
    
    def __init__(self, team_name):
        self.team_name = team_name
        # Timeline: list of (time, collected, spent)
        self.timeline = []
    
    def record_status(self, time, collected, spent):
        """Record a resource_status snapshot."""
        self.timeline.append((time, collected, spent))
    
    def get_stats_at_time(self, time):
        """Get resource stats at a specific time (finds closest snapshot <= time).
        
        Returns:
            tuple: (collected, spent) or (0, 0) if no data yet
        """
        if not self.timeline:
            return (0, 0)
        
        for i in range(len(self.timeline) - 1, -1, -1):
            if self.timeline[i][0] <= time:
                return self.timeline[i][1:]  # (collected, spent)
        
        return (0, 0)

