from poke_env.player import RandomPlayer
from poke_env.ps_client.account_configuration import AccountConfiguration
from poke_env.ps_client.server_configuration import ServerConfiguration
from poke_env.teambuilder.teambuilder import Teambuilder
import asyncio
import inspect
import argparse
import time

# ServerConfiguration for a local Showdown running on localhost:8000
SERVER_CONFIG = ServerConfiguration(
    websocket_url="ws://localhost:8000/showdown/websocket",
    authentication_url="https://play.pokemonshowdown.com/action.php?",
)

# Example Showdown-formatted team (human-readable). You can replace this with any
# valid Showdown team text (or a packed team string). Passing a string to the
# `team` parameter of `RandomPlayer` will wrap it into a ConstantTeambuilder.
SAMPLE_TEAM = """
Lucaninja (Lucario) @ Life Orb  
Ability: Protean  
Fusion: Greninja  
EVs: 252 SpA / 4 SpD / 252 Spe  
Timid Nature  
IVs: 0 Atk  
- Aura Sphere  
- Ice Beam  
- Dark Pulse  
- Water Shuriken  

Muzing (Muk) @ Black Sludge  
Ability: Levitate  
Fusion: Weezing  
EVs: 252 HP / 4 SpA / 252 SpD  
Calm Nature  
IVs: 0 Atk  
- Acid Spray  
- Flamethrower  
- Clear Smog  
- Pain Split  

Galletta (Gallade) @ Lum Berry  
Ability: Justified  
Fusion: Meloetta  
EVs: 80 HP / 252 Atk / 176 Spe  
Jolly Nature  
- Psycho Cut  
- Close Combat  
- Rock Slide  
- Protect  

Whimsikou (Whimsicott) @ Focus Sash  
Ability: Prankster  
Fusion: Raikou  
EVs: 100 HP / 252 SpA / 156 Spe  
Timid Nature  
- Beat Up  
- Tailwind  
- Encore  
- Volt Switch  

Chandelzone (Chandelure) @ Mental Herb  
Ability: Magnet Pull  
Fusion: Magnezone  
EVs: 252 HP / 252 SpA / 4 SpD  
Quiet Nature  
IVs: 0 Atk  
- Trick Room  
- Heat Wave  
- Thunderbolt  
- Protect  

Metanite (Metagross) @ Sitrus Berry  
Ability: Clear Body  
Fusion: Dragonite  
EVs: 252 HP / 252 Atk / 4 SpD  
Brave Nature  
- Meteor Mash  
- Earthquake  
- Tailwind  
- Protect  
"""

# Convert SAMPLE_TEAM (export format) to packed format once and reuse for both
# agents. Teambuilder.parse_showdown_team and join_team are used so conversion
# matches the library's behavior.
PACKED_SAMPLE_TEAM = (
    Teambuilder.join_team(Teambuilder.parse_showdown_team(SAMPLE_TEAM))
    if SAMPLE_TEAM.strip()
    else ""
)

print(f"DEBUG: Packed Team String:\n{PACKED_SAMPLE_TEAM}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=("auto", "accept", "queue"),
        default="auto",
        help=(
            "auto: run two agents against each other (default). "
            "accept: run a single agent and accept a human challenge. "
            "queue: run a single agent and queue for ladder games (gen8randombattle)."
        ),
    )
    parser.add_argument(
        "--n-battles", type=int, default=1, help="number of battles when relevant"
    )
    args = parser.parse_args()

    fmt = "gen9nationaldexgeneration9"

    # Provide AccountConfiguration instances (username and optional password)
    # AccountConfiguration is a NamedTuple(username, password)
    acct1 = AccountConfiguration("custom_bot", None)
    acct2 = AccountConfiguration("random_bot", None)

    p1 = RandomPlayer(
        account_configuration=acct1,
        battle_format=fmt,
        team=PACKED_SAMPLE_TEAM,
        server_configuration=SERVER_CONFIG,
    )

    p2 = None
    if args.mode == "auto":
        p2 = RandomPlayer(
            account_configuration=acct2,
            battle_format=fmt,
            team=PACKED_SAMPLE_TEAM,
            server_configuration=SERVER_CONFIG,
        )

    # How long (seconds) to wait before making each decision.
    # Increase this value to make battles run slower so they don't finish instantly
    # when running against a local fast server.
    DECISION_DELAY = 0.6

    def _add_decision_delay(player, delay: float):
        """Monkey-patch a player to await `delay` seconds before choosing moves/switches.

        This handles both sync and async implementations of the underlying methods.
        """

        # Wrap choose_move
        if hasattr(player, "choose_move"):
            orig_choose_move = player.choose_move

            async def _choose_move_delayed(battle):
                await asyncio.sleep(delay)
                choice = orig_choose_move(battle)
                if inspect.isawaitable(choice):
                    return await choice
                return choice

            player.choose_move = _choose_move_delayed

        # Wrap choose_switch (some players may not implement it explicitly)
        if hasattr(player, "choose_switch"):
            orig_choose_switch = player.choose_switch

            async def _choose_switch_delayed(battle):
                await asyncio.sleep(delay)
                choice = orig_choose_switch(battle)
                if inspect.isawaitable(choice):
                    return await choice
                return choice

            player.choose_switch = _choose_switch_delayed

    # Apply delay to players so games are paced
    _add_decision_delay(p1, DECISION_DELAY)
    if p2 is not None:
        _add_decision_delay(p2, DECISION_DELAY)

    try:
        # Run according to selected mode
        if args.mode == "auto":
            # battle_against is async; run it in the main thread event loop
            # p2 is created above when mode==auto, assert for static checkers
            assert p2 is not None
            asyncio.run(p1.battle_against(p2, n_battles=args.n_battles))
        elif args.mode == "accept":
            print(
                f"Waiting to accept a challenge. From your Showdown client, challenge the bot username: {p1.username}"
            )
            # Wait for a human to challenge the bot and accept one challenge
            asyncio.run(p1.accept_challenges(None, n_challenges=1))
        elif args.mode == "queue":
            print(f"Queueing for {fmt} ladder games as {p1.username}.")
            # Queue for ladder games (search ladder). Uses p1.ladder which will
            # call the underlying PSClient search function.
            asyncio.run(p1.ladder(n_games=args.n_battles))
        time.sleep(1)
    finally:
        # Stop the underlying PSClient listeners cleanly (async)
        try:
            asyncio.run(p1.ps_client.stop_listening())
        except Exception:
            pass
        try:
            if p2 is not None:
                asyncio.run(p2.ps_client.stop_listening())
        except Exception:
            pass


if __name__ == "__main__":
    main()
