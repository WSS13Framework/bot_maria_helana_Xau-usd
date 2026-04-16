import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import dotenv_values
from neo4j import GraphDatabase

DATA_DIR = Path("/root/maria-helena/data")
DEFAULT_ENV = Path("/root/maria-helena/.env")


class Neo4jKG:
    def __init__(self, uri: str, user: str, password: str, database: str = "neo4j") -> None:
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.database = database

    def close(self) -> None:
        self.driver.close()

    def write(self, query: str, params: dict[str, Any] | None = None) -> None:
        with self.driver.session(database=self.database) as session:
            session.execute_write(lambda tx: tx.run(query, params or {}))

    def read(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        with self.driver.session(database=self.database) as session:
            result = session.execute_read(lambda tx: list(tx.run(query, params or {})))
        return [record.data() for record in result]


def _safe_json_load(path: Path) -> Any:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def _create_constraints(kg: Neo4jKG) -> None:
    statements = [
        "CREATE CONSTRAINT asset_symbol IF NOT EXISTS FOR (a:Asset) REQUIRE a.symbol IS UNIQUE",
        "CREATE CONSTRAINT candle_key IF NOT EXISTS FOR (c:Candle) REQUIRE (c.symbol, c.timeframe, c.time) IS UNIQUE",
        "CREATE CONSTRAINT signal_time IF NOT EXISTS FOR (s:Signal) REQUIRE s.time IS UNIQUE",
        "CREATE CONSTRAINT event_key IF NOT EXISTS FOR (e:Event) REQUIRE e.event_id IS UNIQUE",
        "CREATE CONSTRAINT run_id IF NOT EXISTS FOR (r:RiskRun) REQUIRE r.run_id IS UNIQUE",
    ]
    for statement in statements:
        kg.write(statement)


def _sync_candles(kg: Neo4jKG, symbol: str, timeframe: str, path: Path, limit: int) -> int:
    if not path.exists():
        return 0
    candles = _safe_json_load(path) or []
    if not isinstance(candles, list):
        return 0
    subset = candles[-limit:] if limit > 0 else candles
    query = """
    MERGE (a:Asset {symbol: $symbol})
    WITH a
    UNWIND $rows AS row
      MERGE (c:Candle {symbol: $symbol, timeframe: $timeframe, time: row.time})
      SET c.open = row.open,
          c.high = row.high,
          c.low = row.low,
          c.close = row.close,
          c.volume = row.volume
      MERGE (a)-[:HAS_CANDLE {timeframe: $timeframe}]->(c)
    """
    kg.write(query, {"symbol": symbol, "timeframe": timeframe, "rows": subset})
    return len(subset)


def _sync_signals(kg: Neo4jKG, symbol: str, baseline_predictions_path: Path, limit: int) -> int:
    if not baseline_predictions_path.exists():
        return 0
    frame = pd.read_csv(baseline_predictions_path)
    if frame.empty:
        return 0
    frame["time"] = pd.to_datetime(frame["time"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["time"]).sort_values("time")
    if limit > 0:
        frame = frame.tail(limit)
    rows = []
    for _, row in frame.iterrows():
        rows.append(
            {
                "time": row["time"].isoformat(),
                "y_prob": float(row.get("y_prob", 0.0)),
                "y_pred": int(row.get("y_pred", 0)),
                "y_true": int(row.get("y_true", 0)),
                "fold": int(row.get("fold", 0)),
            }
        )
    query = """
    MERGE (a:Asset {symbol: $symbol})
    WITH a
    UNWIND $rows AS row
      MERGE (s:Signal {time: row.time})
      SET s.symbol = $symbol,
          s.y_prob = row.y_prob,
          s.y_pred = row.y_pred,
          s.y_true = row.y_true,
          s.fold = row.fold
      MERGE (a)-[:HAS_SIGNAL]->(s)
    """
    kg.write(query, {"symbol": symbol, "rows": rows})
    return len(rows)


def _sync_news(kg: Neo4jKG, news_path: Path, limit: int) -> int:
    payload = _safe_json_load(news_path)
    if not isinstance(payload, list):
        return 0
    subset = payload[-limit:] if limit > 0 else payload
    rows = []
    for idx, item in enumerate(subset):
        if not isinstance(item, dict):
            continue
        event_time = (
            item.get("created")
            or item.get("updated")
            or item.get("date")
            or item.get("time")
            or f"unknown-{idx}"
        )
        event_id = f"{event_time}-{idx}"
        rows.append(
            {
                "event_id": event_id,
                "time": str(event_time),
                "title": str(item.get("title") or item.get("headline") or ""),
                "keywords": [str(k).lower() for k in (item.get("matched_keywords") or [])],
            }
        )
    query = """
    UNWIND $rows AS row
      MERGE (e:Event {event_id: row.event_id})
      SET e.time = row.time,
          e.title = row.title,
          e.kind = 'news'
      FOREACH (kw IN row.keywords |
        MERGE (k:Keyword {name: kw})
        MERGE (e)-[:HAS_KEYWORD]->(k)
      )
    """
    kg.write(query, {"rows": rows})
    return len(rows)


def _sync_risk_metrics(kg: Neo4jKG, metrics_path: Path) -> bool:
    metrics = _safe_json_load(metrics_path)
    if not isinstance(metrics, dict):
        return False
    run_id = str(metrics.get("generated_at") or metrics.get("timestamp") or "current")
    query = """
    MERGE (r:RiskRun {run_id: $run_id})
    SET r.trades = $trades,
        r.win_rate = $win_rate,
        r.net_pnl_usd = $net_pnl_usd,
        r.max_drawdown_usd = $max_drawdown_usd,
        r.profit_factor = $profit_factor
    """
    kg.write(
        query,
        {
            "run_id": run_id,
            "trades": int(metrics.get("trades") or metrics.get("executed_trades") or 0),
            "win_rate": float(metrics.get("win_rate") or 0.0),
            "net_pnl_usd": float(metrics.get("net_pnl_usd") or 0.0),
            "max_drawdown_usd": float(metrics.get("max_drawdown_usd") or 0.0),
            "profit_factor": float(metrics.get("profit_factor") or 0.0),
        },
    )
    return True


def run_sync(args: argparse.Namespace) -> None:
    cfg = dotenv_values(args.env_file)
    uri = (args.neo4j_uri or cfg.get("NEO4J_URI") or "").strip()
    user = (args.neo4j_user or cfg.get("NEO4J_USER") or "").strip()
    password = (args.neo4j_password or cfg.get("NEO4J_PASSWORD") or "").strip()
    database = (args.neo4j_database or cfg.get("NEO4J_DATABASE") or "neo4j").strip()
    if not uri or not user or not password:
        raise ValueError("NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD são obrigatórios.")

    kg = Neo4jKG(uri=uri, user=user, password=password, database=database)
    try:
        _create_constraints(kg)
        candles_synced = 0
        candles_synced += _sync_candles(kg, args.symbol, "M5", args.data_dir / "xauusd_m5.json", args.candle_limit)
        candles_synced += _sync_candles(kg, args.symbol, "H1", args.data_dir / "xauusd_h1.json", args.candle_limit)
        candles_synced += _sync_candles(kg, args.symbol, "D1", args.data_dir / "xauusd_d1.json", args.candle_limit)

        signals_synced = _sync_signals(
            kg=kg,
            symbol=args.symbol,
            baseline_predictions_path=args.data_dir / "baseline_predictions.csv",
            limit=args.signal_limit,
        )
        events_synced = _sync_news(kg, args.data_dir / "benzinga_relevant_news.json", args.news_limit)
        risk_synced = _sync_risk_metrics(kg, args.data_dir / "risk_execution_metrics.json")

        print("✅ Neo4j sync concluído")
        print(f"   candles={candles_synced} | signals={signals_synced} | events={events_synced} | risk={int(risk_synced)}")
    finally:
        kg.close()


def run_query(args: argparse.Namespace) -> None:
    cfg = dotenv_values(args.env_file)
    uri = (args.neo4j_uri or cfg.get("NEO4J_URI") or "").strip()
    user = (args.neo4j_user or cfg.get("NEO4J_USER") or "").strip()
    password = (args.neo4j_password or cfg.get("NEO4J_PASSWORD") or "").strip()
    database = (args.neo4j_database or cfg.get("NEO4J_DATABASE") or "neo4j").strip()
    if not uri or not user or not password:
        raise ValueError("NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD são obrigatórios.")

    kg = Neo4jKG(uri=uri, user=user, password=password, database=database)
    try:
        query = args.cypher.strip()
        if not query:
            query = """
            MATCH (a:Asset {symbol: $symbol})-[:HAS_SIGNAL]->(s:Signal)
            RETURN s.time AS time, s.y_prob AS y_prob, s.y_pred AS y_pred, s.y_true AS y_true
            ORDER BY s.time DESC
            LIMIT $limit
            """
        rows = kg.read(query, {"symbol": args.symbol, "limit": args.limit})
        print(json.dumps(rows, indent=2, ensure_ascii=False))
    finally:
        kg.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Knowledge Graph Neo4j para Maria Helena.")
    sub = parser.add_subparsers(dest="mode", required=True)

    sync = sub.add_parser("sync", help="Sincroniza dados locais para o Neo4j")
    sync.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    sync.add_argument("--data-dir", type=Path, default=DATA_DIR)
    sync.add_argument("--symbol", type=str, default="XAUUSD")
    sync.add_argument("--candle-limit", type=int, default=3000)
    sync.add_argument("--signal-limit", type=int, default=5000)
    sync.add_argument("--news-limit", type=int, default=2000)
    sync.add_argument("--neo4j-uri", type=str, default="")
    sync.add_argument("--neo4j-user", type=str, default="")
    sync.add_argument("--neo4j-password", type=str, default="")
    sync.add_argument("--neo4j-database", type=str, default="")

    query = sub.add_parser("query", help="Executa consulta no Neo4j")
    query.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    query.add_argument("--symbol", type=str, default="XAUUSD")
    query.add_argument("--limit", type=int, default=20)
    query.add_argument("--cypher", type=str, default="")
    query.add_argument("--neo4j-uri", type=str, default="")
    query.add_argument("--neo4j-user", type=str, default="")
    query.add_argument("--neo4j-password", type=str, default="")
    query.add_argument("--neo4j-database", type=str, default="")

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.mode == "sync":
        run_sync(args)
    else:
        run_query(args)


if __name__ == "__main__":
    main()
