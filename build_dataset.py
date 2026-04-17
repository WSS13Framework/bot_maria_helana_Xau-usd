import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from benzinga_filter import DEFAULT_RELEVANCE_KEYWORDS
from external_flag_engine import add_exogenous_shock_features

DATA_DIR = Path("/root/maria-helena/data")
DEFAULT_OUTPUT = DATA_DIR / "xauusd_feature_table.csv"
DEFAULT_METADATA_OUTPUT = DATA_DIR / "xauusd_feature_table_meta.json"


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def _read_candle_frame(path: Path, prefix: str) -> pd.DataFrame:
    candles = _read_json(path)
    if not isinstance(candles, list):
        raise ValueError(f"Candle file must contain a JSON list: {path}")

    frame = pd.DataFrame(candles)
    required = {"time", "open", "high", "low", "close", "volume"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Missing columns in {path}: {sorted(missing)}")

    frame["time"] = pd.to_datetime(frame["time"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["time"]).sort_values("time").drop_duplicates("time")
    rename_map = {column: f"{prefix}_{column}" for column in ("open", "high", "low", "close", "volume")}
    frame = frame.rename(columns=rename_map)
    return frame[["time", *rename_map.values()]]


def _build_macro_frame(macro_snapshot_path: Path) -> pd.DataFrame:
    if not macro_snapshot_path.exists():
        return pd.DataFrame(columns=["time", "macro_dxy_yahoo", "macro_vix_yahoo", "macro_us10y_fred", "macro_dxy_fred_proxy"])

    snapshot = _read_json(macro_snapshot_path)
    if not isinstance(snapshot, dict):
        return pd.DataFrame(columns=["time", "macro_dxy_yahoo", "macro_vix_yahoo", "macro_us10y_fred", "macro_dxy_fred_proxy"])

    def _extract_time() -> pd.Timestamp | None:
        candidates = [
            snapshot.get("dxy_selected", {}).get("time"),
            snapshot.get("vix_selected", {}).get("time"),
            snapshot.get("us10y_selected", {}).get("time"),
            snapshot.get("dxy_yahoo", {}).get("time"),
            snapshot.get("vix_yahoo", {}).get("time"),
            snapshot.get("collected_at"),
        ]
        for candidate in candidates:
            ts = pd.to_datetime(candidate, utc=True, errors="coerce")
            if pd.notna(ts):
                return ts
        return None

    snapshot_time = _extract_time()
    if snapshot_time is None:
        return pd.DataFrame(columns=["time", "macro_dxy_yahoo", "macro_vix_yahoo", "macro_us10y_fred", "macro_dxy_fred_proxy"])

    dxy_selected = snapshot.get("dxy_selected", {})
    vix_selected = snapshot.get("vix_selected", {})
    us10y_selected = snapshot.get("us10y_selected", {})
    row = {
        "time": snapshot_time,
        # Keep legacy column names for compatibility, but fill using selected source.
        "macro_dxy_yahoo": dxy_selected.get("value", snapshot.get("dxy_yahoo", {}).get("value")),
        "macro_vix_yahoo": vix_selected.get("value", snapshot.get("vix_yahoo", {}).get("value")),
        "macro_us10y_fred": us10y_selected.get("value", snapshot.get("us10y_fred", {}).get("value")),
        "macro_dxy_fred_proxy": snapshot.get("dxy_fred_proxy", {}).get("value"),
        "macro_dxy_selected": dxy_selected.get("value"),
        "macro_vix_selected": vix_selected.get("value"),
        "macro_us10y_selected": us10y_selected.get("value"),
        "macro_premium_enabled": int(bool(snapshot.get("premium_macro_status", {}).get("enabled"))),
        "macro_premium_error": str(snapshot.get("premium_macro_status", {}).get("error") or ""),
    }
    return pd.DataFrame([row]).sort_values("time")


def _build_news_events(news_path: Path) -> pd.DataFrame:
    if not news_path.exists():
        return pd.DataFrame(columns=["time", "matched_keywords"])

    payload = _read_json(news_path)
    if not isinstance(payload, list):
        return pd.DataFrame(columns=["time", "matched_keywords"])

    rows: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        event_time = (
            item.get("created")
            or item.get("updated")
            or item.get("date")
            or item.get("time")
            or item.get("published")
        )
        ts = pd.to_datetime(event_time, utc=True, errors="coerce")
        if pd.isna(ts):
            continue

        keywords = item.get("matched_keywords", [])
        if not isinstance(keywords, list):
            keywords = []
        rows.append({"time": ts, "matched_keywords": [str(k).lower() for k in keywords]})

    if not rows:
        return pd.DataFrame(columns=["time", "matched_keywords"])

    news_frame = pd.DataFrame(rows).sort_values("time").reset_index(drop=True)
    return news_frame


def _build_macro_events_frame(events_path: Path) -> pd.DataFrame:
    columns = [
        "time",
        "macro_event_count_4h",
        "macro_event_high_impact_4h",
        "macro_event_usd_4h",
        "macro_event_gold_relevant_4h",
        "macro_event_positive_surprise_4h",
        "macro_event_negative_surprise_4h",
        "macro_event_abs_surprise_4h",
    ]
    if not events_path.exists():
        return pd.DataFrame(columns=columns)

    payload = _read_json(events_path)
    if not isinstance(payload, dict):
        return pd.DataFrame(columns=columns)
    raw_events = payload.get("events", [])

    event_items: list[dict[str, Any]] = []
    if isinstance(raw_events, list):
        event_items = [item for item in raw_events if isinstance(item, dict)]
    elif isinstance(raw_events, dict):
        event_items = [item for item in raw_events.values() if isinstance(item, dict)]

    if not event_items:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, Any]] = []
    for item in event_items:
        if not isinstance(item, dict):
            continue
        ts = pd.to_datetime(item.get("time") or item.get("event_time"), utc=True, errors="coerce")
        if pd.isna(ts):
            continue
        currency = str(item.get("currency") or "").upper()
        category = str(item.get("category") or "").upper()
        event_name = str(item.get("event") or "").upper()
        impact_score = float(pd.to_numeric(item.get("impact_score"), errors="coerce") or 0.0)
        surprise = float(pd.to_numeric(item.get("surprise"), errors="coerce") or 0.0)
        abs_surprise = float(pd.to_numeric(item.get("abs_surprise"), errors="coerce") or abs(surprise))

        gold_relevant = int(
            ("GOLD" in category)
            or ("USD" in currency)
            or any(keyword in event_name for keyword in ("CPI", "NFP", "FOMC", "RATE", "INFLATION"))
        )
        rows.append(
            {
                "time": ts,
                "event_count": 1,
                "high_impact": int(impact_score >= 0.8),
                "usd_related": int(currency == "USD"),
                "gold_relevant": gold_relevant,
                "positive_surprise": int(surprise > 0),
                "negative_surprise": int(surprise < 0),
                "abs_surprise": abs_surprise,
            }
        )

    if not rows:
        return pd.DataFrame(columns=columns)

    events = pd.DataFrame(rows).sort_values("time").reset_index(drop=True)
    out = events[["time"]].copy()
    base_times_ns = events["time"].astype("int64").to_numpy()
    four_hours_ns = int(pd.Timedelta(hours=4).value)

    right_indices = np.searchsorted(base_times_ns, base_times_ns, side="right")
    left_4h = np.searchsorted(base_times_ns, base_times_ns - four_hours_ns, side="right")

    def _window_sum(values: np.ndarray) -> np.ndarray:
        cumsum = np.cumsum(values.astype(float))
        counts = np.zeros_like(cumsum, dtype=float)
        valid = right_indices > 0
        counts[valid] = cumsum[right_indices[valid] - 1]
        left_valid = left_4h > 0
        counts[left_valid] -= cumsum[left_4h[left_valid] - 1]
        return counts

    out["macro_event_count_4h"] = _window_sum(events["event_count"].to_numpy())
    out["macro_event_high_impact_4h"] = _window_sum(events["high_impact"].to_numpy())
    out["macro_event_usd_4h"] = _window_sum(events["usd_related"].to_numpy())
    out["macro_event_gold_relevant_4h"] = _window_sum(events["gold_relevant"].to_numpy())
    out["macro_event_positive_surprise_4h"] = _window_sum(events["positive_surprise"].to_numpy())
    out["macro_event_negative_surprise_4h"] = _window_sum(events["negative_surprise"].to_numpy())
    out["macro_event_abs_surprise_4h"] = _window_sum(events["abs_surprise"].to_numpy())
    return out


def _build_global_context_frame(global_context_path: Path, structural_path: Path) -> pd.DataFrame:
    context_frames: list[pd.DataFrame] = []
    for path in (global_context_path, structural_path):
        if not path.exists():
            continue
        frame = pd.read_csv(path)
        if "time" not in frame.columns:
            continue
        frame["time"] = pd.to_datetime(frame["time"], utc=True, errors="coerce")
        frame = frame.dropna(subset=["time"]).sort_values("time").drop_duplicates("time")
        context_frames.append(frame)

    if not context_frames:
        return pd.DataFrame(columns=["time"])

    merged = context_frames[0]
    for frame in context_frames[1:]:
        merged = merged.merge(frame, on="time", how="outer")
    merged = merged.sort_values("time").ffill().bfill().reset_index(drop=True)
    return merged


def _add_news_window_features(base_frame: pd.DataFrame, news_events: pd.DataFrame) -> pd.DataFrame:
    frame = base_frame.copy()
    frame["news_count_1h"] = 0
    frame["news_count_4h"] = 0

    for keyword in DEFAULT_RELEVANCE_KEYWORDS:
        frame[f"news_kw_{keyword}_4h"] = 0

    if news_events.empty:
        return frame

    base_times_ns = frame["time"].astype("int64").to_numpy()
    news_times_ns = news_events["time"].astype("int64").to_numpy()
    one_hour_ns = int(pd.Timedelta(hours=1).value)
    four_hours_ns = int(pd.Timedelta(hours=4).value)

    cumulative_total = np.arange(1, len(news_events) + 1, dtype=np.int64)
    keyword_flags: dict[str, np.ndarray] = {}
    keyword_cumsum: dict[str, np.ndarray] = {}
    for keyword in DEFAULT_RELEVANCE_KEYWORDS:
        flags = news_events["matched_keywords"].apply(lambda kws: int(keyword in kws)).to_numpy(dtype=np.int64)
        keyword_flags[keyword] = flags
        keyword_cumsum[keyword] = np.cumsum(flags)

    right_indices = np.searchsorted(news_times_ns, base_times_ns, side="right")
    left_1h = np.searchsorted(news_times_ns, base_times_ns - one_hour_ns, side="right")
    left_4h = np.searchsorted(news_times_ns, base_times_ns - four_hours_ns, side="right")

    def _window_counts(cumsum: np.ndarray, left: np.ndarray, right: np.ndarray) -> np.ndarray:
        counts = np.zeros_like(right, dtype=np.int64)
        valid = right > 0
        counts[valid] = cumsum[right[valid] - 1]
        left_valid = left > 0
        counts[left_valid] -= cumsum[left[left_valid] - 1]
        return counts

    frame["news_count_1h"] = _window_counts(cumulative_total, left_1h, right_indices)
    frame["news_count_4h"] = _window_counts(cumulative_total, left_4h, right_indices)

    for keyword in DEFAULT_RELEVANCE_KEYWORDS:
        frame[f"news_kw_{keyword}_4h"] = _window_counts(keyword_cumsum[keyword], left_4h, right_indices)

    return frame


def build_dataset(
    m5_path: Path,
    h1_path: Path,
    d1_path: Path,
    macro_snapshot_path: Path,
    news_path: Path,
    global_context_path: Path | None = None,
    structural_context_path: Path | None = None,
    macro_events_path: Path | None = None,
    exogenous_shock_threshold: float = 0.55,
) -> pd.DataFrame:
    m5_frame = _read_candle_frame(m5_path, prefix="m5")
    h1_frame = _read_candle_frame(h1_path, prefix="h1")
    d1_frame = _read_candle_frame(d1_path, prefix="d1")

    dataset = pd.merge_asof(
        m5_frame.sort_values("time"),
        h1_frame.sort_values("time"),
        on="time",
        direction="backward",
    )
    dataset = pd.merge_asof(
        dataset.sort_values("time"),
        d1_frame.sort_values("time"),
        on="time",
        direction="backward",
    )

    macro_frame = _build_macro_frame(macro_snapshot_path)
    if not macro_frame.empty:
        dataset = pd.merge_asof(
            dataset.sort_values("time"),
            macro_frame.sort_values("time"),
            on="time",
            direction="backward",
        )
    else:
        dataset["macro_dxy_yahoo"] = np.nan
        dataset["macro_vix_yahoo"] = np.nan
        dataset["macro_us10y_fred"] = np.nan
        dataset["macro_dxy_fred_proxy"] = np.nan

    news_events = _build_news_events(news_path)
    dataset = _add_news_window_features(dataset, news_events)
    if macro_events_path and macro_events_path.exists():
        macro_events = _build_macro_events_frame(macro_events_path)
        if not macro_events.empty:
            dataset = pd.merge_asof(
                dataset.sort_values("time"),
                macro_events.sort_values("time"),
                on="time",
                direction="backward",
            )
        else:
            dataset["macro_event_count_4h"] = 0.0
            dataset["macro_event_high_impact_4h"] = 0.0
            dataset["macro_event_usd_4h"] = 0.0
            dataset["macro_event_gold_relevant_4h"] = 0.0
            dataset["macro_event_positive_surprise_4h"] = 0.0
            dataset["macro_event_negative_surprise_4h"] = 0.0
            dataset["macro_event_abs_surprise_4h"] = 0.0
    else:
        dataset["macro_event_count_4h"] = 0.0
        dataset["macro_event_high_impact_4h"] = 0.0
        dataset["macro_event_usd_4h"] = 0.0
        dataset["macro_event_gold_relevant_4h"] = 0.0
        dataset["macro_event_positive_surprise_4h"] = 0.0
        dataset["macro_event_negative_surprise_4h"] = 0.0
        dataset["macro_event_abs_surprise_4h"] = 0.0

    dataset["h1_close_to_m5_close"] = dataset["h1_close"] / dataset["m5_close"]
    dataset["d1_close_to_m5_close"] = dataset["d1_close"] / dataset["m5_close"]
    dataset["m5_log_return_1"] = np.log(dataset["m5_close"]).diff()
    dataset["m5_log_return_12"] = np.log(dataset["m5_close"]).diff(12)
    dataset["m5_range"] = (dataset["m5_high"] - dataset["m5_low"]) / dataset["m5_close"]

    if global_context_path and global_context_path.exists():
        global_context = pd.read_csv(global_context_path)
        if "time" in global_context.columns:
            global_context["time"] = pd.to_datetime(global_context["time"], utc=True, errors="coerce")
            global_context = (
                global_context.dropna(subset=["time"])
                .sort_values("time")
                .drop_duplicates("time")
            )
            dataset = pd.merge_asof(
                dataset.sort_values("time"),
                global_context.sort_values("time"),
                on="time",
                direction="backward",
            )

    if structural_context_path and structural_context_path.exists():
        structural_context = pd.read_csv(structural_context_path)
        if "time" in structural_context.columns:
            structural_context["time"] = pd.to_datetime(
                structural_context["time"], utc=True, errors="coerce"
            )
            structural_context = (
                structural_context.dropna(subset=["time"])
                .sort_values("time")
                .drop_duplicates("time")
            )
            dataset = pd.merge_asof(
                dataset.sort_values("time"),
                structural_context.sort_values("time"),
                on="time",
                direction="backward",
            )

    dataset = add_exogenous_shock_features(
        dataset,
        shock_threshold=exogenous_shock_threshold,
    )
    return dataset


def _save_metadata(frame: pd.DataFrame, output_path: Path) -> None:
    meta = {
        "rows": int(len(frame)),
        "columns": list(frame.columns),
        "time_start": frame["time"].iloc[0].isoformat() if not frame.empty else None,
        "time_end": frame["time"].iloc[-1].isoformat() if not frame.empty else None,
        "null_ratio": {column: float(frame[column].isna().mean()) for column in frame.columns},
    }
    with output_path.open("w", encoding="utf-8") as fp:
        json.dump(meta, fp, ensure_ascii=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build strict as-of feature table for XAUUSD.")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--meta-output", type=Path, default=DEFAULT_METADATA_OUTPUT)
    parser.add_argument("--exogenous-shock-threshold", type=float, default=0.55)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.meta_output.parent.mkdir(parents=True, exist_ok=True)

    dataset = build_dataset(
        m5_path=args.data_dir / "xauusd_m5.json",
        h1_path=args.data_dir / "xauusd_h1.json",
        d1_path=args.data_dir / "xauusd_d1.json",
        macro_snapshot_path=args.data_dir / "macro_snapshot.json",
        news_path=args.data_dir / "benzinga_relevant_news.json",
        global_context_path=args.data_dir / "global_context_daily.csv",
        structural_context_path=args.data_dir / "global_structural_fred.csv",
        macro_events_path=args.data_dir / "macro_events_snapshot.json",
        exogenous_shock_threshold=args.exogenous_shock_threshold,
    )
    dataset.to_csv(args.output, index=False)
    _save_metadata(dataset, args.meta_output)

    print(f"✅ Dataset salvo em {args.output}")
    print(f"   Linhas: {len(dataset)}")
    print(f"   Período: {dataset['time'].iloc[0]} -> {dataset['time'].iloc[-1]}")
    print(f"✅ Metadata salva em {args.meta_output}")


if __name__ == "__main__":
    main()
