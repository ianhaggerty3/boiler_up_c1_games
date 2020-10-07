from gamelib import AlgoCore, debug_write, GameState, GameUnit
import random
import math
import warnings
from sys import maxsize
import json

from typing import Dict, List, Set, Union
from utility import Utility

"""
Most of the algo code you write will be in this file unless you create new
modules yourself. Start by modifying the 'on_turn' function.

Advanced strategy tips: 

  - You can analyze action frames by modifying on_action_frame function

  - The GameState.map object can be manually manipulated to create hypothetical 
  board states. Though, we recommended making a copy of the map to preserve 
  the actual current map state.
"""


class AlgoStrategy(AlgoCore):
    cached_health: int
    health: int
    utility: Utility
    mobile_units: Set[Union[str, int]]
    latest_enemy_spawns: List[Union[str, int, List[int]]]
    latest_enemy_removes: List[Union[str, int, List[int]]]

    def __init__(self):
        super().__init__()
        self.ARENA_SIZE = 28

        seed = random.randrange(maxsize)
        random.seed(seed)
        debug_write('Random seed: {}'.format(seed))

        self.scored_on_locations = []
        self.mobile_units = set()
        self.latest_enemy_spawns = []

        self.utility = Utility()

    def on_game_start(self, config):
        """ 
        Read in config and perform any initial setup here 
        """
        debug_write('Configuring your custom algo strategy...')
        self.config = config
        global WALL, FACTORY, TURRET, SCOUT, DEMOLISHER, INTERCEPTOR, MP, SP

        WALL = config["unitInformation"][0]["shorthand"]
        FACTORY = config["unitInformation"][1]["shorthand"]
        TURRET = config["unitInformation"][2]["shorthand"]
        SCOUT = config["unitInformation"][3]["shorthand"]
        DEMOLISHER = config["unitInformation"][4]["shorthand"]
        INTERCEPTOR = config["unitInformation"][5]["shorthand"]

        # index values used in action frames
        self.mobile_units.add(3)
        self.mobile_units.add(4)
        self.mobile_units.add(5)

        MP = 1
        SP = 0

        # This is a good place to do initial setup
        self.add_initial_defence()

    def on_turn(self, turn_state):
        """
        This function is called every turn with the game state wrapper as
        an argument. The wrapper stores the state of the arena and has methods
        for querying its state, allocating your current resources as planned
        unit deployments, and transmitting your intended deployments to the
        game engine.
        """
        game_state = GameState(self.config, turn_state)
        self.health = game_state.my_health
        if game_state.turn_number == 0:
            self.cached_health = self.health

        debug_write('Performing turn {} of your custom algo strategy'.format(game_state.turn_number))
        game_state.suppress_warnings(True)

        self.dynamic_strategy(game_state)
        self.cached_health = self.health

        game_state.submit_turn()

    def dynamic_strategy(self, game_state: GameState):
        """
        For defense we will use a spread out layout and some interceptors early on.
        We will place turrets near locations the opponent managed to score on.
        For offense we will use long range demolishers if they place stationary units near the enemy's front.
        If there are no stationary units to attack in the front, we will send Scouts to try and score quickly.
        """
        # First, place basic defenses
        # self.build_defences(game_state)
        # Now build reactive defenses based on where the enemy scored
        if self.cached_health != self.health:
            self.build_reactive_defense()

        # If the turn is less than 5, try to get them with a destructor
        factory_locations = [[13, 2], [14, 2], [13, 3], [14, 3]]
        
        if game_state.turn_number < 3:
            self.send_initial_destructor(game_state)
            self.utility.append_action("upgrade_factories", '', factory_locations, upgrade = True)
            self.utility.append_action("extra_factories", FACTORY, factory_locations)
        if game_state.turn_number == 3:
            self.utility.append_action("upgrade_factories", '', factory_locations, upgrade = True)
            self.utility.append_action('extra_factories', FACTORY, factory_locations)
        if game_state.turn_number >= 3:
            # Now let's analyze the enemy base to see where their defenses are concentrated.
            # If they have many units in the front we can build a line for our demolishers to attack them at long range.
            # if self.detect_enemy_unit(game_state, unit_type=None, valid_x=None, valid_y=[14, 15]) > 10:
            #     self.demolisher_line_strategy(game_state)
            # else:
            # They don't have many units in the front so lets figure out their least defended area and send Scouts there.

            # Only spawn Scouts every other turn
            # Sending more at once is better since attacks can only hit a single scout at a time
            self.incremental_turret(game_state)
            if game_state.turn_number % 2 == 1:
                # To simplify we will just check sending them from back left and right
                scout_spawn_location_options = [[10, 3], [11, 2], [16, 3], [17, 3]]
                try:
                    best_location = self.least_damage_spawn_location(game_state, scout_spawn_location_options)
                    game_state.attempt_spawn(SCOUT, best_location, 1000)
                except ValueError:
                    debug_write('could not find a path for spawning')

        # always try to use more resources
        self.utility.attempt_actions(game_state)
        
    def incremental_turret(self, game_state):
        """
            Attempt to build out Turrets from one side as the game progresses
        """
        if(game_state.turn_number > 4):
            turret_build = [[23 - x, 13] for x in range(game_state.turn_number - 3)]
            self.utility.append_action("upgrade_front_turrets", '', turret_build, upgrade=True)
            self.utility.append_action("upgrade_front_turrets", '', turret_build)

    def wall_surround(self, locations: List[List[int]]):
        """
        Surround the passed spot with walls, including the spot itself if empty
        """
        new_locations = []
        for location in locations:
            # we might eventually want to block where we spawn walls, but for now this logic isn't good enough; it can
            # still block useful paths, but prevents us from putting walls in some much-needed locations
            # new_locations += list(filter(
            #     lambda entry: not self.on_edge(entry),
            #     [[location[0], location[1]], [location[0] + 1, location[1]],
            #      [location[0] - 1, location[1]], [location[0], location[1] + 1]]
            # ))
            new_locations += [[location[0], location[1]], [location[0] + 1, location[1]],
                              [location[0] - 1, location[1]], [location[0], location[1] + 1]]

        self.utility.append_action('surround_walls' + str(len(locations)), WALL, new_locations)

    def add_initial_defence(self) -> None:
        """
        Build basic defenses using hardcoded locations.
        Remember to defend corners and avoid placing units in the front where enemy demolishers can attack them.
        """
        # Useful tool for setting up your base locations: https://www.kevinbai.design/terminal-map-maker
        # More community tools available at: https://terminal.c1games.com/rules#Download

        # Add default turrets
        turret_locations = [[3, 13], [24, 13]]
        self.utility.append_action('initial_turrets', TURRET, turret_locations)

        # initial_upgrades = [[5, 13], [24, 13]]
        # self.utility.append_action('initial_upgrades', '', initial_upgrades, upgrade=True)

        # Place walls in front of turrets to soak up damage for them
        # self.wall_surround(turret_locations)

        wall_locations = [[0, 13], [27, 13], [12, 13], [13, 13], [14, 13], [15, 13]]
        self.utility.append_action('initial_walls', WALL, wall_locations)

        factory_locations = [[3, 12]]
        self.utility.append_action('initial_factories', FACTORY, factory_locations)

    def build_reactive_defense(self):
        """
        This function builds reactive defenses based on where the enemy scored on us from.
        We can track where the opponent scored by looking at events in action frames 
        as shown in the on_action_frame function
        """

        try:
            self.utility.remove_action('response_turrets')
            self.utility.remove_action('upgrade_response_turrets')
        except ValueError:
            pass
        self.utility.append_action('upgrade_response_turrets', '', self.scored_on_locations, True)
        self.utility.append_action('response_turrets', TURRET, self.scored_on_locations)
        self.utility.prioritize_action('upgrade_response_turrets')
        self.utility.prioritize_action('response_turrets')
        # don't really want to put turrets there
        # for location in self.scored_on_locations:
        #     # Build turret one space above so that it doesn't block our own edge spawn locations
        #     # build_location = [location[0], location[1]+1]
        #     # game_state.attempt_spawn(TURRET, build_location)
        #     self.wall_surround(self.scored_on_locations)

    def send_initial_destructor(self, game_state: GameState):
        """
        Send out a demolisher to get enemy factories at the start
        """
        game_state.attempt_spawn(DEMOLISHER, [1, 12], num=4)
        game_state.attempt_spawn(INTERCEPTOR, [4, 9])

    def demolisher_line_strategy(self, game_state: GameState):
        """
        Build a line of the cheapest stationary unit so our demolisher can attack from long range.
        """
        # First let's figure out the cheapest unit
        # We could just check the game rules, but this demonstrates how to use the GameUnit class
        stationary_units = [WALL, TURRET, FACTORY]
        cheapest_unit = WALL
        for unit in stationary_units:
            unit_class = GameUnit(unit, game_state.config)
            if unit_class.cost[game_state.MP] < GameUnit(cheapest_unit, game_state.config).cost[game_state.MP]:
                cheapest_unit = unit

        # Now let's build out a line of stationary units. This will prevent our demolisher from running into the enemy base.
        # Instead they will stay at the perfect distance to attack the front two rows of the enemy base.
        for x in range(27, 5, -1):
            game_state.attempt_spawn(cheapest_unit, [x, 11])

        # Now spawn demolishers next to the line
        # By asking attempt_spawn to spawn 1000 units, it will essentially spawn as many as we have resources for
        game_state.attempt_spawn(DEMOLISHER, [24, 10], 1000)

    def least_damage_spawn_location(self, game_state: GameState, location_options: List[List[int]]):
        """
        This function will help us guess which location is the safest to spawn moving units from.
        It gets the path the unit will take then checks locations on that path to 
        estimate the path's damage risk.
        """
        damages = []
        # Get the damage estimate each path will take
        for location in location_options:
            path = game_state.find_path_to_edge(location)
            damage = 0

            if path is None:
                debug_write('[DEBUG] Could not find path for location:', location)
                continue

            for path_location in path:
                # Get number of enemy turrets that can attack each location and multiply by turret damage
                damage += len(game_state.get_attackers(path_location, 0)) * GameUnit(TURRET, game_state.config).damage_i
            damages.append(damage)
        
        # Now just return the location that takes the least damage
        return location_options[damages.index(min(damages))]

    def detect_enemy_unit(self, game_state: GameState, unit_type=None, valid_x = None, valid_y = None):
        total_units = 0
        for location in game_state.game_map:
            if game_state.contains_stationary_unit(location):
                for unit in game_state.game_map[location]:
                    if unit.player_index == 1 and (unit_type is None or unit.unit_type == unit_type) and (valid_x is None or location[0] in valid_x) and (valid_y is None or location[1] in valid_y):
                        total_units += 1
        return total_units

    def filter_blocked_locations(self, locations: List[List[int]], game_state: GameState):
        filtered = []
        for location in locations:
            if not game_state.contains_stationary_unit(location):
                filtered.append(location)
        return filtered

    def analyze_corner(self, game_state: GameState, id=1) -> List[int]:
        if id == 1:
            corner_spaces = [[]]
        else:
            corner_spaces = [[]]

        # [turrets, upgraded_turrets, walls, upgraded_walls, factories, upgraded_factories]
        count_list = [0, 0, 0, 0, 0, 0]
        for space in corner_spaces:
            if len(game_state.game_map[space[0], space[1]]):
                unit: GameUnit = game_state.game_map[space[0], space[1]][0]
                index_add = 1 if unit.upgraded else 0
                index = -1
                if unit.unit_type == TURRET:
                    index = 0 + index_add
                elif unit.unit_type == WALL:
                    index = 2 + index_add
                elif unit.unit_type == FACTORY:
                    index = 4 + index_add
                count_list[index] += 1

        return count_list

    def on_action_frame(self, turn_string: str):
        """
        This is the action frame of the game. This function could be called 
        hundreds of times per turn and could slow the algo down so avoid putting slow code here.
        Processing the action frames is complicated so we only suggest it if you have time and experience.
        Full doc on format of a game frame at: https://docs.c1games.com/json-docs.html
        """
        # Let's record at what position we get scored on
        state = json.loads(turn_string)
        events = state["events"]
        breaches = events["breach"]

        self.latest_enemy_spawns = filter(lambda event: event[3] == 2 and event[1] in self.mobile_units, events["spawn"])

        for spawn in self.latest_enemy_spawns:
            if spawn[1] == 3:
                debug_write("enemy spawned Scout at: " + str(spawn[0]))
            elif spawn[1] == 4:
                debug_write("enemy spawned Demolisher at: " + str(spawn[0]))
            elif spawn[1] == 5:
                debug_write("enemy spawned Interceptor at: " + str(spawn[0]))

        self.latest_enemy_removes = filter(lambda event: event[3] == 2 and event[1] == 6, events["spawn"])
        for unit in self.latest_enemy_removes:
            debug_write("enemy removed a unit at: " + str(unit[0]))

        for breach in breaches:
            location = breach[0]
            unit_owner_self = True if breach[4] == 1 else False
            # When parsing the frame data directly, 
            # 1 is integer for yourself, 2 is opponent (StarterKit code uses 0, 1 as player_index instead)
            if not unit_owner_self:
                # debug_write("[DEBUG] Got scored on at: {}".format(location))
                self.scored_on_locations.append(location)
                # debug_write("[DEBUG] All scored on locations: {}".format(self.scored_on_locations))


if __name__ == "__main__":
    algo = AlgoStrategy()
    algo.start()