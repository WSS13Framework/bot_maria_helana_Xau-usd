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
DEFAULT_GATE_REPORT = DATA_DIR / "gate_report.json"
DEFAULT_LOG_PATH = DATA_DIR / "demo_autonomous_executor_log.jsonl"


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


def _align_live_features(
    train_frame: pd.DataFrame,
    live_frame: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    train_features = _feature_columns(train_frame)
    live_features = _feature_columns(live_frame)
    common_features = [column for column in train_features if column in live_features]
    if not common_features:
        raise ValueError("Nenhuma feature comum entre treino e inferência ao vivo.")

    x_train = train_frame[common_features].copy().ffill().bfill().fillna(0.0)
    x_live_all = live_frame[common_features].copy().ffill().bfill().fillna(0.0)
    return x_train, x_live_all, common_features


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


def _round_to_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    rounded = round(value / step) * step
    step_text = f"{step:.10f}".rstrip("0")
    decimals = len(step_text.split(".")[1]) if "." in step_text else 0
    return round(rounded, decimals)


def _compute_volume(
    balance: float,
    risk_pct: float,
    sl_points: float,
    point: float,
    specification: dict[str, Any],
    max_volume_cap: float,
) -> tuple[float, float]:
    risk_usd = max(0.0, balance * risk_pct)
    min_volume = float(specification.get("minVolume") or 0.01)
    max_volume = float(specification.get("maxVolume") or 100.0)
    if max_volume_cap > 0:
        max_volume = min(max_volume, max_volume_cap)
    volume_step = float(specification.get("volumeStep") or min_volume or 0.01)
    tick_size = float(specification.get("tickSize") or point or 0.01)
    tick_value = specification.get("tickValue")
    contract_size = float(specification.get("tradeContractSize") or 100.0)

    stop_distance_price = max(sl_points * point, point)
    if tick_value is not None and float(tick_value) > 0 and tick_size > 0:
        risk_per_lot = (stop_distance_price / tick_size) * float(tick_value)
    else:
        risk_per_lot = stop_distance_price * contract_size
    risk_per_lot = max(risk_per_lot, 1e-9)

    raw_volume = risk_usd / risk_per_lot
    clipped = min(max(raw_volume, min_volume), max_volume)
    volume = _round_to_step(clipped, volume_step)
    volume = min(max(volume, min_volume), max_volume)
    return volume, risk_usd


def _count_today_executions(log_path: Path, account_id: str) -> int:
    if not log_path.exists():
        return 0
    today = datetime.now(timezone.utc).date().isoformat()
    count = 0
    with log_path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("event") != "order_executed":
                continue
            if payload.get("account_id") != account_id:
                continue
            timestamp = str(payload.get("timestamp") or "")
            if timestamp.startswith(today):
                count += 1
    return count


async def run_autonomous(args: argparse.Namespace) -> None:
    cfg = dotenv_values(args.env_file)
    token = (cfg.get("METAAPI_TOKEN") or "").strip()
    account_id = (args.account_id or cfg.get("METAAPI_DEMO_ACCOUNT_ID") or "").strip()
    if not token:
        raise ValueError("METAAPI_TOKEN não encontrado no .env")
    if not account_id:
        raise ValueError("account_id ausente. Use --account-id ou METAAPI_DEMO_ACCOUNT_ID no .env")

    if not args.ignore_gate:
        if not args.gate_report.exists():
            raise ValueError(f"Gate report não encontrado: {args.gate_report}")
        gate_payload = json.loads(args.gate_report.read_text(encoding="utf-8"))
        recommendation = gate_payload.get("recommendation")
        if recommendation != "APPROVED_FOR_SHADOW":
            raise ValueError(f"Gate não aprovado para shadow ({recommendation}).")

    feature_frame = _load_frame(args.feature_input)
    labeled_frame = _load_frame(args.labeled_input)
    train_frame = _prepare_training_targets(labeled_frame)
    if len(train_frame) < args.min_train_rows:
        raise ValueError(
            f"Amostra de treino insuficiente ({len(train_frame)}). "
            f"Necessário >= {args.min_train_rows}"
        )

    # Use labeled frame for live inference so ATR is available.
    x_train, x_live_all, features = _align_live_features(
        train_frame=train_frame,
        live_frame=labeled_frame,
    )
    x_live = x_live_all.iloc[[-1]]

    p_long = _fit_predict_probability(x_train, train_frame["long_target"], x_live)
    p_short = _fit_predict_probability(x_train, train_frame["short_target"], x_live)

    side = None
    if p_long >= args.threshold and p_long >= p_short + args.edge_margin:
        side = "buy"
    elif p_short >= args.threshold and p_short >= p_long + args.edge_margin:
        side = "sell"

    latest_feature = feature_frame.iloc[-1]
    latest_labeled = labeled_frame.iloc[-1]
    atr_value = float(latest_labeled.get("atr") or 0.0)
    if atr_value <= 0:
        raise ValueError("ATR inválido no último candle; não é possível calcular SL dinâmico.")

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

    positions = await connection.get_positions()
    symbol = args.symbol.upper()
    symbol_positions = [
        position for position in positions if (position.get("symbol") or "").upper() == symbol
    ]
    if len(symbol_positions) >= args.max_open_positions:
        print(
            f"⚠️ Execução bloqueada: {len(symbol_positions)} posições abertas em {symbol} "
            f"(limite={args.max_open_positions})."
        )
        return

    today_count = _count_today_executions(args.log_path, account_id)
    if today_count >= args.max_orders_per_day:
        print(
            f"⚠️ Execução bloqueada: limite diário atingido "
            f"({today_count}/{args.max_orders_per_day})."
        )
        return

    if side is None:
        no_trade_payload = {
            "event": "no_trade_signal",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "account_id": account_id,
            "symbol": symbol,
            "p_long": p_long,
            "p_short": p_short,
            "threshold": args.threshold,
            "edge_margin": args.edge_margin,
            "feature_time": latest_feature["time"].isoformat(),
        }
        _append_log(args.log_path, no_trade_payload)
        print("⚠️ Sem trade: sinal sem confiança suficiente.")
        print(json.dumps(no_trade_payload, indent=2, ensure_ascii=False))
        return

    account_info = await connection.get_account_information()
    balance = float(account_info.get("balance") or account_info.get("equity") or 0.0)
    if balance <= 0:
        raise ValueError("Saldo/equity inválido para cálculo de risco.")

    terminal_state = connection.terminal_state
    price = terminal_state.price(symbol=symbol)
    if not price:
        raise ValueError(f"Preço indisponível para {symbol}")
    specification = terminal_state.specification(symbol=symbol) or {}
    point = float(specification.get("point") or 0.01)
    sl_points = max(args.min_sl_points, (atr_value / point) * args.atr_sl_mult)
    tp_points = max(args.min_tp_points, sl_points * args.tp_rr)
    volume, risk_usd = _compute_volume(
        balance=balance,
        risk_pct=args.risk_per_trade_pct,
        sl_points=sl_points,
        point=point,
        specification=specification,
        max_volume_cap=args.max_volume_cap,
    )
    if args.max_volume_cap > 0 and volume > args.max_volume_cap:
        raise ValueError(
            f"Volume calculado ({volume}) acima do max_volume_cap ({args.max_volume_cap})."
        )

    ask = float(price.get("ask"))
    bid = float(price.get("bid"))
    entry_price = ask if side == "buy" else bid
    stop_loss = entry_price - (sl_points * point) if side == "buy" else entry_price + (sl_points * point)
    take_profit = entry_price + (tp_points * point) if side == "buy" else entry_price - (tp_points * point)

    order_plan = {
        "event": "order_plan",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "account_id": account_id,
        "account_name": account_name,
        "account_kind": account_kind,
        "symbol": symbol,
        "side": side,
        "volume": volume,
        "balance": balance,
        "risk_per_trade_pct": args.risk_per_trade_pct,
        "risk_usd": risk_usd,
        "p_long": p_long,
        "p_short": p_short,
        "threshold": args.threshold,
        "edge_margin": args.edge_margin,
        "atr": atr_value,
        "sl_points": sl_points,
        "tp_points": tp_points,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "entry_price": entry_price,
        "feature_time": latest_feature["time"].isoformat(),
        "dry_run": not args.execute,
    }
    _append_log(args.log_path, order_plan)
    print("Plano de ordem autonoma:")
    print(json.dumps(order_plan, indent=2, ensure_ascii=False))

    if not args.execute:
        print("✅ DRY RUN concluído (nenhuma ordem enviada). Use --execute para enviar.")
        return

    options = {"comment": args.comment}
    if side == "buy":
        result = await connection.create_market_buy_order(
            symbol, volume, stop_loss, take_profit, options
        )
    else:
        result = await connection.create_market_sell_order(
            symbol, volume, stop_loss, take_profit, options
        )

    execution_log = {
        "event": "order_executed",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "account_id": account_id,
        "symbol": symbol,
        "side": side,
        "volume": volume,
        "result": result,
    }
    _append_log(args.log_path, execution_log)
    print("✅ Ordem autonoma enviada com sucesso.")
    print(json.dumps(result, indent=2, ensure_ascii=False))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Executor autonomo DEMO com sizing por saldo e controle de risco.")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_PATH)
    parser.add_argument("--account-id", type=str, default="")
    parser.add_argument("--symbol", type=str, default="XAUUSD")
    parser.add_argument("--feature-input", type=Path, default=DEFAULT_FEATURE_INPUT)
    parser.add_argument("--labeled-input", type=Path, default=DEFAULT_LABELED_INPUT)
    parser.add_argument("--gate-report", type=Path, default=DEFAULT_GATE_REPORT)
    parser.add_argument("--threshold", type=float, default=0.65)
    parser.add_argument("--edge-margin", type=float, default=0.03)
    parser.add_argument("--risk-per-trade-pct", type=float, default=0.003)
    parser.add_argument("--atr-sl-mult", type=float, default=1.0)
    parser.add_argument("--tp-rr", type=float, default=1.5)
    parser.add_argument("--min-sl-points", type=float, default=400.0)
    parser.add_argument("--min-tp-points", type=float, default=600.0)
    parser.add_argument("--min-train-rows", type=int, default=2500)
    parser.add_argument("--max-open-positions", type=int, default=1)
    parser.add_argument("--max-orders-per-day", type=int, default=3)
    parser.add_argument("--max-volume-cap", type=float, default=0.10)
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--allow-unknown-account", action="store_true")
    parser.add_argument("--ignore-gate", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--comment", type=str, default="MariaHelena-Autonomo")
    parser.add_argument("--log-path", type=Path, default=DEFAULT_LOG_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(run_autonomous(args))


if __name__ == "__main__":
    main()
