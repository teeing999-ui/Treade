from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple

import logging
import asyncio

import config

logger = logging.getLogger(__name__)


class PositionSide(str, Enum):
    BUY = "Buy"
    SELL = "Sell"


class OrderStatus(str, Enum):
    PENDING = "Pending"
    FILLED = "Filled"
    CANCELLED = "Cancelled"


class AccountStatus(str, Enum):
    FREE = "FREE"
    BUSY = "BUSY"


@dataclass
class GridLevel:
    price: float
    max_positions: int = 1
    is_active_long: bool = False
    positions_count: int = 0

    def check_activation_threshold(self, current_price: float, threshold: float) -> bool:
        deviation = abs(current_price - self.price) / self.price
        return deviation >= threshold

    def can_open_position(self) -> bool:
        return self.positions_count < self.max_positions

    def open_position(self) -> None:
        self.positions_count += 1

    def close_position(self) -> None:
        if self.positions_count > 0:
            self.positions_count -= 1


@dataclass
class Position:
    symbol: str
    quantity: float
    entry_price: float
    level_price: float
    close_order_id: Optional[str] = None
    averaging_order_id: Optional[str] = None
    leverage: float = 1.0
    risk_zone: str = ""
    total_quantity: float = field(init=False)
    average_entry_price: float = field(init=False)
    is_averaged: bool = False
    is_averaged_by_volume: bool = False
    averaging_failed_insufficient_balance: bool = False
    last_averaging_alert_roi: Optional[float] = None

    def __post_init__(self) -> None:
        self.total_quantity = self.quantity
        self.average_entry_price = self.entry_price

    def calculate_breakeven_price(self) -> float:
        return self.average_entry_price

    def calculate_pnl(self, price: float) -> float:
        return (price - self.average_entry_price) * self.total_quantity

    def calculate_roi(self, price: float) -> float:
        if self.average_entry_price == 0:
            return 0.0
        return (price - self.average_entry_price) / self.average_entry_price

    def add_averaging(self, qty: float, price: float) -> None:
        total_cost = self.average_entry_price * self.total_quantity + price * qty
        self.total_quantity += qty
        self.average_entry_price = total_cost / self.total_quantity
        self.is_averaged = True

    def check_if_averaged_by_volume(self, base_volume: float) -> None:
        self.is_averaged_by_volume = self.entry_price * self.quantity > base_volume

    def should_send_averaging_alert(self, current_price: float, interval: float) -> bool:
        roi = self.calculate_roi(current_price) * 100
        if self.last_averaging_alert_roi is None:
            return True
        return abs(roi - self.last_averaging_alert_roi) >= interval

    def mark_averaging_alert_sent(self, current_price: float) -> None:
        self.last_averaging_alert_roi = self.calculate_roi(current_price) * 100


@dataclass
class Order:
    order_id: str
    symbol: str
    side: str
    order_type: str
    quantity: float
    price: float
    purpose: str
    account_id: str
    status: OrderStatus = OrderStatus.PENDING
    level_price: Optional[float] = None

    def mark_filled(self) -> None:
        self.status = OrderStatus.FILLED

    def mark_cancelled(self) -> None:
        self.status = OrderStatus.CANCELLED


@dataclass
class TradingAccount:
    account_id: str
    balance: float = 0.0
    status: AccountStatus = AccountStatus.FREE
    long_usdt_position: Optional[Position] = None

    def has_free_slot(self) -> bool:
        return self.long_usdt_position is None

    def open_position(self, position: Position) -> None:
        self.long_usdt_position = position
        self.status = AccountStatus.BUSY

    def close_position(self) -> None:
        self.long_usdt_position = None
        self.status = AccountStatus.FREE


class AccountQueue:
    def __init__(self) -> None:
        self.accounts: Dict[str, TradingAccount] = {}
        self.long_queue: List[TradingAccount] = []
        for account_id in config.ACCOUNT_IDS:
            account = TradingAccount(account_id)
            self.accounts[account_id] = account
            self.long_queue.append(account)

    def get_next_free_account(self, required_balance: float = 0) -> Optional[TradingAccount]:
        suitable = [a for a in self.long_queue if a.has_free_slot() and a.balance >= required_balance]
        if not suitable:
            return None
        best = max(suitable, key=lambda a: a.balance)
        self.long_queue.remove(best)
        return best

    def return_account_to_queue(self, account: TradingAccount) -> None:
        if account not in self.long_queue:
            self.long_queue.append(account)


class LevelManager:
    def __init__(self) -> None:
        self.levels: Dict[str, Dict[float, GridLevel]] = {}
        for idx, symbol in enumerate(config.SYMBOLS):
            grid_levels = config.GRID_LEVELS[idx]
            self.levels[symbol] = {price: GridLevel(price) for price in grid_levels}

    def initialize_levels(self, symbol: str, current_price: float) -> None:
        symbol_levels = self.levels[symbol]
        for level in symbol_levels.values():
            level.is_active_long = level.check_activation_threshold(current_price, config.LEVEL_ACTIVATION_THRESHOLD)

    def check_nearest_level_activation(self, symbol: str, current_price: float, grid_engine: GridEngine, is_level_occupied) -> Optional[float]:
        symbol_levels = self.levels[symbol]
        nearest_price: Optional[float] = None
        min_distance = float("inf")
        for price, level in symbol_levels.items():
            if price < current_price:
                distance = current_price - price
                if distance < min_distance:
                    min_distance = distance
                    nearest_price = price
        if nearest_price is None:
            return None
        level = symbol_levels[nearest_price]
        if not level.check_activation_threshold(current_price, config.LEVEL_ACTIVATION_THRESHOLD):
            return None
        has_order = any(
            o.purpose == "grid" and o.level_price and abs(o.level_price - nearest_price) < 0.01
            for o in grid_engine.state["active_orders"].values()
        )
        if has_order or level.positions_count >= level.max_positions or is_level_occupied(nearest_price, symbol):
            return None
        level.is_active_long = True
        return nearest_price

    def get_next_level_price(self, symbol: str, current_price: float) -> Optional[float]:
        levels = sorted(self.levels[symbol])
        for price in levels:
            if price > current_price:
                return price
        return None

    def can_open_position_on_level(self, symbol: str, price: float) -> bool:
        level = self.levels[symbol].get(price)
        return level.can_open_position() if level else False

    def get_level(self, symbol: str, price: float) -> Optional[GridLevel]:
        return self.levels[symbol].get(price)

    def get_nearest_level_activation_info(self, symbol: str, current_price: float) -> Any:
        symbol_levels = self.levels[symbol]
        nearest: Optional[Tuple[float, GridLevel]] = None
        min_distance = float("inf")
        for price, level in symbol_levels.items():
            if price < current_price:
                distance = current_price - price
                if distance < min_distance:
                    min_distance = distance
                    nearest = (price, level)
        if not nearest:
            return "Нет уровней ниже текущей цены"
        price, _ = nearest
        deviation = min_distance / price
        threshold = config.LEVEL_ACTIVATION_THRESHOLD
        return {
            "level": price,
            "distance": round(min_distance, 2),
            "deviation_percent": round(deviation * 100, 2),
            "threshold_percent": round(threshold * 100, 2),
            "activation_progress": f"{round(deviation / threshold * 100, 1)}%",
            "is_activated": deviation >= threshold,
            "status": "АКТИВИРОВАН" if deviation >= threshold else f"Нужно еще {round((threshold - deviation) * 100, 2)}%",
        }


class RiskZoneManager:
    def __init__(self) -> None:
        self.symbol_zones: Dict[str, Dict[str, float]] = {}
        for idx, symbol in enumerate(config.SYMBOLS):
            oversold = config.OVERSOLD_ZONE_BOUNDARIES[idx]
            overbought = config.OVERBOUGHT_ZONE_BOUNDARIES[idx]
            self.symbol_zones[symbol] = {
                "oversold_max": max(oversold),
                "overbought_min": min(overbought),
            }

    def get_risk_zone(self, symbol: str, price: float) -> str:
        zones = self.symbol_zones.get(symbol)
        if not zones:
            return "NEUTRAL"
        if price <= zones["oversold_max"]:
            return "OVERSOLD"
        if price >= zones["overbought_min"]:
            return "OVERBOUGHT"
        return "NEUTRAL"

    def get_leverage_for_zone(self, zone: str) -> float:
        if zone == "OVERSOLD":
            return config.OVERSOLD_ZONE_LEVERAGE
        if zone == "OVERBOUGHT":
            return config.OVERBOUGHT_ZONE_LEVERAGE
        return config.NEUTRAL_ZONE_LEVERAGE

    def get_volume_usdt_for_zone(self, zone: str) -> float:
        if zone == "OVERSOLD":
            return config.OVERSOLD_ZONE_VOLUME_USDT
        if zone == "OVERBOUGHT":
            return config.OVERBOUGHT_ZONE_VOLUME_USDT
        return config.NEUTRAL_ZONE_VOLUME_USDT

    def get_volume_for_level(self, symbol: str, price: float) -> float:
        zone = self.get_risk_zone(symbol, price)
        return self.get_volume_usdt_for_zone(zone)

    def get_level_config(self, symbol: str, price: float) -> Dict[str, Any]:
        zone = self.get_risk_zone(symbol, price)
        return {
            "risk_zone": zone,
            "leverage": self.get_leverage_for_zone(zone),
            "volume_usdt": self.get_volume_usdt_for_zone(zone),
        }

    def get_risk_zone_name(self, symbol: str, price: float) -> str:
        return self.get_risk_zone(symbol, price)


class GridEngine:
    def __init__(self) -> None:
        self.account_queue = AccountQueue()
        self.level_manager = LevelManager()
        self.risk_zone_manager = RiskZoneManager()
        self.state: Dict[str, Any] = {
            "current_prices": {},
            "active_orders": {},
            "order_account_mapping": {},
            "is_running": False,
        }
        self.telegram_bot = None
        self.exchange_manager = None

    def set_exchange_manager(self, exchange_manager: Any) -> None:
        self.exchange_manager = exchange_manager

    def set_telegram_bot(self, telegram_bot: Any) -> None:
        self.telegram_bot = telegram_bot

    async def initialize(self) -> None:
        if not self.exchange_manager:
            raise RuntimeError("Exchange manager не установлен")
        for account_id, account in self.account_queue.accounts.items():
            try:
                account.balance = await self.exchange_manager.get_account_balance(account_id)
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("Ошибка получения баланса аккаунта", {"account": account_id, "error": str(exc)})
                account.balance = 0
        for symbol in config.SYMBOLS:
            current_price = await self.exchange_manager.get_current_price(symbol)
            self.state["current_prices"][symbol] = current_price
            self.level_manager.initialize_levels(symbol, current_price)

    def calculate_quantity_from_usdt(self, usdt_amount: float, price: float) -> float:
        return float(f"{usdt_amount / price:.3f}")

    async def place_order_with_usdt_volume(self, account_id: str, symbol: str, side: str, usdt_volume: float, price: float, purpose: str, level_price: Optional[float] = None) -> Optional[str]:
        quantity = self.calculate_quantity_from_usdt(usdt_volume, price)
        if quantity <= 0:
            return None
        return await self.place_order(account_id, symbol, side, quantity, price, purpose, level_price)

    async def place_order(self, account_id: str, symbol: str, side: str, quantity: float, price: float, purpose: str, level_price: Optional[float] = None) -> Optional[str]:
        try:
            order_id = await self.exchange_manager.place_limit_order(account_id, symbol, side, quantity, price)
            order = Order(order_id, symbol, side, "Limit", quantity, price, purpose, account_id)
            order.level_price = level_price
            self.state["active_orders"][order_id] = order
            self.state["order_account_mapping"][order_id] = account_id
            logger.info("Ордер %s размещен", purpose)
            return order_id
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Ошибка размещения ордера %s", purpose)
            return None

    async def cancel_and_cleanup_order(self, order_id: str, symbol: str, account_id: str) -> bool:
        try:
            success = await self.exchange_manager.cancel_order(account_id, symbol, order_id)
            self.state["active_orders"].pop(order_id, None)
            self.state["order_account_mapping"].pop(order_id, None)
            if success:
                await asyncio.sleep(0.5)
                account = self.account_queue.accounts.get(account_id)
                if account:
                    account.balance = await self.exchange_manager.get_account_balance(account_id)
            return success
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Ошибка отмены ордера", {"orderId": order_id, "error": str(exc)})
            return False
    def find_position_by_order(self, order_id: str, order_type: str) -> Tuple[Optional[Position], Optional[TradingAccount]]:
        for account in self.account_queue.accounts.values():
            position = account.long_usdt_position
            if position:
                if order_type == "close" and position.close_order_id == order_id:
                    return position, account
                if order_type == "averaging" and position.averaging_order_id == order_id:
                    return position, account
        return None, None

    async def place_grid_orders(self) -> int:
        placed = 0
        for symbol in config.SYMBOLS:
            current_price = self.state["current_prices"].get(symbol)
            symbol_levels = self.level_manager.levels[symbol]
            active = []
            for price, level in symbol_levels.items():
                if level.is_active_long and level.can_open_position():
                    active.append((abs(price - current_price), price))
            active.sort()
            for _, price in active:
                level_cfg = self.risk_zone_manager.get_level_config(symbol, price)
                required_balance = level_cfg["volume_usdt"] / level_cfg["leverage"]
                account = self.account_queue.get_next_free_account(required_balance)
                if account:
                    can_place = await self.exchange_manager.can_place_order_on_account_with_position(account.account_id, symbol, None)
                    if can_place:
                        await self.set_leverage_for_risk_zone(account.account_id, symbol, level_cfg["leverage"])
                        order_id = await self.place_order_with_usdt_volume(account.account_id, symbol, "Buy", level_cfg["volume_usdt"], price, "grid", price)
                        if order_id:
                            placed += 1
        return placed

    async def check_filled_orders(self) -> None:
        filled: List[Order] = []
        for order_id, order in list(self.state["active_orders"].items()):
            status = await self.exchange_manager.check_order_status(order.account_id, order.symbol, order_id)
            if status.orderStatus == "Filled":
                order.mark_filled()
                filled.append(order)
                self.state["active_orders"].pop(order_id, None)
        for order in filled:
            await self.handle_order_fill(order)

    async def handle_order_fill(self, order: Order) -> None:
        if order.purpose == "grid":
            await self.handle_grid_order_fill(order)
        elif order.purpose == "close":
            await self.handle_close_order_fill(order)
        elif order.purpose == "averaging":
            await self.handle_averaging_order_fill(order)

    async def handle_grid_order_fill(self, order: Order) -> None:
        account = self.account_queue.accounts.get(order.account_id)
        if not account or account.long_usdt_position:
            return
        position = Position(order.symbol, order.quantity, order.price, order.level_price or order.price)
        level_cfg = self.risk_zone_manager.get_level_config(order.symbol, order.price)
        position.leverage = level_cfg["leverage"]
        position.risk_zone = level_cfg["risk_zone"]
        account.open_position(position)
        if order.level_price:
            level = self.level_manager.get_level(order.symbol, order.level_price)
            if level:
                level.open_position()
        await self.place_close_order(position, account)
        await self.place_averaging_order(position, account)
        await self.replace_grid_order(order.level_price or order.price, order.symbol)
        self.state["order_account_mapping"].pop(order.order_id, None)

    async def place_close_order(self, position: Position, account: TradingAccount) -> None:
        if config.PROFIT_CLOSE_MODE == "level":
            close_price = self.level_manager.get_next_level_price(position.symbol, position.entry_price) or position.calculate_breakeven_price()
        else:
            close_price = position.calculate_breakeven_price()
        order_id = await self.place_order(account.account_id, position.symbol, "Sell", position.quantity, close_price, "close")
        if order_id:
            position.close_order_id = order_id

    async def place_averaging_order(self, position: Position, account: TradingAccount) -> None:
        averaging_price = position.entry_price * (1 - config.AVERAGING_PRICE_DROP_PERCENT / 100)
        pos_volume = position.quantity * position.entry_price
        averaging_volume = pos_volume * (config.AVERAGING_MULTIPLIER - 1)
        zone = self.risk_zone_manager.get_risk_zone(position.symbol, averaging_price)
        leverage = self.risk_zone_manager.get_leverage_for_zone(zone)
        required_balance = averaging_volume / leverage
        can_place = await self.exchange_manager.can_place_order_on_account_with_position(account.account_id, position.symbol, position)
        if not can_place or account.balance < required_balance:
            position.averaging_failed_insufficient_balance = True
            position.last_averaging_alert_roi = position.calculate_roi(self.state["current_prices"][position.symbol]) * 100
            return
        order_id = await self.place_order_with_usdt_volume(account.account_id, position.symbol, "Buy", averaging_volume, averaging_price, "averaging")
        if order_id:
            position.averaging_order_id = order_id

    async def replace_grid_order(self, level_price: float, symbol: str) -> None:
        level = self.level_manager.get_level(symbol, level_price)
        if not level or not level.can_open_position():
            return
        account = self.account_queue.get_next_free_account()
        if not account:
            return
        cfg = self.risk_zone_manager.get_level_config(symbol, level_price)
        await self.place_order_with_usdt_volume(account.account_id, symbol, "Buy", cfg["volume_usdt"], level_price, "grid", level_price)

    async def handle_close_order_fill(self, order: Order) -> None:
        position, account = self.find_position_by_order(order.order_id, "close")
        if not position or not account:
            return
        if position.averaging_order_id:
            await self.cancel_and_cleanup_order(position.averaging_order_id, position.symbol, account.account_id)
        level_price = position.level_price
        account.close_position()
        level = self.level_manager.get_level(position.symbol, level_price)
        if level:
            level.close_position()
        self.account_queue.return_account_to_queue(account)
        await self.place_new_grid_order_on_level(level_price, position.symbol)
        self.state["order_account_mapping"].pop(order.order_id, None)

    async def handle_averaging_order_fill(self, order: Order) -> None:
        position, account = self.find_position_by_order(order.order_id, "averaging")
        if not position or not account:
            return
        position.add_averaging(order.quantity, order.price)
        if position.close_order_id:
            await self.cancel_and_cleanup_order(position.close_order_id, position.symbol, account.account_id)
        await self.place_breakeven_close_order(position, account)
        self.state["order_account_mapping"].pop(order.order_id, None)

    async def place_breakeven_close_order(self, position: Position, account: TradingAccount) -> None:
        breakeven = position.calculate_breakeven_price()
        order_id = await self.place_order(account.account_id, position.symbol, "Sell", position.total_quantity, breakeven, "close")
        if order_id:
            position.close_order_id = order_id

    async def place_new_grid_order_on_level(self, level_price: float, symbol: str) -> None:
        level = self.level_manager.get_level(symbol, level_price)
        if not level:
            return
        level.is_active_long = True
        if not level.can_open_position():
            return
        account = self.account_queue.get_next_free_account()
        if not account:
            return
        cfg = self.risk_zone_manager.get_level_config(symbol, level_price)
        await self.place_order_with_usdt_volume(account.account_id, symbol, "Buy", cfg["volume_usdt"], level_price, "grid", level_price)

