from poke_env.player import RandomPlayer
from poke_env.ps_client.account_configuration import AccountConfiguration
from poke_env.ps_client.server_configuration import ServerConfiguration
import asyncio
import inspect
import time

# ServerConfiguration for a local Showdown running on localhost:8000
SERVER_CONFIG = ServerConfiguration(
    websocket_url="ws://localhost:8000/showdown/websocket",
    authentication_url="https://play.pokemonshowdown.com/action.php?",
)


def main():
    fmt = "gen9randombattle"

    # Provide AccountConfiguration instances (username and optional password)
    # AccountConfiguration is a NamedTuple(username, password)
    acct1 = AccountConfiguration("custom_bot", None)
    acct2 = AccountConfiguration("random_bot", None)

    p1 = RandomPlayer(
        account_configuration=acct1,
        battle_format=fmt,
        server_configuration=SERVER_CONFIG,
    )

    p2 = RandomPlayer(
        account_configuration=acct2,
        battle_format=fmt,
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

    # Apply delay to both players so games are paced
    _add_decision_delay(p1, DECISION_DELAY)
    _add_decision_delay(p2, DECISION_DELAY)

    try:
        # battle_against is async; run it in the main thread event loop
        asyncio.run(p1.battle_against(p2, n_battles=1))
        time.sleep(1)
    finally:
        # Stop the underlying PSClient listeners cleanly (async)
        try:
            asyncio.run(p1.ps_client.stop_listening())
        except Exception:
            pass
        try:
            asyncio.run(p2.ps_client.stop_listening())
        except Exception:
            pass


if __name__ == "__main__":
    main()
