from poke_env.player import (
    RandomPlayer,
    MaxBasePowerPlayer,
    SimpleHeuristicsPlayer,
    AggressivePlayer,
    DefensivePlayer,
    SetupSweeperPlayer,
    SpeedControlPlayer,
    WeatherWarriorPlayer,
    DisruptorPlayer,
    ChoiceTricksterPlayer,
)
from poke_env.ps_client.account_configuration import AccountConfiguration
from poke_env.ps_client.server_configuration import ServerConfiguration
from poke_env.teambuilder.teambuilder import Teambuilder
import asyncio
import inspect
import argparse
import time
import random
from typing import List

from teams_config import ALL_TEAMS

# ServerConfiguration for a local Showdown running on localhost:8000
SERVER_CONFIG = ServerConfiguration(
    websocket_url="ws://localhost:8000/showdown/websocket",
    authentication_url="https://play.pokemonshowdown.com/action.php?",
)


class RandomTeambuilder(Teambuilder):
    def __init__(self, teams: List[str]):
        # Convert all human-readable teams to packed format once at startup
        self.packed_teams = [
            self.join_team(self.parse_showdown_team(t)) for t in teams if t.strip()
        ]

    def yield_team(self) -> str:
        # This is called by the Player object every time a new battle starts
        return random.choice(self.packed_teams)


# print(f"DEBUG: Packed Team String:\n{PACKED_SAMPLE_TEAM}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=("auto", "accept", "queue"),
        default="auto",
        help=(
            "auto: run two agents against each other (default). "
            "accept: run a single agent and accept a human challenge. "
            "queue: run a single agent and queue for ladder games (gen9nationaldexgeneration9)."
        ),
    )
    parser.add_argument(
        "--n-battles", type=int, default=1, help="number of battles when relevant"
    )
    args = parser.parse_args()

    player_types = [
        RandomPlayer,
        MaxBasePowerPlayer,
        SimpleHeuristicsPlayer,
        AggressivePlayer,
        DefensivePlayer,
        SetupSweeperPlayer,
        SpeedControlPlayer,
        WeatherWarriorPlayer,
        DisruptorPlayer,
        ChoiceTricksterPlayer,
    ]

    fmt = "gen9nationaldexgeneration9vgc"

    # Provide AccountConfiguration instances (username and optional password)
    # AccountConfiguration is a NamedTuple(username, password)
    acct1 = AccountConfiguration("custom_bot", None)
    acct2 = AccountConfiguration("random_bot", None)

    teambuilder = RandomTeambuilder(ALL_TEAMS)

    p1_class = random.choice(player_types)
    p2_class = random.choice(player_types)

    p1 = p1_class(
        account_configuration=acct1,
        battle_format=fmt,
        team=teambuilder,
        server_configuration=SERVER_CONFIG,
    )

    p2 = None
    if args.mode == "auto":
        p2 = p2_class(
            account_configuration=acct2,
            battle_format=fmt,
            team=teambuilder,
            server_configuration=SERVER_CONFIG,
        )

    # print(f"Matchup: {p1_class.__name__} vs {p2_class.__name__}")
    print(f"Matchup: {p1_class.__name__}")

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
