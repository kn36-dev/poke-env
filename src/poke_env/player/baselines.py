import math
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
        # Check if this is a force-switch turn (e.g., after a KO)
        is_force_switch = any(battle.force_switch)
        orders: List[Optional[BattleOrder]] = [None, None]

        # Iterate through both active pokemon (0 and 1)
        for i in range(2):
            attacker = battle.active_pokemon[i]
            if not attacker or attacker.fainted:
                orders[i] = DefaultBattleOrder()
                continue

            # 2. Handle Force-Switch Phase
            if is_force_switch:
                if battle.force_switch[i]:
                    # This slot MUST switch
                    if battle.available_switches[i]:
                        best_switch = max(
                            battle.available_switches[i],
                            key=lambda p: p.current_hp_fraction,
                        )
                        orders[i] = self.create_order(best_switch)
                    else:
                        orders[i] = DefaultBattleOrder()
                else:
                    orders[i] = PassBattleOrder()
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

                # TARGET: NORMAL / ANY / ADJACENT_FOE
                if move.target in {Target.NORMAL, Target.ANY, Target.ADJACENT_FOE}:
                    possible_targets = [
                        battle.opponent_active_pokemon[0],
                        battle.opponent_active_pokemon[1],
                    ]
                # TARGET: SPREAD (All Foes)
                elif move.target in {Target.ALL_ADJACENT, Target.ALL_ADJACENT_FOES}:
                    # Score based on hitting the first available opponent,
                    # damage calculation handles spread logic implicitly by checking type matchups later if needed
                    possible_targets = [
                        op for op in battle.opponent_active_pokemon if op is not None
                    ]

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
                            # In Double Battles, target is 1 or 2 (Opponents), -1 or -2 (Allies)
                            # battle.opponent_active_pokemon[0] -> Target 1
                            # battle.opponent_active_pokemon[1] -> Target 2
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

    def calculate_stat(self, pokemon: Pokemon, stat_name: str, level: int = 50) -> int:
        """
        Calculates the approximate stat of a Pokemon based on Base Stats.
        Assumes 31 IVs and 85 EVs (neutral spread) for robustness.
        Rounds DOWN strictly.
        """
        base = pokemon.base_stats.get(stat_name, 100)

        # HP Formula: floor((2 * Base + IV + floor(EV/4)) * Level / 100) + Level + 10
        # Stat Formula: floor((floor((2 * Base + IV + floor(EV/4)) * Level / 100) + 5) * Nature)
        # Assuming Neutral Nature (1.0) and generic EVs (85) for un-scouted mons.

        ev_calc = math.floor(85 / 4)  # 21
        common_term = math.floor((2 * base + 31 + ev_calc) * level / 100)

        if stat_name == "hp":
            return common_term + level + 10
        else:
            return common_term + 5

    def estimate_damage(
        self, move: Move, attacker: Pokemon, defender: Pokemon, battle: AbstractBattle
    ) -> float:
        """
        Robust damage estimation with strict floor rounding.
        Handles Teampreview state (where stats are missing) by calculating them.
        """
        if move.category == MoveCategory.STATUS:
            return 0.0

        # Determine if we are in Team Preview (no active turns) or Battle
        # If attacker.stats is empty/None, we calculate manually.
        use_manual_stats = not attacker.stats or not attacker.stats.get("atk")

        # 1. Determine Attack and Defense Stats
        atk_stat_name = "atk"
        def_stat_name = "def"

        if move.id == "bodypress":
            atk_stat_name = "def"
            def_stat_name = "def"
        elif move.category == MoveCategory.SPECIAL:
            atk_stat_name = "spa"
            if move.id == "psyshock":
                def_stat_name = "def"
            else:
                def_stat_name = "spd"

        if use_manual_stats:
            atk = self.calculate_stat(attacker, atk_stat_name, attacker.level)
            defense = self.calculate_stat(defender, def_stat_name, defender.level)
        else:
            atk = attacker.stats[atk_stat_name] or self.calculate_stat(
                attacker, atk_stat_name, attacker.level
            )
            defense = defender.stats[def_stat_name] or self.calculate_stat(
                defender, def_stat_name, defender.level
            )

        if defense == 0:
            defense = 1  # Safety

        # 2. Ability Immunities
        if move.type == PokemonType.GROUND and defender.ability == "levitate":
            return 0.0
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

        # 3. Item Checks
        item_bonus = 1.0
        if attacker.item == "lifeorb":
            item_bonus = 1.3
        elif attacker.item == "choiceband" and move.category == MoveCategory.PHYSICAL:
            item_bonus = 1.5
        elif attacker.item == "choicespecs" and move.category == MoveCategory.SPECIAL:
            item_bonus = 1.5

        # 4. Base Calculation
        base_power = move.base_power
        if attacker.ability == "technician" and base_power <= 60:
            base_power = math.floor(base_power * 1.5)

        level_factor = math.floor((2 * attacker.level) / 5) + 2

        # Damage Formula: floor(floor(floor(2 * L / 5 + 2) * BP * A / D) / 50) + 2

        # Step 1: Base Damage
        base_damage = (
            math.floor(math.floor(level_factor * base_power * atk / defense) / 50) + 2
        )

        # Step 2: Modifiers (STAB, Weather, Type)
        # Note: In real games, these are chained with flooring.
        # For estimation, we chain floats but floor the final result is usually enough,
        # but to be strict with your rule:

        damage = base_damage * 0.85  # Low roll estimation

        if move.type in attacker.types:
            damage = damage * 1.5  # STAB

        damage = damage * defender.damage_multiplier(move.type)  # Type Effectiveness

        # Weather
        weather_name = (
            next(iter(battle.weather)).name.lower() if battle.weather else "none"
        )
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

        damage = damage * item_bonus

        return math.floor(damage)

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

    def teampreview(self, battle: AbstractBattle) -> str:
        """
        Advanced VGC Teampreview Logic.
        1. Identifies if Opponent Team is known (Open Team Sheet).
        2. Calculates Matchups based on Base Stats (calculated to Lvl 50).
        3. Prioritizes Leads (Slots 1 & 2) separately from Backline.
        """
        my_team = list(battle.team.values())
        opp_team = list(battle.opponent_team.values())

        # If opponent team is hidden (Closed Team Sheet early on), fallback to power heuristic
        if not opp_team:
            # Sort by simply highest base stat total or offensive stats
            sorted_team = sorted(
                range(len(my_team)),
                key=lambda i: my_team[i].base_stats["atk"]
                + my_team[i].base_stats["spa"]
                + my_team[i].base_stats["spe"],
                reverse=True,
            )
            return "/team " + "".join(map(str, [i + 1 for i in sorted_team]))

        # Calculate Scores
        mon_scores = []
        for i, my_mon in enumerate(my_team):
            lead_score = 0.0
            back_score = 0.0

            # Calculate stats manually for teampreview (Level 50 standard)
            my_speed = self.calculate_stat(my_mon, "spe", 50)

            for opp_mon in opp_team:
                opp_speed = self.calculate_stat(opp_mon, "spe", 50)

                # Offensive Potential
                best_dmg = 0
                for move in my_mon.moves.values():
                    # Use estimate_damage which handles 'teampreview' stats calculation internally now
                    dmg = self.estimate_damage(move, my_mon, opp_mon, battle)
                    if dmg > best_dmg:
                        best_dmg = dmg

                # Scoring Logic
                # Lead Score: Favors Speed and OHKO potential
                if my_speed > opp_speed:
                    lead_score += best_dmg * 1.2  # Bonus for being faster
                else:
                    lead_score += best_dmg * 0.8  # Penalty for being slower

                # Back Score: Favors Bulk and Type Matchup (Defensive)
                # Simple defense heuristic: do I resist their types?
                defensive_mult = 1.0
                for type_ in opp_mon.types:
                    defensive_mult *= my_mon.damage_multiplier(type_)

                if defensive_mult < 1.0:  # Resist
                    back_score += 200
                elif defensive_mult > 1.5:  # Weak
                    back_score -= 200

                back_score += best_dmg  # Damage still matters in back

            mon_scores.append(
                {
                    "index": i + 1,
                    "mon": my_mon,
                    "lead_score": lead_score,
                    "back_score": back_score,
                }
            )

        # Selection Logic
        # 1. Pick Top 2 Leads
        mon_scores.sort(key=lambda x: x["lead_score"], reverse=True)
        leads = [mon_scores[0], mon_scores[1]]

        # 2. Pick Top 2 Back from the remaining
        remaining = mon_scores[2:]
        remaining.sort(key=lambda x: x["back_score"], reverse=True)
        back = [remaining[0], remaining[1]]

        # 3. The last 2 are bench (for 6v6 they go last, for VGC they stay home)
        bench = remaining[2:]

        final_order = [x["index"] for x in leads + back + bench]

        return "/team " + "".join(map(str, final_order))


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
