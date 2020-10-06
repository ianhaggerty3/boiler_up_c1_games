from gamelib import debug_write, GameState, GameUnit
from typing import Dict, List, Set, Union


class Utility:
    ARENA_SIZE: int

    action_queue: List[Dict[str, Union[str, bool, List[List[int]]]]]
    all_defenses: List[int]
    change_flag: bool

    def __init__(self):
        self.ARENA_SIZE = 28

        self.action_queue = []
        self.all_defenses = []
        self.edge_set = self.construct_edge_set
        self.change_flag = False

    def append_action(self, id: str, unit_type: str,
                      locations: Union[List[int], List[List[int]]], upgrade=False) -> None:
        """
        Appends an action to the to the end of the priority queue
        """
        index = -1
        for i, entry in enumerate(self.action_queue):
            if entry['id'] == id:
                index = i
                break

        if index != -1:
            debug_write("[DEBUG] cannot append existing action:", id)
            return

        self.change_flag = True
        location_list = [locations] if type(locations[0]) is int else locations
        action_object = {'id': id, 'unit_type': unit_type, 'locations': location_list, 'upgrade': upgrade}
        self.action_queue.append(action_object)

    def prioritize_action(self, id: str) -> None:
        """
        Moves an action to the front of the priority queue by id
        """
        index = -1
        for i, entry in enumerate(self.action_queue):
            if entry['id'] == id:
                index = i
                break

        if index == -1:
            debug_write("[DEBUG] cannot prioritize nonexistant action:", id)
            raise ValueError('Cannot prioritize nonexistant action')

        self.change_flag = True
        value = self.action_queue.pop(index)
        self.action_queue.insert(0, value)

    def remove_action(self, id: str) -> None:
        """
        Removes an action from the priority queue by id
        """
        index = -1
        for i, entry in enumerate(self.action_queue):
            if entry['id'] == id:
                index = i
                break

        if index == -1:
            debug_write("[DEBUG] cannot remove nonexistant action:", id)
            raise ValueError('Cannot remove nonexistant action')

        self.change_flag = True
        remove_locations = self.action_queue[index].get('locations', [])
        for location in remove_locations:
            self.all_defenses.remove(self.point_hash(location))

        self.action_queue.pop(index)

    def attempt_actions(self, game_state: GameState):
        """
        Call on each turn to act on the finished action queue
        Takes care of adding the updated upgrade_all action
        """

        if self.change_flag:
            self.refresh_upgrade_all()

        for action in self.action_queue:
            if not action['upgrade']:
                game_state.attempt_spawn(action['unit_type'], action['locations'])
            else:
                game_state.attempt_upgrade(action['locations'])

    def refresh_upgrade_all(self):
        try:
            self.remove_action('upgrade_all')
        except ValueError:
            pass
        self.all_defenses = []
        for action in self.action_queue:
            if action['upgrade'] is True:
                continue
            self.all_defenses += action['locations']

        self.append_action('upgrade_all', '', self.all_defenses, upgrade=True)
        self.change_flag = False

    def point_hash(self, location: List[int]) -> int:
        """
        Since lists aren't hashable, this maps each point on the grid to a unique int, for adding to a collection
        """
        return 1 * location[0] + self.ARENA_SIZE * location[1]

    def inv_point_hash(self, hashed_location: int):
        return [hashed_location % self.ARENA_SIZE, hashed_location // self.ARENA_SIZE]

    @property
    def construct_edge_set(self) -> Set[int]:
        ret = set()
        for x in range(14):
            ret.add(self.point_hash([x, 13 - x]))
            ret.add(self.point_hash([27 - x, 13 - x]))

        return ret

    def on_edge(self, location: List[int]):
        return self.point_hash(location) in self.edge_set

