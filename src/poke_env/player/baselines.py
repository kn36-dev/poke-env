import random
from typing import List, Tuple, cast, Optional, Union

from poke_env.battle.abstract_battle import AbstractBattle
from poke_env.battle.battle import Battle
from poke_env.battle.double_battle import DoubleBattle
from poke_env.battle.move import Move
from poke_env.battle.move_category import MoveCategory
from poke_env.battle.pokemon import Pokemon
from poke_env.battle.side_condition import SideCondition
from poke_env.battle.target import Target
from poke_env.player.battle_order import (
    BattleOrder,
    DefaultBattleOrder,
    DoubleBattleOrder,
    PassBattleOrder,
    SingleBattleOrder,
)
from poke_env.player.player import Player
from poke_env.battle.pokemon_type import PokemonType


class BaselinePlayer(Player):
    """
    A foundational class that handles the mechanical complexity of Singles vs Doubles.
    Subclasses only need to implement `get_move_score`.
    """

    def choose_move(self, battle: AbstractBattle) -> BattleOrder:
        if isinstance(battle, DoubleBattle):
            return self._choose_doubles_move(battle)
        elif isinstance(battle, Battle):
            return self._choose_singles_move(battle)
        else:
            return DefaultBattleOrder()

    def _choose_singles_move(self, battle: Battle) -> BattleOrder:
        if not battle.active_pokemon:
            return self.choose_random_move(battle)

        best_score = -float("inf")
        best_order = self.choose_random_move(battle)

        # Evaluate Switches
        if battle.available_switches:
            for switch_mon in battle.available_switches:
                score = self.get_switch_score(
                    battle,
                    switch_mon,
                    battle.active_pokemon,
                    battle.opponent_active_pokemon,
                )
                if score > best_score:
                    best_score = score
                    best_order = self.create_order(switch_mon)

        # Evaluate Moves
        if battle.available_moves and battle.opponent_active_pokemon:
            for move in battle.available_moves:
                score = self.get_move_score(
                    battle, move, battle.active_pokemon, battle.opponent_active_pokemon
                )
                if score > best_score:
                    best_score = score
                    best_order = self.create_order(move)

        return best_order

    def _choose_doubles_move(self, battle: DoubleBattle) -> BattleOrder:
        orders: List[Optional[BattleOrder]] = [None, None]

        # Iterate through both active pokemon (0 and 1)
        for i in range(2):
            attacker = battle.active_pokemon[i]
            if not attacker or attacker.fainted:
                orders[i] = DefaultBattleOrder()
                continue

            best_move_order = DefaultBattleOrder()
            best_score = -float("inf")

            # If no moves, try to switch
            if not battle.available_moves[i]:
                if battle.available_switches[i]:
                    best_switch = max(
                        battle.available_switches[i],
                        key=lambda p: p.current_hp_fraction,
                    )
                    orders[i] = self.create_order(best_switch)
                else:
                    orders[i] = DefaultBattleOrder()
                continue

            # Evaluate every move against every valid target
            for move in battle.available_moves[i]:
                # 1. Determine valid targets
                possible_targets = []

                # If move targets specific foe (normal single target moves)
                if move.target in {Target.NORMAL, Target.ANY, Target.ADJACENT_FOE}:
                    possible_targets = [
                        battle.opponent_active_pokemon[0],
                        battle.opponent_active_pokemon[1],
                    ]
                # If move targets all adjacent (Spread moves like Earthquake)
                elif move.target in {Target.ALL_ADJACENT, Target.ALL_ADJACENT_FOES}:
                    # We treat the "target" as the opponent slot 1 for API purposes, but calculate spread damage
                    possible_targets = [battle.opponent_active_pokemon[0]]

                for target in possible_targets:
                    if not target or target.fainted:
                        continue

                    # Calculate Score
                    current_score = self.get_move_score(battle, move, attacker, target)

                    # FRIENDLY FIRE CHECK
                    if move.target == Target.ALL_ADJACENT:
                        # This move (e.g., Earthquake) hits our partner too!
                        partner = battle.active_pokemon[1 if i == 0 else 0]
                        if partner and not partner.fainted:
                            # Estimate damage to partner
                            ff_damage = self.estimate_damage(
                                move, attacker, partner, battle
                            )
                            # Subtract massive penalty if it hurts partner significantly
                            current_score -= ff_damage * 1.5

                    if current_score > best_score:
                        best_score = current_score
                        # If targeting is required, specify it
                        if move.target in {
                            Target.NORMAL,
                            Target.ANY,
                            Target.ADJACENT_FOE,
                        }:
                            # Targets: 1, 2 are opponents. -1, -2 are allies.
                            # poke-env usually takes the target object or index.
                            # DoubleBattleOrder logic usually requires specifying target index explicitly.
                            # Standard poke-env: 1 is opp1, 2 is opp2.
                            target_idx = (
                                1 if target == battle.opponent_active_pokemon[0] else 2
                            )
                            best_move_order = self.create_order(
                                move, move_target=target_idx
                            )
                        else:
                            best_move_order = self.create_order(move)

            orders[i] = best_move_order

        # Combine into DoubleBattleOrder
        return DoubleBattleOrder(
            cast(
                Union[SingleBattleOrder, DefaultBattleOrder],
                orders[0] or DefaultBattleOrder(),
            ),
            cast(
                Union[SingleBattleOrder, DefaultBattleOrder],
                orders[1] or DefaultBattleOrder(),
            ),
        )

    def _get_target_from_index(
        self, battle: DoubleBattle, idx: int
    ) -> Optional[Pokemon]:
        # Mapping: 1, 2 are opponents. -1, -2 are allies.
        if idx == 1:
            return battle.opponent_active_pokemon[0]
        if idx == 2:
            return battle.opponent_active_pokemon[1]
        if idx == -1:
            return battle.active_pokemon[1]
        if idx == -2:
            return battle.active_pokemon[0]
        return None

    def estimate_damage(
        self,
        move: Move,
        attacker: Pokemon,
        defender: Pokemon,
        battle: AbstractBattle,  # Add battle here
    ) -> float:
        """
        Robust damage estimation including OTS data (Items/Abilities).
        """
        if move.category == MoveCategory.STATUS:
            return 0.0

        # 1. Stats with Stat Changes
        # Psyshock Check: Uses SpA vs Def
        use_def_stat = "def"
        # Initialize atk with a default to satisfy the 'unbound' warning
        atk = 0.0

        if move.id == "bodypress":
            atk = attacker.stats["def"] or attacker.base_stats["def"]
            use_def_stat = "def"
        elif move.category == MoveCategory.SPECIAL:
            atk = attacker.stats["spa"] or attacker.base_stats["spa"]
            if move.id == "psyshock":
                use_def_stat = "def"
            else:
                use_def_stat = "spd"
        else:  # Physical
            atk = attacker.stats["atk"] or attacker.base_stats["atk"]
            use_def_stat = "def"

        defense = defender.stats[use_def_stat] or 1  # Avoid division by zero

        # 2. Ability Immunities (OTS Awareness)
        # Levitate Check
        if move.type == PokemonType.GROUND and defender.ability == "levitate":
            return 0.0
        # Flash Fire / Volt Absorb / etc.
        if move.type == PokemonType.FIRE and defender.ability == "flashfire":
            return 0.0
        if move.type == PokemonType.ELECTRIC and defender.ability in [
            "voltabsorb",
            "lightningrod",
            "motordrive",
        ]:
            return 0.0
        if move.type == PokemonType.WATER and defender.ability in [
            "waterabsorb",
            "stormdrain",
            "dryskin",
        ]:
            return 0.0
        # Wonder Guard
        if (
            defender.ability == "wonderguard"
            and defender.damage_multiplier(move.type) <= 1
        ):
            return 0.0

        # 3. Item Checks (OTS Awareness)
        item_bonus = 1.0
        if attacker.item == "lifeorb":
            item_bonus = 1.3
        elif attacker.item == "choiceband" and move.category == MoveCategory.PHYSICAL:
            item_bonus = 1.5
        elif attacker.item == "choicespecs" and move.category == MoveCategory.SPECIAL:
            item_bonus = 1.5

        # 4. Calculation
        base_power = move.base_power
        # Technician Boost
        if attacker.ability == "technician" and base_power <= 60:
            base_power *= 1.5

        # Standard Formula
        level_factor = (2 * attacker.level) / 5 + 2
        damage = ((level_factor * base_power * (atk / defense)) / 50 + 2) * 0.85

        # Modifiers
        stab = 1.5 if move.type in attacker.types else 1.0
        type_eff = defender.damage_multiplier(move.type)

        # Fixed Weather Modifiers logic
        weather_name = "none"
        if battle.weather:
            # Access weather name safely from the battle object passed in
            weather_name = next(iter(battle.weather)).name.lower()

        if "rain" in weather_name:
            if move.type == PokemonType.WATER:
                damage *= 1.5
            elif move.type == PokemonType.FIRE:
                damage *= 0.5
        elif "sun" in weather_name:
            if move.type == PokemonType.FIRE:
                damage *= 1.5
            elif move.type == PokemonType.WATER:
                damage *= 0.5

        return damage * stab * type_eff * item_bonus

    def get_move_score(
        self, battle: AbstractBattle, move: Move, attacker: Pokemon, defender: Pokemon
    ) -> float:
        raise NotImplementedError

    def get_switch_score(
        self,
        battle: AbstractBattle,
        switch_mon: Pokemon,
        active_mon: Pokemon,
        opponent: Optional[Pokemon],
    ) -> float:
        return -50.0


class RandomPlayer(Player):
    def choose_move(self, battle: AbstractBattle) -> BattleOrder:
        return self.choose_random_move(battle)


class MaxBasePowerPlayer(BaselinePlayer):
    def get_move_score(
        self, battle: AbstractBattle, move: Move, attacker: Pokemon, defender: Pokemon
    ) -> float:
        score = move.base_power

        # Refactor: Multiplier for type effectiveness
        # If type immunity exists (0x damage), score drops to 0.
        if defender:
            effectiveness = defender.damage_multiplier(move.type)
            score *= effectiveness

        # Boost spread moves in doubles
        if isinstance(battle, DoubleBattle):
            if move.target in {"allAdjacentFoes", "allAdjacent"}:
                score *= 1.5

        return score


class PseudoBattle(Battle):
    def __init__(self, battle: DoubleBattle, active_id: int, opp_id: int):
        self._active_pokemon = battle.active_pokemon[active_id]
        self._opponent_active_pokemon = battle.opponent_active_pokemon[opp_id]
        self._team = battle.team
        self._opponent_team = battle.opponent_team
        self._available_moves = battle.available_moves[active_id]
        self._available_switches = battle.available_switches[active_id]
        self._force_switch = battle.force_switch[active_id]
        self._trapped = battle.trapped[active_id]
        self._wait = battle._wait
        self._side_conditions = battle.side_conditions
        self._opponent_side_conditions = battle.opponent_side_conditions
        self._can_mega_evolve = battle.can_mega_evolve[active_id]
        self._can_z_move = battle.can_z_move[active_id]
        self._can_dynamax = battle.can_dynamax[active_id]
        self._can_tera = battle.can_tera[active_id]

    @property
    def active_pokemon(self):
        return self._active_pokemon

    @property
    def opponent_active_pokemon(self):
        return self._opponent_active_pokemon


class SimpleHeuristicsPlayer(BaselinePlayer):
    """
    A port of the original SimpleHeuristics logic into the new BaselinePlayer structure.
    """

    ENTRY_HAZARDS = {
        "spikes": SideCondition.SPIKES,
        "stealthrock": SideCondition.STEALTH_ROCK,
        "stickyweb": SideCondition.STICKY_WEB,
        "toxicspikes": SideCondition.TOXIC_SPIKES,
    }
    ANTI_HAZARDS_MOVES = {"rapidspin", "defog"}

    def get_move_score(
        self, battle: AbstractBattle, move: Move, attacker: Pokemon, defender: Pokemon
    ) -> float:
        score = 0.0

        # 1. Hazard Logic
        if move.id in self.ENTRY_HAZARDS:
            if self.ENTRY_HAZARDS[move.id] not in battle.opponent_side_conditions:
                score += 200.0

        if move.id in self.ANTI_HAZARDS_MOVES:
            if battle.side_conditions:
                score += 200.0

        # 2. Setup Logic
        if move.category == MoveCategory.STATUS and move.boosts:
            if attacker.current_hp_fraction == 1.0:
                score += 150.0

        # 3. Offensive Logic
        if move.base_power > 0:
            # Physical/Special split estimation
            atk_stat = "atk" if move.category == MoveCategory.PHYSICAL else "spa"
            def_stat = "def" if move.category == MoveCategory.PHYSICAL else "spd"

            # Simple ratio of stats
            stat_ratio = attacker.base_stats[atk_stat] / (
                defender.base_stats[def_stat] if defender else 100
            )
            effectiveness = defender.damage_multiplier(move.type) if defender else 1.0
            accuracy = move.accuracy if move.accuracy is not True else 1.0

            damage_heuristic = move.base_power * stat_ratio * effectiveness * accuracy
            score += damage_heuristic

        return score


class AggressivePlayer(BaselinePlayer):
    """
    Focuses on maximizing immediate damage and securing KOs.
    Improvement: Uses actual damage formula estimation rather than just Base Power.
    """

    def get_move_score(
        self, battle: AbstractBattle, move: Move, attacker: Pokemon, defender: Pokemon
    ) -> float:
        # 1. Estimate Damage
        damage = self.estimate_damage(move, attacker, defender, battle)
        score = damage

        # Calculate percentage damage
        # We assume average bulk if we don't know exact HP
        # A standard pokemon has roughly 150-180 HP at level 50, 300-400 at level 100.
        # A safer check for "KO" is simply comparing relative damage.

        damage_absolute = self.estimate_damage(move, attacker, defender, battle)

        # We can't easily map absolute damage to HP fraction without knowing Max HP.
        # HEURISTIC: Assume average max HP based on level.
        level = defender.level or 100
        avg_hp = (defender.base_stats["hp"] * 2 * level / 100) + level + 10

        if damage_absolute >= (avg_hp * defender.current_hp_fraction):
            score += 1000.0

        # 3. Speed Bias
        # If we are faster and can hit hard, do it.
        # If we are slower and low HP, prioritize priority moves.
        my_speed = attacker.stats["spe"] or attacker.base_stats["spe"]
        opp_speed = defender.base_stats["spe"]

        if attacker.current_hp_fraction < 0.3 and my_speed < opp_speed:
            if move.priority > 0 and damage > 0:
                score += 500.0  # Desperation priority move

        # 4. Accuracy Penalty
        # Don't risk a 50% accuracy move unless it's the only way to win
        if move.accuracy is not True:
            score *= move.accuracy

        # 5. Status Move Penalty
        if move.category == MoveCategory.STATUS:
            # Only use status if it sets up a sweep (Swords Dance)
            if move.boosts and ("atk" in move.boosts or "spa" in move.boosts):
                score = 50.0  # Moderate score, lower than a good attack
            else:
                score = 0.0

        return score


class DefensivePlayer(BaselinePlayer):
    """
    Focuses on survival, stalling, and chip damage.
    Improvement: Checks immunities for status moves and switches out of bad matchups.
    """

    RECOVERY_MOVES = {
        "recover",
        "roost",
        "slackoff",
        "softboiled",
        "wish",
        "protect",
        "moonlight",
        "synthesis",
    }
    STATUS_MOVES = {
        "thunderwave",
        "willowisp",
        "toxic",
        "yawn",
        "hypnosis",
        "sleeppowder",
    }

    def get_switch_score(
        self,
        battle: AbstractBattle,
        switch_mon: Pokemon,
        active_mon: Pokemon,
        opponent: Optional[Pokemon],
    ) -> float:
        # If active pokemon is about to die or type disadvantaged, switch
        if not opponent:
            return -50.0

        # Check current matchup
        # If opponent has a move that is 4x effective against us
        # Note: We can't see opponent moves easily, so we check Type Matchup of opponent types vs our types
        defensive_multiplier = 1.0
        for type_ in opponent.types:
            defensive_multiplier *= active_mon.damage_multiplier(type_)

        if defensive_multiplier >= 2.0:
            # We are weak to them. Check if switch_mon is better.
            switch_def_mult = 1.0
            for type_ in opponent.types:
                switch_def_mult *= switch_mon.damage_multiplier(type_)

            if switch_def_mult < defensive_multiplier:
                return 200.0  # High priority to switch to a resist

        return -50.0

    def get_move_score(
        self, battle: AbstractBattle, move: Move, attacker: Pokemon, defender: Pokemon
    ) -> float:
        score = 0.0

        # 1. Recovery Logic
        if move.id in self.RECOVERY_MOVES:
            hp = attacker.current_hp_fraction
            if hp < 0.3:
                return 2000.0  # Critical range
            if hp < 0.7:
                return 500.0  # Maintenance
            return -10.0  # Don't heal if full

        # 2. Status Logic (Smart)
        if move.id in self.STATUS_MOVES:
            if not defender or defender.status is not None:
                return -50.0  # Don't status again

            # Type Immunities check
            if (
                move.type == PokemonType.ELECTRIC
                and PokemonType.GROUND in defender.types
            ):
                return -50.0
            if move.type == PokemonType.POISON and (
                PokemonType.STEEL in defender.types
                or PokemonType.POISON in defender.types
            ):
                return -50.0
            if move.id == "willowisp" and PokemonType.FIRE in defender.types:
                return -50.0
            if move.type == PokemonType.GRASS and PokemonType.GRASS in defender.types:
                return -50.0
            if move.id == "protect":

                # Check if we used protect last turn (requires tracking state,
                # but simpler heuristic: don't use if high HP)
                if attacker.current_hp_fraction > 0.9:
                    return (
                        -50.0
                    )  # Don't protect if full HP (stalling usually requires toxic/burn)
                # If we could track last_move, we would add that here.
                # Without state tracking, at least lower the score so it's not 2000.0 always.
                return 100.0

            return 300.0

        # 3. Chip Damage (Attacking)
        if move.base_power > 0:
            damage = self.estimate_damage(move, attacker, defender, battle)
            # Defensive players prefer reliable damage over high risk
            score = damage * (
                move.accuracy if isinstance(move.accuracy, float) else 1.0
            )

            # Bonus for draining moves
            if "drain" in move.id or move.id in [
                "gigadrain",
                "drainpunch",
                "hornleech",
            ]:
                score *= 1.5

        return score


class SetupSweeperPlayer(BaselinePlayer):
    """
    NEW PLAYER TYPE: Setup Sweeper.
    Prioritizes boosting stats early, then sweeping with high damage moves.
    """

    SETUP_MOVES = {
        "swordsdance",
        "nastyplot",
        "dragondance",
        "quiverdance",
        "calmmind",
        "shellsmash",
        "curse",
        "bulkup",
    }

    def get_move_score(
        self, battle: AbstractBattle, move: Move, attacker: Pokemon, defender: Pokemon
    ) -> float:
        score = 0.0

        # 1. Setup Logic
        # Boost if healthy and not already boosted too high
        is_boosted = sum(val for key, val in attacker.boosts.items() if val > 0) >= 2

        if move.id in self.SETUP_MOVES:
            if attacker.current_hp_fraction > 0.6 and not is_boosted:
                return 1000.0  # Top priority
            return 0.0

        # 2. Attack Logic
        if move.base_power > 0:
            damage = self.estimate_damage(move, attacker, defender, battle)
            score = damage

            # If we are boosted, we really want to attack
            if is_boosted:
                score *= 1.5

        return score


class SpeedControlPlayer(BaselinePlayer):
    """
    NEW PLAYER TYPE: Speed Control (Doubles Specialist).
    Prioritizes Trick Room, Tailwind, or Icy Wind to control turn order.
    """

    SPEED_MOVES = {"trickroom", "tailwind", "icywind", "electroweb", "stringshot"}

    def get_move_score(
        self, battle: AbstractBattle, move: Move, attacker: Pokemon, defender: Pokemon
    ) -> float:
        score = 0.0

        # 1. Field Control
        if move.id == "trickroom":
            # Use TR if we are slow and it's not up
            field = getattr(battle, "field", None)
            trick_room_active = field.trick_room_is_active if field else False

            if not trick_room_active and attacker.base_stats["spe"] < 80:
                return 2000.0
            return -100.0

        if move.id == "tailwind":
            if "tailwind" not in battle.side_conditions:
                return 2000.0
            return -100.0

        # 2. Speed Dropping Moves
        if move.id in ["icywind", "electroweb"]:
            return 500.0  # Good spread spam in doubles

        # 3. Fallback to Damage
        if move.base_power > 0:
            return self.estimate_damage(move, attacker, defender, battle)

        return score


class WeatherWarriorPlayer(BaselinePlayer):
    WEATHER_MOVES = {"raindance", "sunnyday", "sandstorm", "hail", "snowscape"}
    WEATHER_ABILITIES = {"drizzle", "drought", "sandstream", "snowwarning"}

    def get_move_score(
        self, battle: AbstractBattle, move: Move, attacker: Pokemon, defender: Pokemon
    ) -> float:
        score = 0.0

        # We take the first key from the dictionary if it exists
        current_weather = next(iter(battle.weather)).name if battle.weather else "NONE"

        # If we have a weather move and weather is not ours/neutral, prioritize setting it
        if move.id in self.WEATHER_MOVES:
            # Assuming we want Rain if we have Rain Dance
            wanted_weather = move.weather
            if current_weather != wanted_weather:
                return 500.0

        # 2. Weather Exploitation
        damage = self.estimate_damage(move, attacker, defender, battle)

        if "rain" in current_weather.lower():
            if move.type == PokemonType.WATER:
                damage *= 1.5
            elif move.type == PokemonType.FIRE:
                damage *= 0.5
            if move.id == "thunder":
                damage *= 1.3  # Accuracy boost bonus

        elif "sun" in current_weather.lower():
            if move.type == PokemonType.FIRE:
                damage *= 1.5
            elif move.type == PokemonType.WATER:
                damage *= 0.5
            if move.id == "solarbeam":
                damage *= 1.5  # No charge turn

        return damage


class DisruptorPlayer(BaselinePlayer):
    DISRUPTION_MOVES = {"taunt", "encore", "disable", "torment", "yawn"}

    def get_move_score(
        self, battle: AbstractBattle, move: Move, attacker: Pokemon, defender: Pokemon
    ) -> float:
        score = 0.0

        if not defender:
            return 0.0

        # Priority: Disrupt first
        if move.id in self.DISRUPTION_MOVES:
            # Logic: Don't Taunt if already Taunted
            if move.id == "taunt" and "taunt" not in defender.effects:
                # Value Taunt highly against passive mons (Status moves known?)
                return 400.0

            if move.id == "encore":
                # Only Encore if they used a non-damaging or weak move last turn
                # Note: Poke-env might not easily track "last move used" without keeping state
                # But we can try randomly spamming it if we don't know
                if defender.status is None:
                    return 300.0

            if move.id == "yawn" and not defender.status:
                return 350.0

        # Fallback: Attack with STAB or Coverage
        damage = self.estimate_damage(move, attacker, defender, battle)
        return damage


class ChoiceTricksterPlayer(BaselinePlayer):
    TRICK_MOVES = {"trick", "switcheroo"}
    CHOICE_ITEMS = {"choiceband", "choicespecs", "choicescarf"}

    def get_move_score(
        self, battle: AbstractBattle, move: Move, attacker: Pokemon, defender: Pokemon
    ) -> float:
        # Check if we are holding a choice item and have Trick
        if move.id in self.TRICK_MOVES:
            if attacker.item in self.CHOICE_ITEMS:
                # If opponent is NOT holding a choice item or crystal
                # And opponent seems defensive (low offensive stats or used status moves)
                if defender.item not in self.CHOICE_ITEMS and "z" not in str(
                    defender.item
                ):
                    return 1000.0  # High Priority to cripple walls

        return self.estimate_damage(move, attacker, defender, battle)
