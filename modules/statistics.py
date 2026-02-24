# -*- coding: utf-8 -*-
"""
Statistics Module

Functions for building match statistics from parsed data.
"""

import math
from collections import defaultdict
import logging
from data_models import TeamStats, BuildingStats, PlayerStats, ResourceStats
from icon_config import normalize_unit_name, is_ai_unit, is_greatworm

def build_building_stats_from_log(buildings, teams=["Sol", "Centauri", "Alien"], team_tech_events=None):

    """
    Build BuildingStats objects from building data.
    
    Args:
        buildings: dict of Building namedtuples
        teams: list of team names
    
    Returns:
        dict: {team_name: BuildingStats}
    """
    stats = {team: BuildingStats(team) for team in teams}
    
    # Create a timeline of all building events
    events = []
    
    # Add tech-level change events FIRST (outside building loop!)
    if team_tech_events:
        for tech_team, tech_list in team_tech_events.items():
            if tech_team not in stats:
                continue
            for t, tier in tech_list:
                events.append(("tech", t, tech_team, tier))
    
    # Now process buildings
    for building in buildings.values():
        team = building.team
        name = building.name

        if team not in stats:
            continue        
       
        # Construction start event
        if building.start_t is not None:
            events.append(("start", building.start_t, team, name))
        
        # Destruction event
        if building.destroy_t is not None:
            events.append(("destroy", building.destroy_t, team, name))
        
        # Sold event (new!)
        if building.sold_t is not None:
            events.append(("sold", building.sold_t, team, name))
    
    events.sort(key=lambda x: x[1])  # Sort by time

    for event_type, time, team, value in events:
        if team not in stats:
            continue

        if event_type == "start":
            building_name = value
            stats[team].record_construction_start(building_name, time)
        elif event_type == "destroy":
            building_name = value
            stats[team].record_destruction(building_name, time)
        elif event_type == "sold":
            building_name = value
            stats[team].record_sold(building_name, time)
        elif event_type == "tech":
            tier = int(value)
            stats[team].record_tech_change(tier, time)

    
    return stats




def build_stats_from_kills(kills, teams=["Sol", "Centauri", "Alien"]):
    """
    Build TeamStats objects from kill events.
    
    Handles:
    - Regular kills between teams
    - Team kills (same team)
    - Greatworm kills (wildlife)
    
    Returns:
        dict: {team_name: TeamStats}
    """
    stats = {team: TeamStats(team) for team in teams}
    
    for kill in sorted(kills, key=lambda k: k.time):
        # Check if this is a team kill
        is_teamkill = (kill.attacker_team == kill.victim_team)
        
        # Check if victim is a Greatworm (wildlife)
        victim_is_worm = is_greatworm(kill.victim_unit)
        
        # Check if attacker is a Greatworm (wildlife killed a player)
        attacker_is_worm = is_greatworm(kill.attacker_unit)
        
        # Victim's team loses something (unless victim is a Greatworm which has no team)
        if not victim_is_worm and kill.victim_team in stats:
            # Record death, and if killed by worm, mark it
            stats[kill.victim_team].record_loss(
                kill.time, 
                kill.is_structure, 
                killed_by_worm=attacker_is_worm
            )
        
        # Attacker's team gets credit (unless teamkill)
        if kill.attacker_team in stats:
            stats[kill.attacker_team].record_kill(
                kill.time, 
                kill.is_structure, 
                is_teamkill=is_teamkill,
                is_worm_kill=victim_is_worm
            )
    
    return stats




def get_all_team_building_stats_at_time(building_stats_dict, current_time):
    """
    Get building stats for all teams at a specific time.
    
    Returns:
        dict: {team_name: (hq_built, hq_current, refs_built, refs_current, bio_built, bio_current, nodes_built, nodes_lost, tech_level)}
    """
    result = {}
    for team_name, stats in building_stats_dict.items():
        result[team_name] = stats.get_stats_at_time(current_time)
    return result




def build_all_stats_from_log(buildings, kills, teams=["Sol", "Centauri", "Alien"], team_tech_events=None):

    """
    Build both kill stats and building stats.
    
    Returns:
        tuple: (kill_stats_dict, building_stats_dict)
    """
    kill_stats = build_stats_from_kills(kills, teams)
    building_stats = build_building_stats_from_log(buildings, teams, team_tech_events)

    
    return kill_stats, building_stats




def build_player_stats_from_kills(kills):
    """
    Build PlayerStats objects from kill events.
    
    Returns:
        dict: {player_name: PlayerStats}
    """
    players = {}
    
    for kill in kills:
        attacker = kill.attacker_name
        victim = kill.victim_name
        attacker_team = kill.attacker_team
        victim_team = kill.victim_team
        
        # Check if this involves a Greatworm
        victim_is_worm = is_greatworm(kill.victim_unit)
        attacker_is_worm = is_greatworm(kill.attacker_unit)
        
        # Track worm deaths for victims (human players killed by worms)
        if attacker_is_worm and not is_ai_unit(victim):
            if victim not in players:
                players[victim] = PlayerStats(victim, victim_team)
            players[victim].worm_deaths += 1
        
        # Skip if attacker is AI unit (including worms as attackers for kill credit)
        if is_ai_unit(attacker):
            continue
        
        # Initialize attacker if new
        if attacker not in players:
            players[attacker] = PlayerStats(attacker, attacker_team)
        
        # Initialize victim if new (but only for death tracking)
        if victim not in players and not is_ai_unit(victim):
            players[victim] = PlayerStats(victim, victim_team)
        
        # Skip if attacker is "Unknown" or system
        if attacker == "Unknown" or attacker_team == "Unknown":
            continue
        
        player = players[attacker]
        
        # Record the kill
        player.kill_events.append(kill)
        player.total_kills += 1
        
        # Track worm kills
        if victim_is_worm:
            player.worm_kills += 1
        
        if kill.is_structure:
            player.building_kills += 1
            # Check for specific building types
            if kill.victim_unit == "Node":
                player.node_kills += 1
        else:
            player.unit_kills += 1
            # Check for specific unit types
            if "Harvester" in kill.victim_unit:
                player.harvester_kills += 1
            elif kill.victim_unit == "Shrimp":
                player.shrimp_kills += 1
        
        # Track kills by victim
        player.kills_by_victim[victim] += 1
        
        # Check if this is a team kill
        if attacker_team == victim_team:
            player.teamkills += 1
        
        # Calculate range for longest range kill (if we have positions)
        if kill.attacker_x is not None and kill.x is not None:
            range_dist = math.sqrt(
                (kill.x - kill.attacker_x)**2 + 
                (kill.y - kill.attacker_y)**2
            )
            if player.longest_range_kill is None or range_dist > player.longest_range_kill[0]:
                player.longest_range_kill = (range_dist, kill.attacker_unit, kill.victim_unit, kill.time)
    
    return players




def build_unit_kill_stats(kills):
    """
    Build statistics for which units got the most kills.
    
    Returns:
        dict: {unit_name: kill_count}
    """
    unit_kills = defaultdict(int)
    
    for kill in kills:
        if kill.attacker_unit and kill.attacker_unit != "Unknown":
            unit_kills[kill.attacker_unit] += 1
    
    return unit_kills


def build_kill_stats_from_srpl(srpl_replay, teams=["Sol", "Centauri", "Alien"]):
    """
    Build TeamStats from SRPL destruction events (includes ALL kills, not just player-related).

    Args:
        srpl_replay: SrplReplay object with .destructions and .entities
        teams: list of team names

    Returns:
        dict: {team_name: TeamStats}
    """
    stats = {team: TeamStats(team) for team in teams}

    for tick, victim_id, attacker_id, is_building in sorted(srpl_replay.destructions, key=lambda d: d[0]):
        time_s = srpl_replay.tick_to_seconds(tick)
        victim_ent = srpl_replay.entities.get(victim_id)
        attacker_ent = srpl_replay.entities.get(attacker_id)

        if victim_ent is None:
            continue

        victim_team = victim_ent.team_name
        attacker_team = attacker_ent.team_name if attacker_ent else "Unknown"

        is_teamkill = (attacker_team == victim_team)

        # Victim team records a loss
        if victim_team in stats:
            stats[victim_team].record_loss(time_s, is_building)

        # Attacker team gets credit (skip teamkills)
        if attacker_team in stats:
            stats[attacker_team].record_kill(time_s, is_building, is_teamkill=is_teamkill)

    return stats


def build_resource_stats_from_log(resource_status_events, teams=["Sol", "Centauri", "Alien"]):
    """
    Build ResourceStats objects from resource_status events parsed from the log.
    
    Args:
        resource_status_events: list of ResourceStatusEvent namedtuples
        teams: list of team names
    
    Returns:
        dict: {team_name: ResourceStats}
    """
    stats = {team: ResourceStats(team) for team in teams}
    
    for event in sorted(resource_status_events, key=lambda e: e.time):
        if event.team in stats:
            stats[event.team].record_status(event.time, event.collected, event.spent)
    
    return stats


