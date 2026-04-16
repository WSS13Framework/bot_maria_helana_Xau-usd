import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from dotenv import dotenv_values
from metaapi_cloud_sdk import MetaApi

DATA_DIR = Path("/root/maria-helena/data")
DEFAULT_ENV_PATH = Path("/root/maria-helena/.env")
DEFAULT_FEATURE_INPUT = DATA_DIR / "xauusd_feature_table.csv"
DEFAULT_LABELED_INPUT = DATA_DIR / "xauusd_labeled_dataset.csv"
DEFAULT_LOG_PATH = DATA_DIR / "position_manager_log.jsonl"


def _append_log(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _classify_account(name: str) -> str:
    lower_name = name.lower()
    if "demo" in lower_name:
        return "demo"
    if "live" in lower_name or "real" in lower_name:
        return "live"
    return "unknown"


def _load_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["time"] = pd.to_datetime(frame["time"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)
    return frame


def _feature_columns(frame: pd.DataFrame) -> list[str]:
    excluded = {
        "time",
        "tb_label",
        "tb_hit_bars",
        "future_up_atr",
        "future_down_atr",
        "rr_observed",
        "rr_viable",
        "trade_label",
        "long_target",
        "short_target",
    }
    numeric_columns = frame.select_dtypes(include=[np.number]).columns
    return [column for column in numeric_columns if column not in excluded]


def _prepare_training_targets(labeled: pd.DataFrame) -> pd.DataFrame:
    train = labeled.copy()
    train = train.dropna(subset=["atr", "future_up_atr", "future_down_atr"])
    train["long_target"] = ((train["tb_label"] == 1) & (train["rr_viable"] == 1)).astype(int)
    train["short_target"] = ((train["tb_label"] == -1) & (train["rr_viable"] == 1)).astype(int)
    return train


def _fit_predict_probability(
    x_train: pd.DataFrame,
    y_train: pd.Series,
    x_live: pd.DataFrame,
) -> float:
    if y_train.nunique() < 2:
        return 0.0
    model = CatBoostClassifier(
        loss_function="Logloss",
        eval_metric="AUC",
        iterations=500,
        learning_rate=0.03,
        depth=6,
        l2_leaf_reg=5.0,
        random_strength=0.5,
        subsample=0.8,
        bootstrap_type="Bernoulli",
        random_state=42,
        verbose=False,
    )
    model.fit(x_train, y_train)
    return float(model.predict_proba(x_live)[:, 1][0])


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


async def run_manager(args: argparse.Namespace) -> None:
    cfg = dotenv_values(args.env_file)
    token = (cfg.get("METAAPI_TOKEN") or "").strip()
    account_id = (args.account_id or cfg.get("METAAPI_DEMO_ACCOUNT_ID") or "").strip()
    if not token:
        raise ValueError("METAAPI_TOKEN não encontrado no .env")
    if not account_id:
        raise ValueError("account_id ausente. Use --account-id ou METAAPI_DEMO_ACCOUNT_ID no .env")

    feature_frame = _load_frame(args.feature_input)
    labeled_frame = _load_frame(args.labeled_input)
    train_frame = _prepare_training_targets(labeled_frame)
    if len(train_frame) < args.min_train_rows:
        raise ValueError(
            f"Amostra de treino insuficiente ({len(train_frame)}). "
            f"Necessário >= {args.min_train_rows}"
        )

    train_features = _feature_columns(train_frame)
    live_features = _feature_columns(feature_frame)
    features = [col for col in train_features if col in live_features]
    if not features:
        raise ValueError("Nenhuma feature comum entre treino e feature table.")

    x_train = train_frame[features].copy().ffill().bfill().fillna(0.0)
    x_live = feature_frame[features].copy().ffill().bfill().fillna(0.0).iloc[[-1]]
    p_long = _fit_predict_probability(x_train, train_frame["long_target"], x_live)
    p_short = _fit_predict_probability(x_train, train_frame["short_target"], x_live)

    api = MetaApi(token)
    account = await api.metatrader_account_api.get_account(account_id)
    account_name = account.name or ""
    account_kind = _classify_account(account_name)

    if account_kind == "live" and not args.allow_live:
        raise ValueError(
            f"Conta LIVE detectada ({account_name}). "
            "Use --allow-live explicitamente se realmente quiser operar live."
        )
    if account_kind == "unknown" and not args.allow_unknown_account:
        raise ValueError(
            f"Não foi possível classificar conta '{account_name}'. "
            "Use --allow-unknown-account para continuar."
        )

    await account.wait_connected()
    connection = account.get_rpc_connection()
    await connection.connect()
    await connection.wait_synchronized()

    symbol = args.symbol.upper()
    positions = await connection.get_positions()
    symbol_positions = [p for p in positions if (p.get("symbol") or "").upper() == symbol]
    if not symbol_positions:
        payload = {
            "event": "position_status",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "account_id": account_id,
            "account_name": account_name,
            "account_kind": account_kind,
            "symbol": symbol,
            "position_open": False,
            "p_long": p_long,
            "p_short": p_short,
            "note": "No open position for symbol",
        }
        _append_log(args.log_path, payload)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    position = symbol_positions[0]
    side = str(position.get("type") or "").upper()
    open_price = _safe_float(position.get("openPrice"))
    current_price = _safe_float(position.get("currentPrice"))
    stop_loss = _safe_float(position.get("stopLoss"), default=np.nan)
    take_profit = _safe_float(position.get("takeProfit"), default=np.nan)
    volume = _safe_float(position.get("volume"))
    profit = _safe_float(position.get("profit"))
    position_id = str(position.get("id") or position.get("positionId") or position.get("ticketNumber") or "")

    atr_value = _safe_float(labeled_frame.iloc[-1].get("atr"), default=0.0)
    if atr_value <= 0:
        raise ValueError("ATR inválido no dataset rotulado.")

    terminal_state = connection.terminal_state
    spec = terminal_state.specification(symbol=symbol) or {}
    point = _safe_float(spec.get("point"), default=0.01)
    entry_to_current = (current_price - open_price) if side in {"POSITION_TYPE_BUY", "ORDER_TYPE_BUY"} else (open_price - current_price)
    r_distance = max(args.sl_points * point, atr_value * args.atr_sl_mult, point)
    r_multiple = entry_to_current / r_distance

    action = "hold"
    new_stop = None
    if args.enable_breakeven and r_multiple >= args.breakeven_r:
        if side in {"POSITION_TYPE_BUY", "ORDER_TYPE_BUY"}:
            breakeven = open_price + (args.breakeven_buffer_points * point)
            current_sl = stop_loss if not np.isnan(stop_loss) else -np.inf
            if breakeven > current_sl:
                new_stop = breakeven
        else:
            breakeven = open_price - (args.breakeven_buffer_points * point)
            current_sl = stop_loss if not np.isnan(stop_loss) else np.inf
            if breakeven < current_sl:
                new_stop = breakeven
        if new_stop is not None:
            action = "move_sl_to_breakeven"

    if args.enable_trailing and r_multiple >= args.trailing_start_r:
        trail_distance = max(args.trailing_points * point, point)
        if side in {"POSITION_TYPE_BUY", "ORDER_TYPE_BUY"}:
            trailing_sl = current_price - trail_distance
            current_sl = stop_loss if not np.isnan(stop_loss) else -np.inf
            if trailing_sl > current_sl:
                new_stop = trailing_sl
                action = "move_sl_trailing"
        else:
            trailing_sl = current_price + trail_distance
            current_sl = stop_loss if not np.isnan(stop_loss) else np.inf
            if trailing_sl < current_sl:
                new_stop = trailing_sl
                action = "move_sl_trailing"

    status_payload = {
        "event": "position_status",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "account_id": account_id,
        "account_name": account_name,
        "account_kind": account_kind,
        "symbol": symbol,
        "position_open": True,
        "position_id": position_id,
        "side": side,
        "volume": volume,
        "open_price": open_price,
        "current_price": current_price,
        "stop_loss": None if np.isnan(stop_loss) else stop_loss,
        "take_profit": None if np.isnan(take_profit) else take_profit,
        "profit": profit,
        "p_long": p_long,
        "p_short": p_short,
        "atr": atr_value,
        "r_multiple": r_multiple,
        "manager_action": action,
        "proposed_stop_loss": new_stop,
        "dry_run": not args.execute,
    }
    _append_log(args.log_path, status_payload)
    print(json.dumps(status_payload, indent=2, ensure_ascii=False))

    if action in {"move_sl_to_breakeven", "move_sl_trailing"} and new_stop is not None:
        if not args.execute:
            print("✅ DRY RUN: SL seria ajustado, mas nenhuma modificação foi enviada.")
            return
        result = await connection.modify_position(
            position_id=position_id,
            stop_loss=float(new_stop),
            take_profit=None if np.isnan(take_profit) else float(take_profit),
        )
        mod_payload = {
            "event": "position_modified",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "account_id": account_id,
            "symbol": symbol,
            "position_id": position_id,
            "new_stop_loss": float(new_stop),
            "take_profit": None if np.isnan(take_profit) else float(take_profit),
            "result": result,
        }
        _append_log(args.log_path, mod_payload)
        print("✅ Posição modificada com sucesso.")
        print(json.dumps(result, indent=2, ensure_ascii=False))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Gerenciador institucional de posição aberta (status, breakeven e trailing)."
    )
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_PATH)
    parser.add_argument("--account-id", type=str, default="")
    parser.add_argument("--symbol", type=str, default="XAUUSD")
    parser.add_argument("--feature-input", type=Path, default=DEFAULT_FEATURE_INPUT)
    parser.add_argument("--labeled-input", type=Path, default=DEFAULT_LABELED_INPUT)
    parser.add_argument("--min-train-rows", type=int, default=2500)
    parser.add_argument("--sl-points", type=float, default=800.0)
    parser.add_argument("--atr-sl-mult", type=float, default=1.0)
    parser.add_argument("--enable-breakeven", action="store_true")
    parser.add_argument("--breakeven-r", type=float, default=1.0)
    parser.add_argument("--breakeven-buffer-points", type=float, default=20.0)
    parser.add_argument("--enable-trailing", action="store_true")
    parser.add_argument("--trailing-start-r", type=float, default=1.2)
    parser.add_argument("--trailing-points", type=float, default=600.0)
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--allow-unknown-account", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--log-path", type=Path, default=DEFAULT_LOG_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(run_manager(args))


if __name__ == "__main__":
    main()
