from gamelib import AlgoCore, debug_write, GameState, GameUnit
from enum import Enum
import random
import math
import warnings
from sys import maxsize
import json

from typing import Dict, List, Set


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
    all_locations: Set[int]
    ARENA_SIZE = 28

    def __init__(self):
        super().__init__()
        seed = random.randrange(maxsize)
        random.seed(seed)
        debug_write('Random seed: {}'.format(seed))
        self.edge_set = self.construct_edge_set
        self.ARENA_SIZE = 28
        self.scored_on_locations = []
        self.all_locations = set()

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

        MP = 1
        SP = 0

        # This is a good place to do initial setup

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
        game_state.suppress_warnings(True)  #Comment or remove this line to enable warnings.

        self.starter_strategy(game_state)
        self.cached_health = self.health

        game_state.submit_turn()


    """
    NOTE: All the methods after this point are part of the sample starter-algo
    strategy and can safely be replaced for your custom algo.
    """

    def starter_strategy(self, game_state: GameState):
        """
        For defense we will use a spread out layout and some interceptors early on.
        We will place turrets near locations the opponent managed to score on.
        For offense we will use long range demolishers if they place stationary units near the enemy's front.
        If there are no stationary units to attack in the front, we will send Scouts to try and score quickly.
        """
        # First, place basic defenses
        self.build_defences(game_state)
        # Now build reactive defenses based on where the enemy scored
        if self.cached_health != self.health:
            self.build_reactive_defense(game_state)

        # If the turn is less than 5, stall with interceptors and wait to see enemy's base
        if game_state.turn_number < 5:
            self.stall_with_interceptors(game_state)
        else:
            # Now let's analyze the enemy base to see where their defenses are concentrated.
            # If they have many units in the front we can build a line for our demolishers to attack them at long range.
            if self.detect_enemy_unit(game_state, unit_type=None, valid_x=None, valid_y=[14, 15]) > 10:
                self.demolisher_line_strategy(game_state)
            else:
                # They don't have many units in the front so lets figure out their least defended area and send Scouts there.

                # Only spawn Scouts every other turn
                # Sending more at once is better since attacks can only hit a single scout at a time
                if game_state.turn_number % 2 == 1:
                    # To simplify we will just check sending them from back left and right
                    scout_spawn_location_options = [[10, 3], [17, 3]]
                    try:
                        best_location = self.least_damage_spawn_location(game_state, scout_spawn_location_options)
                        game_state.attempt_spawn(SCOUT, best_location, 1000)
                    except ValueError:
                        debug_write('could not find a path for spawning')

                # Lastly, if we have spare SP, let's build some Factories to generate more resources
                factory_locations = [[13, 2], [14, 2], [13, 3], [14, 3]]
                self.add_locations(factory_locations)

                game_state.attempt_spawn(FACTORY, factory_locations)

        # always try to use more resources
        self.upgrade_all(game_state)

    def add_locations(self, locations: List[List[int]]):
        for location in locations:
            self.all_locations.add(self.point_hash(location))

    def upgrade_all(self, game_state: GameState):
        for location_hash in self.all_locations:
            location = self.inv_point_hash(location_hash)
            if game_state.attempt_upgrade(location) == 0:
                break

    def attempt_spawn_refresh(self, game_state: GameState, unit_type, locations: List[List[int]], threshold=0.75):
        """
        Does the same thing as attempt_spawn, but will automatically sell and repurchase units below a health threshold
        """
        for location in locations:
            if len(game_state.game_map[location]):
                unit: GameUnit = game_state.game_map[location[0], location[1]][0]
                if unit.health <= int(unit.max_health * threshold):
                    game_state.attempt_remove(location)
                    game_state.attempt_spawn(unit_type, location)
                    if unit.upgraded:
                        game_state.attempt_upgrade(location)
                        debug_write("[DEBUG] replacing upgraded unit")
                    else:
                        debug_write("[DEBUG] replacing normal unit")
            else:
                game_state.attempt_spawn(unit_type, location)

    def point_hash(self, location: List[int]) -> int:
        """
        Since lists aren't hashable, this maps each point on the grid to a unique int, for adding to a collection
        """
        return 1 * location[0] + self.ARENA_SIZE * location[1]

    def inv_point_hash(self, hash: int):
        return [hash % self.ARENA_SIZE, hash // self.ARENA_SIZE]

    @property
    def construct_edge_set(self) -> Set[int]:
        ret = set()
        for x in range(14):
            ret.add(self.point_hash([x, 13 - x]))
            ret.add(self.point_hash([27 - x, 13 - x]))

        return ret

    def on_edge(self, location: List[int]):
        return self.point_hash(location) in self.edge_set

    def wall_surround(self, game_state: GameState, locations: List[List[int]]):
        new_locations = []
        for location in locations:
            new_locations += list(filter(
                # don't want to spawn walls where they could block mobile unit spawns, in most cases
                lambda entry: not self.on_edge(entry),
                [[location[0] + 1, location[1]], [location[0] - 1, location[1]], [location[0], location[1] + 1]]
            ))

        game_state.attempt_spawn(WALL, new_locations)

    def build_defences(self, game_state: GameState):
        """
        Build basic defenses using hardcoded locations.
        Remember to defend corners and avoid placing units in the front where enemy demolishers can attack them.
        """
        # Useful tool for setting up your base locations: https://www.kevinbai.design/terminal-map-maker
        # More community tools available at: https://terminal.c1games.com/rules#Download

        # Place turrets that attack enemy units
        turret_locations = [[3, 12], [24, 12], [8, 11], [19, 11], [13, 11], [14, 11]]
        self.add_locations(turret_locations)
        # attempt_spawn will try to spawn units if we have resources, and will check if a blocking unit is already there
        self.attempt_spawn_refresh(game_state, TURRET, turret_locations)
        game_state.attempt_upgrade([[3, 12], [24, 12]])
        self.wall_surround(game_state, turret_locations)
        
        # Place walls in front of turrets to soak up damage for them
        wall_locations = [[0, 13], [1, 13], [1, 12], [27, 13], [26, 13], [26, 12]]
        self.add_locations(wall_locations)
        game_state.attempt_spawn(WALL, wall_locations)

        factory_locations = [[13, 0], [14, 0]]
        self.add_locations(factory_locations)
        self.attempt_spawn_refresh(game_state, FACTORY, factory_locations)

    def build_reactive_defense(self, game_state: GameState):
        """
        This function builds reactive defenses based on where the enemy scored on us from.
        We can track where the opponent scored by looking at events in action frames 
        as shown in the on_action_frame function
        """
        for location in self.scored_on_locations:
            # Build turret one space above so that it doesn't block our own edge spawn locations
            build_location = [location[0], location[1]+1]
            game_state.attempt_spawn(TURRET, build_location)

    def stall_with_interceptors(self, game_state: GameState):
        """
        Send out interceptors at random locations to defend our base from enemy moving units.
        """
        # We can spawn moving units on our edges so a list of all our edge locations
        friendly_edges = game_state.game_map.get_edge_locations(game_state.game_map.BOTTOM_LEFT) + game_state.game_map.get_edge_locations(game_state.game_map.BOTTOM_RIGHT)
        
        # Remove locations that are blocked by our own structures 
        # since we can't deploy units there.
        deploy_locations = self.filter_blocked_locations(friendly_edges, game_state)
        
        # While we have remaining MP to spend lets send out interceptors randomly.
        while game_state.get_resource(MP) >= game_state.type_cost(INTERCEPTOR)[MP] and len(deploy_locations) > 0:
            # Choose a random deploy location.
            deploy_index = random.randint(0, len(deploy_locations) - 1)
            deploy_location = deploy_locations[deploy_index]
            
            game_state.attempt_spawn(INTERCEPTOR, deploy_location)
            """
            We don't have to remove the location since multiple mobile 
            units can occupy the same space.
            """

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
        for breach in breaches:
            location = breach[0]
            unit_owner_self = True if breach[4] == 1 else False
            # When parsing the frame data directly, 
            # 1 is integer for yourself, 2 is opponent (StarterKit code uses 0, 1 as player_index instead)
            if not unit_owner_self:
                debug_write("[DEBUG] Got scored on at: {}".format(location))
                self.scored_on_locations.append(location)
                debug_write("[DEBUG] All locations: {}".format(self.scored_on_locations))


if __name__ == "__main__":
    algo = AlgoStrategy()
    algo.start()
