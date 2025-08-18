import asyncio
import os
import signal
import sys
from typing import Optional

from config import config  # type: ignore
from exchange import ExchangeManager  # type: ignore
from grid_engine import GridEngine  # type: ignore
from telegram import TelegramBotHandler as TelegramBot  # type: ignore
from logger import logger  # type: ignore

print("Starting Grid Bot...")
print("Current directory:", os.getcwd())
print("Python version:", sys.version)


class GridBotMain:
    """Main entry point for the Grid Bot system."""

    def __init__(self) -> None:
        self.is_running: bool = False
        self.exchange_manager: Optional[ExchangeManager] = None
        self.grid_engine: Optional[GridEngine] = None
        self.telegram_bot: Optional[TelegramBot] = None

    async def initialize_system(self) -> None:
        """Initialise all system components."""
        try:
            logger.info("Starting Grid Bot system")
            config.validate_settings()
            logger.info("Configuration is valid")
            self.exchange_manager = ExchangeManager(config)
            await self.exchange_manager.initialize_all_accounts()
            logger.info("Exchange Manager initialised")
            self.telegram_bot = TelegramBot(config)
            await self.telegram_bot.initialize()
            logger.info("Telegram Bot initialised")
            self.grid_engine = GridEngine()
            self.grid_engine.set_exchange_manager(self.exchange_manager)
            self.grid_engine.set_telegram_bot(self.telegram_bot)
            await self.grid_engine.initialize()
            logger.info("Grid Engine initialised")
            self.telegram_bot.set_grid_engine(self.grid_engine)
            logger.info("All components initialised")
        except Exception as error:  # pragma: no cover - business logic
            logger.error(
                "System initialisation error", extra={"error": str(error)}
            )
            raise

    async def start_system(self) -> None:
        """Start trading system."""
        try:
            self.is_running = True
            if not self.grid_engine:
                raise RuntimeError("Grid engine is not initialised")
            await self.grid_engine.restore_state_from_exchange()
            logger.info("State restored from exchange")
            logger.info("Trading levels initialised")
            await self.grid_engine.place_grid_orders()
            logger.info("Initial grid orders placed")
            if self.telegram_bot:
                await self.telegram_bot.send_startup_notification()
            await self.run_main_loop()
        except Exception as error:  # pragma: no cover - business logic
            logger.error(
                "Trading system start error", extra={"error": str(error)}
            )
            if self.telegram_bot:
                await self.telegram_bot.send_error_notification(
                    "System Start", str(error)
                )
            raise

    async def run_main_loop(self) -> None:
        """Main trading loop."""
        logger.info("Starting main trading loop")
        while self.is_running and self.grid_engine:
            try:
                await self.grid_engine.run_trading_loop()
                await self.sleep(config.MAIN_LOOP_INTERVAL)
            except Exception as error:  # pragma: no cover - business logic
                logger.error(
                    "Trading cycle error", extra={"error": str(error)}
                )
                if self.telegram_bot:
                    await self.telegram_bot.send_error_notification(
                        "Trading Cycle", str(error)
                    )
                await self.sleep(config.ERROR_RETRY_INTERVAL)

    async def shutdown_system(self) -> None:
        """Shutdown the system gracefully."""
        logger.info("Shutting down system")
        self.is_running = False
        try:
            if self.grid_engine:
                await self.grid_engine.stop()
                logger.info("Grid Engine stopped")
            if self.telegram_bot:
                await self.telegram_bot.close()
                logger.info("Telegram Bot closed")
            if self.exchange_manager:
                await self.exchange_manager.close_all_connections()
                logger.info("Exchange connections closed")
            logger.info("System shutdown complete")
        except Exception as error:  # pragma: no cover - business logic
            logger.error(
                "System shutdown error", extra={"error": str(error)}
            )

    def setup_signal_handlers(self) -> None:
        """Register signal and exception handlers."""
        loop = asyncio.get_running_loop()

        async def signal_handler(name: str) -> None:
            logger.info("Received signal %s, shutting down", name)
            await self.shutdown_system()
            sys.exit(0)

        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            loop.add_signal_handler(
                sig, lambda s=sig: asyncio.create_task(signal_handler(s.name))
            )

        def handle_exception(
            loop: asyncio.AbstractEventLoop, context: dict
        ) -> None:  # pragma: no cover - callback
            error = context.get("exception")
            message = context.get("message")
            if error:
                logger.error(
                    "Uncaught exception", extra={"error": str(error)}
                )
                if self.telegram_bot:
                    loop.create_task(
                        self.telegram_bot.send_error_notification(
                            "Uncaught Exception", str(error)
                        )
                    )
                loop.create_task(self.shutdown_system())
                sys.exit(1)
            else:
                logger.error(
                    "Unhandled rejection", extra={"reason": message}
                )
                if self.telegram_bot:
                    loop.create_task(
                        self.telegram_bot.send_error_notification(
                            "Unhandled Rejection", message or ""
                        )
                    )

        loop.set_exception_handler(handle_exception)

    async def sleep(self, ms: int) -> None:
        """Pause execution for the specified milliseconds."""
        await asyncio.sleep(ms / 1000)


async def main() -> None:
    bot = GridBotMain()
    bot.setup_signal_handlers()
    try:
        await bot.initialize_system()
        await bot.start_system()
    except Exception as error:  # pragma: no cover - business logic
        logger.error("Critical error in main", extra={"error": str(error)})
        print(f"Critical error: {error}")
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:  # pragma: no cover - entry point
        print(f"Fatal error: {error}")
        sys.exit(1)
