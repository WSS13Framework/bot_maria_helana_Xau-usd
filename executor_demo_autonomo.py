import argparse
import asyncio
import json
import subprocess
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
DEFAULT_FEEDBACK_LOG = DATA_DIR / "feedback_events.jsonl"
DEFAULT_RAG_RETRIEVER_SCRIPT = Path("/root/maria-helena/rag_retriever.py")
DEFAULT_RAG_FAISS_INDEX = DATA_DIR / "local_rag" / "index.faiss"
DEFAULT_RAG_SQLITE_DB = DATA_DIR / "local_rag" / "metadata.sqlite3"


def _append_log(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def _append_feedback(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


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


def _safe_float(value: Any, default: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if not np.isfinite(numeric):
        return default
    return numeric


def _extract_last_json_object(raw_text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    candidate = None
    for index, char in enumerate(raw_text):
        if char != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(raw_text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            candidate = parsed
    return candidate


def _normalize_rag_matches(
    payload: dict[str, Any],
    max_items: int,
    snippet_chars: int,
) -> list[dict[str, Any]]:
    raw_matches = payload.get("matches")
    if not isinstance(raw_matches, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in raw_matches[: max(0, max_items)]:
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        text_blob = metadata.get("text")
        if text_blob is None:
            text_blob = item.get("text")
        snippet = str(text_blob or "").replace("\n", " ").strip()
        if snippet_chars > 0:
            snippet = snippet[:snippet_chars]
        normalized.append(
            {
                "id": str(item.get("id") or ""),
                "score": _safe_float(item.get("score"), 0.0),
                "source": str(metadata.get("source") or ""),
                "type": str(metadata.get("type") or ""),
                "title": str(metadata.get("title") or ""),
                "time": str(metadata.get("time") or ""),
                "snippet": snippet,
            }
        )
    return normalized


def _build_rag_query_text(
    symbol: str,
    p_long: float,
    p_short: float,
    exogenous_shock_flag: int,
    exogenous_shock_score: float,
    exogenous_gold_bias: int,
) -> str:
    if exogenous_gold_bias > 0:
        bias_label = "long"
    elif exogenous_gold_bias < 0:
        bias_label = "short"
    else:
        bias_label = "neutral"
    return (
        f"{symbol} market regime context "
        f"p_long={p_long:.4f} p_short={p_short:.4f} "
        f"exogenous_shock_flag={exogenous_shock_flag} "
        f"exogenous_shock_score={exogenous_shock_score:.4f} "
        f"gold_bias={bias_label} "
        "fed fomc inflation dxy vix us10y geopolitics war risk"
    )


def _query_rag_evidence(args: argparse.Namespace, query_text: str) -> dict[str, Any]:
    base_payload = {
        "rag_evidence_enabled": bool(args.enable_rag_evidence),
        "rag_query_text": query_text,
        "rag_backend": None,
        "rag_status": "disabled",
        "rag_error": "",
        "rag_context_matches": [],
    }
    if not args.enable_rag_evidence:
        return base_payload

    if not args.rag_retriever_script.exists():
        base_payload["rag_status"] = "script_not_found"
        base_payload["rag_error"] = f"Arquivo ausente: {args.rag_retriever_script}"
        return base_payload

    command = [
        args.python_bin,
        str(args.rag_retriever_script),
        "--env-file",
        str(args.env_file),
        "--data-dir",
        str(args.rag_data_dir),
        "--faiss-index",
        str(args.rag_faiss_index),
        "--sqlite-db",
        str(args.rag_sqlite_db),
        "query",
        "--text",
        query_text,
        "--top-k",
        str(args.rag_top_k),
        "--prefer",
        args.rag_prefer,
    ]

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=max(5, int(args.rag_timeout_sec)),
        )
    except subprocess.TimeoutExpired as exc:
        base_payload["rag_status"] = "timeout"
        base_payload["rag_error"] = f"RAG timeout ({exc.timeout}s)"
        return base_payload
    except Exception as exc:  # noqa: BLE001
        base_payload["rag_status"] = "error"
        base_payload["rag_error"] = str(exc)
        return base_payload

    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    parsed = _extract_last_json_object(stdout)

    if "Query via Pinecone" in stdout:
        base_payload["rag_backend"] = "pinecone"
    elif "Query via FAISS/SQLite" in stdout:
        base_payload["rag_backend"] = "faiss"

    if completed.returncode != 0:
        base_payload["rag_status"] = "error"
        base_payload["rag_error"] = (stderr or stdout)[-600:]
        return base_payload
    if not isinstance(parsed, dict):
        base_payload["rag_status"] = "parse_error"
        base_payload["rag_error"] = "Nao foi possivel extrair JSON da resposta RAG"
        return base_payload

    base_payload["rag_status"] = "ok"
    base_payload["rag_context_matches"] = _normalize_rag_matches(
        payload=parsed,
        max_items=args.rag_context_max_items,
        snippet_chars=args.rag_snippet_chars,
    )
    return base_payload


def _parse_hhmm_to_minutes(value: str) -> int:
    text = str(value).strip()
    parts = text.split(":")
    if len(parts) != 2:
        raise ValueError(f"Horario invalido: {value}")
    hour = int(parts[0])
    minute = int(parts[1])
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError(f"Horario invalido: {value}")
    return (hour * 60) + minute


def _parse_session_windows(window_spec: str) -> list[tuple[int, int]]:
    windows: list[tuple[int, int]] = []
    for raw_item in str(window_spec or "").split(","):
        item = raw_item.strip()
        if not item:
            continue
        if "-" not in item:
            raise ValueError(f"Janela invalida: {item}")
        start_text, end_text = item.split("-", 1)
        start = _parse_hhmm_to_minutes(start_text)
        end = _parse_hhmm_to_minutes(end_text)
        windows.append((start, end))
    return windows


def _minute_inside_windows(minute_of_day: int, windows: list[tuple[int, int]]) -> bool:
    if not windows:
        return True
    for start, end in windows:
        if start == end:
            continue
        if start < end:
            if start <= minute_of_day < end:
                return True
        else:
            # Overnight window, e.g. 22:00-02:00
            if minute_of_day >= start or minute_of_day < end:
                return True
    return False


def _session_gate_status(
    now_utc: datetime,
    windows: list[tuple[int, int]],
    friday_close_hour_utc: float,
    sunday_open_hour_utc: float,
    allow_rollover_window: bool,
) -> tuple[bool, str]:
    weekday = now_utc.weekday()
    hour_fraction = now_utc.hour + (now_utc.minute / 60.0)
    minute_of_day = (now_utc.hour * 60) + now_utc.minute

    if weekday == 5:
        return False, "weekend_closed_saturday"
    if weekday == 6 and hour_fraction < sunday_open_hour_utc:
        return False, "weekend_closed_sunday_before_open"
    if weekday == 4 and hour_fraction >= friday_close_hour_utc:
        return False, "weekend_closed_friday_after_close"

    # Typical low-liquidity/rollover zone for metals.
    if not allow_rollover_window:
        rollover_start = (20 * 60) + 55
        rollover_end = (22 * 60) + 5
        if rollover_start <= minute_of_day < rollover_end:
            return False, "rollover_liquidity_block"

    if not _minute_inside_windows(minute_of_day, windows):
        return False, "outside_configured_session_windows"
    return True, "session_ok"


def _atr_volatility_ratio(frame: pd.DataFrame, lookback: int) -> tuple[float, float, float]:
    atr_series = pd.to_numeric(frame.get("atr"), errors="coerce")
    atr_series = atr_series.replace([np.inf, -np.inf], np.nan).dropna()
    if atr_series.empty:
        return 0.0, 0.0, 0.0

    current = float(atr_series.iloc[-1])
    if lookback > 0:
        reference_slice = atr_series.iloc[-lookback:]
    else:
        reference_slice = atr_series
    reference = float(reference_slice.median()) if not reference_slice.empty else 0.0
    if reference <= 0:
        return current, reference, 0.0
    return current, reference, float(current / reference)


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

    symbol = args.symbol.upper()
    latest_feature = feature_frame.iloc[-1]
    latest_labeled = labeled_frame.iloc[-1]
    p_long = _fit_predict_probability(x_train, train_frame["long_target"], x_live)
    p_short = _fit_predict_probability(x_train, train_frame["short_target"], x_live)

    exogenous_shock_flag = int(_safe_float(latest_feature.get("exogenous_shock_flag", 0), 0.0))
    exogenous_shock_score = _safe_float(latest_feature.get("exogenous_shock_score", 0.0), 0.0)
    exogenous_gold_bias = int(_safe_float(latest_feature.get("exogenous_gold_bias", 0), 0.0))
    exogenous_threshold_premium = _safe_float(
        latest_feature.get("exogenous_threshold_premium", 0.0), 0.0
    )
    exogenous_risk_multiplier = _safe_float(
        latest_feature.get("exogenous_risk_multiplier", 1.0), 1.0
    )
    rag_query_text = _build_rag_query_text(
        symbol=args.symbol.upper(),
        p_long=p_long,
        p_short=p_short,
        exogenous_shock_flag=exogenous_shock_flag,
        exogenous_shock_score=exogenous_shock_score,
        exogenous_gold_bias=exogenous_gold_bias,
    )
    rag_evidence = _query_rag_evidence(args, rag_query_text)

    effective_threshold = args.threshold
    effective_risk_pct = args.risk_per_trade_pct
    shock_threshold_add_applied = 0.0
    shock_risk_multiplier_applied = 1.0
    if not args.disable_exogenous_guardrail and exogenous_shock_flag == 1:
        shock_threshold_add_applied = max(args.shock_threshold_add, exogenous_threshold_premium)
        effective_threshold = float(np.clip(args.threshold + shock_threshold_add_applied, 0.0, 0.95))
        shock_risk_multiplier_applied = float(
            np.clip(
                min(exogenous_risk_multiplier, args.shock_risk_mult),
                args.min_shock_risk_mult,
                1.0,
            )
        )
        effective_risk_pct = max(
            args.min_risk_per_trade_pct,
            args.risk_per_trade_pct * shock_risk_multiplier_applied,
        )

    atr_current, atr_reference, atr_volatility_ratio = _atr_volatility_ratio(
        labeled_frame,
        lookback=max(20, int(args.atr_regime_lookback)),
    )
    volatility_threshold_add_applied = 0.0
    volatility_risk_multiplier_applied = 1.0
    blocked_by_volatility_guardrail = False
    volatility_gate_reason = "volatility_guardrail_not_enforced"
    if args.enforce_volatility_guardrail:
        if atr_volatility_ratio >= args.volatility_max_ratio:
            blocked_by_volatility_guardrail = True
            volatility_gate_reason = "atr_extreme_volatility_block"
        elif atr_volatility_ratio >= args.volatility_warning_ratio:
            volatility_gate_reason = "atr_high_volatility_adjusted"
            volatility_threshold_add_applied = max(0.0, args.volatility_threshold_add)
            effective_threshold = float(
                np.clip(effective_threshold + volatility_threshold_add_applied, 0.0, 0.95)
            )
            volatility_risk_multiplier_applied = float(
                np.clip(args.volatility_risk_mult, args.min_volatility_risk_mult, 1.0)
            )
            effective_risk_pct = max(
                args.min_risk_per_trade_pct,
                effective_risk_pct * volatility_risk_multiplier_applied,
            )
        else:
            volatility_gate_reason = "atr_volatility_ok"

    side = None
    blocked_by_exogenous_bias = False
    if p_long >= effective_threshold and p_long >= p_short + args.edge_margin:
        side = "buy"
    elif p_short >= effective_threshold and p_short >= p_long + args.edge_margin:
        side = "sell"

    if (
        side is not None
        and not args.disable_bias_block
        and exogenous_shock_flag == 1
        and exogenous_gold_bias != 0
    ):
        if (side == "buy" and exogenous_gold_bias < 0) or (
            side == "sell" and exogenous_gold_bias > 0
        ):
            blocked_by_exogenous_bias = True
            side = None

    if side is not None and blocked_by_volatility_guardrail:
        side = None

    blocked_by_session_window = False
    session_gate_reason = "session_gate_not_enforced"
    if args.enforce_session_window:
        windows = _parse_session_windows(args.session_windows)
        now_utc = datetime.now(timezone.utc)
        session_ok, session_gate_reason = _session_gate_status(
            now_utc=now_utc,
            windows=windows,
            friday_close_hour_utc=args.friday_close_hour_utc,
            sunday_open_hour_utc=args.sunday_open_hour_utc,
            allow_rollover_window=args.allow_rollover_window,
        )
        if not session_ok and side is not None:
            blocked_by_session_window = True
            side = None

    if side is None:
        no_trade_payload = {
            "event": "no_trade_signal",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "account_id": account_id,
            "symbol": symbol,
            "p_long": p_long,
            "p_short": p_short,
            "threshold": args.threshold,
            "effective_threshold": effective_threshold,
            "edge_margin": args.edge_margin,
            "blocked_by_exogenous_bias": blocked_by_exogenous_bias,
            "blocked_by_volatility_guardrail": blocked_by_volatility_guardrail,
            "volatility_gate_reason": volatility_gate_reason,
            "blocked_by_session_window": blocked_by_session_window,
            "session_gate_reason": session_gate_reason,
            "session_windows": args.session_windows,
            "atr_current": atr_current,
            "atr_reference_median": atr_reference,
            "atr_volatility_ratio": atr_volatility_ratio,
            "volatility_threshold_add_applied": volatility_threshold_add_applied,
            "volatility_risk_multiplier_applied": volatility_risk_multiplier_applied,
            "exogenous_shock_flag": exogenous_shock_flag,
            "exogenous_shock_score": exogenous_shock_score,
            "exogenous_gold_bias": exogenous_gold_bias,
            "exogenous_threshold_premium": exogenous_threshold_premium,
            "exogenous_risk_multiplier": exogenous_risk_multiplier,
            **rag_evidence,
            "feature_time": latest_feature["time"].isoformat(),
        }
        _append_log(args.log_path, no_trade_payload)
        _append_feedback(
            args.feedback_log_path,
            {
                **no_trade_payload,
                "feedback_type": "signal",
                "decision": "no_trade",
                "source": "executor_demo_autonomo",
            },
        )
        print("⚠️ Sem trade: sinal sem confiança suficiente.")
        print(json.dumps(no_trade_payload, indent=2, ensure_ascii=False))
        return

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

    account_info = await connection.get_account_information()
    balance = float(account_info.get("balance") or account_info.get("equity") or 0.0)
    if balance <= 0:
        raise ValueError("Saldo/equity inválido para cálculo de risco.")

    stream_connection = account.get_streaming_connection()
    await stream_connection.connect()
    await stream_connection.wait_synchronized()
    await stream_connection.subscribe_to_market_data(symbol=symbol)
    terminal_state = stream_connection.terminal_state
    price = None
    for _ in range(8):
        price = terminal_state.price(symbol=symbol)
        if price:
            break
        await asyncio.sleep(0.5)
    if not price:
        raise ValueError(f"Preço indisponível para {symbol}")
    specification = terminal_state.specification(symbol=symbol) or {}
    point = float(specification.get("point") or 0.01)
    sl_points = max(args.min_sl_points, (atr_value / point) * args.atr_sl_mult)
    tp_points = max(args.min_tp_points, sl_points * args.tp_rr)
    volume, risk_usd = _compute_volume(
        balance=balance,
        risk_pct=effective_risk_pct,
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
        "effective_risk_per_trade_pct": effective_risk_pct,
        "shock_risk_multiplier_applied": shock_risk_multiplier_applied,
        "risk_usd": risk_usd,
        "p_long": p_long,
        "p_short": p_short,
        "threshold": args.threshold,
        "effective_threshold": effective_threshold,
        "shock_threshold_add_applied": shock_threshold_add_applied,
        "edge_margin": args.edge_margin,
        "blocked_by_volatility_guardrail": blocked_by_volatility_guardrail,
        "volatility_gate_reason": volatility_gate_reason,
        "atr_current": atr_current,
        "atr_reference_median": atr_reference,
        "atr_volatility_ratio": atr_volatility_ratio,
        "volatility_threshold_add_applied": volatility_threshold_add_applied,
        "volatility_risk_multiplier_applied": volatility_risk_multiplier_applied,
        "exogenous_shock_flag": exogenous_shock_flag,
        "exogenous_shock_score": exogenous_shock_score,
        "exogenous_gold_bias": exogenous_gold_bias,
        "exogenous_threshold_premium": exogenous_threshold_premium,
        "exogenous_risk_multiplier": exogenous_risk_multiplier,
        **rag_evidence,
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
    _append_feedback(
        args.feedback_log_path,
        {
            **order_plan,
            "feedback_type": "signal",
            "decision": "trade_plan",
            "source": "executor_demo_autonomo",
        },
    )
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
        "p_long": p_long,
        "p_short": p_short,
        "effective_threshold": effective_threshold,
        "effective_risk_per_trade_pct": effective_risk_pct,
        "blocked_by_volatility_guardrail": blocked_by_volatility_guardrail,
        "volatility_gate_reason": volatility_gate_reason,
        "atr_current": atr_current,
        "atr_reference_median": atr_reference,
        "atr_volatility_ratio": atr_volatility_ratio,
        "volatility_threshold_add_applied": volatility_threshold_add_applied,
        "volatility_risk_multiplier_applied": volatility_risk_multiplier_applied,
        "exogenous_shock_flag": exogenous_shock_flag,
        "exogenous_shock_score": exogenous_shock_score,
        "exogenous_gold_bias": exogenous_gold_bias,
        **rag_evidence,
        "result": result,
    }
    _append_log(args.log_path, execution_log)
    _append_feedback(
        args.feedback_log_path,
        {
            **execution_log,
            "feedback_type": "execution",
            "decision": "order_executed",
            "source": "executor_demo_autonomo",
        },
    )
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
    parser.add_argument("--min-risk-per-trade-pct", type=float, default=0.001)
    parser.add_argument("--atr-sl-mult", type=float, default=1.0)
    parser.add_argument("--tp-rr", type=float, default=1.5)
    parser.add_argument("--min-sl-points", type=float, default=400.0)
    parser.add_argument("--min-tp-points", type=float, default=600.0)
    parser.add_argument("--min-train-rows", type=int, default=2500)
    parser.add_argument("--max-open-positions", type=int, default=1)
    parser.add_argument("--max-orders-per-day", type=int, default=3)
    parser.add_argument("--max-volume-cap", type=float, default=0.10)
    parser.add_argument("--shock-threshold-add", type=float, default=0.05)
    parser.add_argument("--shock-risk-mult", type=float, default=0.60)
    parser.add_argument("--min-shock-risk-mult", type=float, default=0.35)
    parser.add_argument("--disable-exogenous-guardrail", action="store_true")
    parser.add_argument("--disable-bias-block", action="store_true")
    parser.add_argument("--enforce-session-window", action="store_true")
    parser.add_argument("--session-windows", type=str, default="06:00-09:00,12:00-16:30")
    parser.add_argument("--friday-close-hour-utc", type=float, default=21.0)
    parser.add_argument("--sunday-open-hour-utc", type=float, default=22.0)
    parser.add_argument("--allow-rollover-window", action="store_true")
    parser.add_argument("--enforce-volatility-guardrail", action="store_true")
    parser.add_argument("--atr-regime-lookback", type=int, default=288)
    parser.add_argument("--volatility-warning-ratio", type=float, default=1.6)
    parser.add_argument("--volatility-max-ratio", type=float, default=2.4)
    parser.add_argument("--volatility-threshold-add", type=float, default=0.03)
    parser.add_argument("--volatility-risk-mult", type=float, default=0.70)
    parser.add_argument("--min-volatility-risk-mult", type=float, default=0.40)
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--allow-unknown-account", action="store_true")
    parser.add_argument("--ignore-gate", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--comment", type=str, default="MariaHelena-Autonomo")
    parser.add_argument("--log-path", type=Path, default=DEFAULT_LOG_PATH)
    parser.add_argument("--feedback-log-path", type=Path, default=DEFAULT_FEEDBACK_LOG)
    parser.add_argument("--enable-rag-evidence", action="store_true")
    parser.add_argument("--python-bin", type=str, default="python3")
    parser.add_argument("--rag-retriever-script", type=Path, default=DEFAULT_RAG_RETRIEVER_SCRIPT)
    parser.add_argument("--rag-data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--rag-faiss-index", type=Path, default=DEFAULT_RAG_FAISS_INDEX)
    parser.add_argument("--rag-sqlite-db", type=Path, default=DEFAULT_RAG_SQLITE_DB)
    parser.add_argument("--rag-top-k", type=int, default=5)
    parser.add_argument("--rag-prefer", type=str, choices=("pinecone", "faiss"), default="pinecone")
    parser.add_argument("--rag-timeout-sec", type=float, default=45.0)
    parser.add_argument("--rag-context-max-items", type=int, default=3)
    parser.add_argument("--rag-snippet-chars", type=int, default=220)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(run_autonomous(args))


if __name__ == "__main__":
    main()
