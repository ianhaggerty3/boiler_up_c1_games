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
    utility: Utility
    ARENA_SIZE: int
    factory_height: int
    cached_health: int
    health: int
    mobile_units: Set[Union[str, int]]
    scored_on_locations: List[List[int]]
    recent_scored_on_locations: List[List[int]]
    latest_enemy_spawns: List[Union[str, int, List[int]]]
    latest_enemy_removes: List[Union[str, int, List[int]]]
    factory_locations: List[List[int]]

    wall_upgrade_added: bool

    def __init__(self):
        super().__init__()
        # utility functions for data structures, mostly
        self.utility = Utility()
        self.ARENA_SIZE = 28
        self.factory_height = 9

        seed = random.randrange(maxsize)
        random.seed(seed)
        debug_write('Random seed: {}'.format(seed))

        self.factory_locations = list(self.factory_location_generator(self.factory_height))
        random.shuffle(self.factory_locations)

        self.scored_on_locations = []
        self.recent_scored_on_locations = []
        self.mobile_units = set()
        self.latest_enemy_spawns = []

        # macro game stage bools
        self.wall_upgrade_added = False


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

        # initial strategy is highly dependent on expected units. Don't want to react until after we've built a little.
        if len(self.recent_scored_on_locations) and game_state.turn_number > 3:
            self.build_reactive_defense()

        # On the initial turn, try to get them with a destructor
        if game_state.turn_number == 0:
            self.send_initial_destructor(game_state)

        if game_state.turn_number == 1:
            self.utility.append_action('initial_turret_upgrades', TURRET, [[3, 13], [24, 13]], upgrade=True)
            self.utility.prioritize_action('initial_turret_upgrades')

        if game_state.turn_number == 2:
            # we want to manually manage and not upgrade these specific walls
            self.build_left_side_wall(game_state)
            # best attack we can do before having an actual structure; should have 12 mp here
            game_state.attempt_spawn(DEMOLISHER, [26, 12], num=2)
            game_state.attempt_spawn(SCOUT, [13, 0], num=100)

            self.utility.remove_action('initial_walls')
            self.utility.append_action('frontal_wall', WALL, self.get_frontal_wall())

            # put upgrades before spawns to upgrade before spawning more; these cover the rest of the game
            self.utility.append_action("upgrade_factories", '', self.factory_locations, True)
            self.utility.append_action("extra_factories", FACTORY, self.factory_locations)

        if game_state.turn_number == 3:
            # clean up from previous attack
            self.build_right_side_wall(game_state)

        if game_state.turn_number == 4:
            self.utility.remove_action('initial_turrets')
            self.utility.remove_action('initial_turret_upgrades')
            self.utility.append_action('frontal_turrets', TURRET, self.get_frontal_turrets())
            self.utility.append_action('frontal_turret_upgrades', TURRET, self.get_frontal_turrets(), upgrade=True)
            self.utility.prioritize_action('frontal_turrets')
            self.utility.prioritize_action('frontal_turret_upgrades')

        # attack logic; manually building to maintain walls if they are destroyed
        if game_state.turn_number >= 4:
            if game_state.turn_number % 6 == 4:
                self.destroy_left_side_wall(game_state)
                self.build_right_side_wall(game_state)
            if game_state.turn_number % 6 == 5:
                self.mount_left_attack(game_state)
                self.build_right_side_wall(game_state)
            if game_state.turn_number % 6 == 0:
                self.build_left_side_wall(game_state)
                self.build_right_side_wall(game_state)
            if game_state.turn_number % 6 == 1:
                self.destroy_right_side_wall(game_state)
                self.build_left_side_wall(game_state)
            if game_state.turn_number % 6 == 2:
                self.mount_right_attack(game_state)
                self.build_left_side_wall(game_state)
            if game_state.turn_number % 6 == 3:
                self.build_right_side_wall(game_state)
                self.build_left_side_wall(game_state)

        # always try to use more resources
        self.utility.attempt_actions(game_state)
        
    def incremental_turret(self, game_state):
        """
            Attempt to build out Turrets from one side as the game progresses
        """
        if(game_state.turn_number > 4):
            turret_build = [[23 - x, 13] for x in range(game_state.turn_number - 3)]
            self.utility.remove_action("add_front_turrets")
            self.utility.remove_action("upgrade_front_turrets")
            self.utility.append_action("upgrade_front_turrets", '', turret_build, upgrade=True)
            self.utility.append_action("add_front_turrets", '', turret_build)

    def get_frontal_wall(self):
        """
        Fill in everywhere between the side turrets. Leave space for future turrets at four spaces, and a middle gap
        """
        return [[4, 12], [5, 13], [6, 13], [7, 13], [8, 13], [9, 13], [10, 13], [11, 12], [12, 13], [13, 12],
                        [14, 12], [15, 13], [16, 12], [17, 13], [18, 13], [19, 13], [20, 13], [21, 13], [22, 13],
                        [23, 12]]

    def get_frontal_turrets(self):
        """
        Frontal turrets along the wall, which are in an intended order
        """
        return [[4, 13], [23, 13], [16, 13], [11, 13], [3, 13], [24, 13]]

    def factory_location_generator(self, starting_y: int):
        """"
            Generates locations for factories beneath a certain y value
            Leaves space open always for scouts
        """
        for y in range(0, starting_y + 1):
            for x in range(15 - y, 13 + y):
                yield [x, y]


    def mount_left_attack(self, game_state: GameState):
        # might want to base this off of whether our wall will be intact or not; changes pathing
        # might want to make demolishers proportional to resources, rather than 4 flat
        game_state.attempt_spawn(DEMOLISHER, [3, 10], num=4)
        game_state.attempt_spawn(SCOUT, [14, 0], num=1000)

    def mount_right_attack(self, game_state: GameState):
        game_state.attempt_spawn(DEMOLISHER, [24, 10], num=4)
        game_state.attempt_spawn(SCOUT, [13, 0], num=1000)


    ### The side walls need to be manually managed, because they are integral to attacking maneuvers
    def build_side_walls(self, game_state: GameState):
        self.build_left_side_wall(game_state)
        self.build_right_side_wall(game_state)

    def build_left_side_wall(self, game_state: GameState):
        game_state.attempt_spawn(WALL, [[0, 13], [1, 13], [2, 13]])

    def build_right_side_wall(self, game_state: GameState):
        game_state.attempt_spawn(WALL, [[27, 13], [26, 13], [25, 13]])

    def destroy_side_walls(self, game_state: GameState):
        self.destroy_left_side_wall(game_state)
        self.destroy_right_side_wall(game_state)

    def destroy_left_side_wall(self, game_state: GameState):
        game_state.attempt_remove([[0, 13], [1, 13], [2, 13]])

    def destroy_right_side_wall(self, game_state: GameState):
        game_state.attempt_remove([[27, 13], [26, 13], [25, 13]])

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

        wall_locations = [[0, 13], [27, 13], [12, 13], [13, 12], [14, 12], [15, 13]]
        self.utility.append_action('initial_walls', WALL, wall_locations)

        factory_locations = [[3, 12]]
        self.utility.append_action('initial_factories', FACTORY, factory_locations)
        self.utility.append_action('initial_factory_upgrade', FACTORY, factory_locations, upgrade=True)

    def get_response_location(self, location: List[int]):
        if location[0] < self.ARENA_SIZE // 2:
            return [location[0] + 1, location[1] + 1]
        else:
            return [location[0] - 1, location[1] + 1]

    def build_reactive_defense(self):
        """
        This function builds reactive defenses based on where the enemy scored on us from.
        We can track where the opponent scored by looking at events in action frames 
        as shown in the on_action_frame function
        """

        self.utility.remove_action('response_turrets')
        self.utility.remove_action('upgrade_response_turrets')

        response_locations = list(map(self.get_response_location, self.recent_scored_on_locations))

        self.utility.append_action('response_turrets', TURRET, response_locations)
        self.utility.append_action('upgrade_response_turrets', '', response_locations, True)
        self.utility.prioritize_action('upgrade_response_turrets')
        self.utility.prioritize_action('response_turrets')

    def send_initial_destructor(self, game_state: GameState):
        """
        Send out a demolisher to get enemy factories at the start
        """
        game_state.attempt_spawn(DEMOLISHER, [1, 12])
        game_state.attempt_spawn(INTERCEPTOR, [4, 9])

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

    def detect_own_unit(self, game_state: GameState, unit_type=None, valid_x = None, valid_y = None):
        total_units = 0
        for location in game_state.game_map:
            if game_state.contains_stationary_unit(location):
                for unit in game_state.game_map[location]:
                    if unit.player_index == 0 and (unit_type is None or unit.unit_type == unit_type) and (valid_x is None or location[0] in valid_x) and (valid_y is None or location[1] in valid_y):
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

        self.recent_scored_on_locations = []
        for breach in breaches:
            location = breach[0]
            unit_owner_self = True if breach[4] == 1 else False
            # When parsing the frame data directly, 
            # 1 is integer for yourself, 2 is opponent (StarterKit code uses 0, 1 as player_index instead)
            if not unit_owner_self:
                # debug_write("[DEBUG] Got scored on at: {}".format(location))
                self.scored_on_locations.append(location)
                self.recent_scored_on_locations.append(location)
                debug_write("[DEBUG] Recent scored on locations: {}".format(self.recent_scored_on_locations))
                # debug_write("[DEBUG] All scored on locations: {}".format(self.scored_on_locations))


    # def demolisher_line_strategy(self, game_state: GameState):
    #     """
    #     Build a line of the cheapest stationary unit so our demolisher can attack from long range.
    #     """
    #     # First let's figure out the cheapest unit
    #     # We could just check the game rules, but this demonstrates how to use the GameUnit class
    #     stationary_units = [WALL, TURRET, FACTORY]
    #     cheapest_unit = WALL
    #     for unit in stationary_units:
    #         unit_class = GameUnit(unit, game_state.config)
    #         if unit_class.cost[game_state.MP] < GameUnit(cheapest_unit, game_state.config).cost[game_state.MP]:
    #             cheapest_unit = unit
    #
    #     # Now let's build out a line of stationary units. This will prevent our demolisher from running into the enemy base.
    #     # Instead they will stay at the perfect distance to attack the front two rows of the enemy base.
    #     for x in range(27, 5, -1):
    #         game_state.attempt_spawn(cheapest_unit, [x, 11])
    #
    #     # Now spawn demolishers next to the line
    #     # By asking attempt_spawn to spawn 1000 units, it will essentially spawn as many as we have resources for
    #     game_state.attempt_spawn(DEMOLISHER, [24, 10], 1000)

if __name__ == "__main__":
    algo = AlgoStrategy()
    algo.start()