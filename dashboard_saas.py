import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import dotenv_values
from metaapi_cloud_sdk import MetaApi

from executor_demo_autonomo import _compute_volume, _safe_float

DATA_DIR = Path("/root/maria-helena/data")
ENV_PATH = Path("/root/maria-helena/.env")


@st.cache_data(ttl=20)
def load_candles(path: Path, rows: int = 300) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
    frame = pd.read_json(path)
    frame["time"] = pd.to_datetime(frame["time"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["time"]).sort_values("time")
    return frame.tail(rows).copy()


@st.cache_data(ttl=10)
def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def build_candle_figure(frame: pd.DataFrame, title: str) -> go.Figure:
    fig = go.Figure(
        data=[
            go.Candlestick(
                x=frame["time"],
                open=frame["open"],
                high=frame["high"],
                low=frame["low"],
                close=frame["close"],
                increasing_line_color="#26a69a",
                decreasing_line_color="#ef5350",
                name="XAUUSD",
            )
        ]
    )
    fig.update_layout(
        title=title,
        xaxis_title="Time (UTC)",
        yaxis_title="Price",
        template="plotly_dark",
        height=520,
        margin=dict(l=10, r=10, t=60, b=10),
    )
    return fig


async def fetch_account_snapshot(token: str, account_id: str, symbol: str) -> dict[str, Any]:
    api = MetaApi(token)
    account = await api.metatrader_account_api.get_account(account_id)
    await account.wait_connected()
    conn = account.get_rpc_connection()
    await conn.connect()
    await conn.wait_synchronized()

    account_info = await conn.get_account_information()
    positions = await conn.get_positions()
    symbol_positions = [p for p in positions if (p.get("symbol") or "").upper() == symbol.upper()]

    terminal_state = conn.terminal_state
    price = terminal_state.price(symbol=symbol)
    spec = terminal_state.specification(symbol=symbol) or {}

    return {
        "account_name": account.name,
        "account_id": account_id,
        "account_info": account_info,
        "positions": symbol_positions,
        "price": price,
        "specification": spec,
    }


def compute_suggested_lot(
    snapshot: dict[str, Any],
    risk_pct: float,
    sl_points: float,
) -> dict[str, Any]:
    account_info = snapshot.get("account_info", {}) or {}
    spec = snapshot.get("specification", {}) or {}
    balance = _safe_float(account_info.get("balance") or account_info.get("equity"), default=0.0)
    point = _safe_float(spec.get("point"), default=0.01)
    volume, risk_usd = _compute_volume(
        balance=balance,
        risk_pct=risk_pct,
        sl_points=sl_points,
        point=point,
        specification=spec,
    )
    return {"balance": balance, "risk_usd": risk_usd, "volume": volume}


def render_position_table(positions: list[dict[str, Any]]) -> None:
    if not positions:
        st.info("No open XAUUSD positions.")
        return

    rows = []
    for p in positions:
        rows.append(
            {
                "id": p.get("id") or p.get("positionId") or p.get("ticketNumber"),
                "type": p.get("type"),
                "volume": p.get("volume"),
                "open_price": p.get("openPrice"),
                "current_price": p.get("currentPrice"),
                "stop_loss": p.get("stopLoss"),
                "take_profit": p.get("takeProfit"),
                "profit": p.get("profit"),
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def build_executor_command(
    account_id: str,
    threshold: float,
    edge_margin: float,
    risk_pct: float,
    max_open_positions: int,
    max_orders_per_day: int,
    execute: bool,
) -> str:
    cmd = (
        "python3 executor_demo_autonomo.py "
        f"--account-id {account_id} --symbol XAUUSD "
        f"--threshold {threshold:.2f} --edge-margin {edge_margin:.2f} "
        f"--risk-per-trade-pct {risk_pct:.4f} "
        f"--max-open-positions {max_open_positions} "
        f"--max-orders-per-day {max_orders_per_day}"
    )
    if execute:
        cmd += " --execute"
    return cmd


def main() -> None:
    st.set_page_config(page_title="Maria Helena SaaS Panel", layout="wide")
    st.title("Maria Helena — Institutional Trading Panel")

    cfg = dotenv_values(ENV_PATH)
    token = (cfg.get("METAAPI_TOKEN") or "").strip()
    default_demo_account = (cfg.get("METAAPI_DEMO_ACCOUNT_ID") or "").strip()

    with st.sidebar:
        st.header("Execution Controls")
        account_id = st.text_input("MetaApi Account ID", value=default_demo_account)
        symbol = st.text_input("Symbol", value="XAUUSD")
        threshold = st.slider("Signal Threshold", min_value=0.50, max_value=0.90, value=0.65, step=0.01)
        edge_margin = st.slider("Edge Margin", min_value=0.00, max_value=0.10, value=0.03, step=0.01)
        risk_pct = st.slider("Risk per Trade (%)", min_value=0.05, max_value=1.00, value=0.20, step=0.05) / 100.0
        sl_points = st.number_input("SL Points", min_value=100.0, max_value=5000.0, value=800.0, step=50.0)
        max_open_positions = st.number_input("Max Open Positions", min_value=1, max_value=5, value=1, step=1)
        max_orders_per_day = st.number_input("Max Orders per Day", min_value=1, max_value=20, value=3, step=1)
        execute_mode = st.toggle("EXECUTE Mode (live order)", value=False)

    if not token:
        st.error("METAAPI_TOKEN not found in /root/maria-helena/.env")
        st.stop()
    if not account_id:
        st.warning("Enter a MetaApi account id in sidebar.")
        st.stop()

    col_a, col_b, col_c, col_d = st.columns(4)
    gate = load_json(DATA_DIR / "gate_report.json")
    recommendation = gate.get("recommendation", "UNKNOWN")
    col_a.metric("Gate Recommendation", recommendation)

    candles = load_candles(DATA_DIR / "xauusd_m5.json", rows=300)
    if not candles.empty:
        col_b.metric("Last Candle", str(candles["time"].iloc[-1]))
        col_c.metric("Last Close", f"{candles['close'].iloc[-1]:.2f}")
        col_d.metric("Rows Loaded", int(len(candles)))
    else:
        col_b.metric("Last Candle", "N/A")
        col_c.metric("Last Close", "N/A")
        col_d.metric("Rows Loaded", 0)

    snapshot = asyncio.run(fetch_account_snapshot(token=token, account_id=account_id, symbol=symbol))
    acct = snapshot.get("account_info", {}) or {}
    price = snapshot.get("price", {}) or {}
    positions = snapshot.get("positions", []) or []
    lot = compute_suggested_lot(snapshot=snapshot, risk_pct=risk_pct, sl_points=sl_points)

    st.subheader("Account Snapshot")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Balance", f"{_safe_float(acct.get('balance')):.2f}")
    c2.metric("Equity", f"{_safe_float(acct.get('equity')):.2f}")
    c3.metric("Free Margin", f"{_safe_float(acct.get('freeMargin')):.2f}")
    c4.metric("Open XAU Positions", int(len(positions)))

    c5, c6, c7 = st.columns(3)
    c5.metric("Ask", f"{_safe_float(price.get('ask')):.2f}")
    c6.metric("Bid", f"{_safe_float(price.get('bid')):.2f}")
    c7.metric("Suggested Lot", f"{lot['volume']:.2f}")
    st.caption(f"Risk budget: {lot['risk_usd']:.2f} USD | Risk pct: {risk_pct*100:.2f}% | SL points: {sl_points:.0f}")

    st.subheader("Open Position(s)")
    render_position_table(positions)

    st.subheader("Market Chart (XAUUSD M5)")
    if candles.empty:
        st.warning("No candle data found in /root/maria-helena/data/xauusd_m5.json")
    else:
        st.plotly_chart(build_candle_figure(candles, "XAUUSD M5"), use_container_width=True)

    st.subheader("Execution Command (copy/paste)")
    command = build_executor_command(
        account_id=account_id,
        threshold=threshold,
        edge_margin=edge_margin,
        risk_pct=risk_pct,
        max_open_positions=max_open_positions,
        max_orders_per_day=max_orders_per_day,
        execute=execute_mode,
    )
    st.code(command, language="bash")
    if execute_mode:
        st.warning("EXECUTE mode selected. Confirm account type and risk settings before running command.")

    st.caption(f"Panel generated at {datetime.now(timezone.utc).isoformat()}")


if __name__ == "__main__":
    main()
