# predictor/forecast.py
import datetime
from typing import Optional, Dict, Union, List, Any, Tuple
import pandas as pd
from django.db import transaction, connections
from django.utils import timezone
import logging
import numpy as _np
if not hasattr(_np, "float_"):
    _np.float_ = _np.float64
# Prophet import - ensure 'prophet' is installed in your env
from prophet import Prophet

# Prefer Scheduling from external MySql_Data_pull. Fallback to PatientHistory if not available.
try:
    from MySql_Data_pull.models import Scheduling as ExternalScheduling
except Exception:
    ExternalScheduling = None

try:
    from Patient.models import PatientHistory
except Exception:
    PatientHistory = None

from .models import Prediction

logger = logging.getLogger(__name__)

# Database alias for external therapy DB
EXTERNAL_DB_ALIAS = "therapy_db"

# If there is a gap longer than this (days) we'll prefer the contiguous block before the gap
MAX_CONTIG_GAP_DAYS = 30


# ----------------- helpers: load & normalize history -----------------

def _today_localdate() -> datetime.date:
    return timezone.localdate()


def _detect_patient_id_field(columns: List[str]) -> Optional[str]:
    candidates = [
        "preg_no", "pat_reg_no", "patient_id", "reg_no",
        "register_number", "pat_name"
    ]
    cols_lower = {c.lower(): c for c in columns}
    for cand in candidates:
        if cand.lower() in cols_lower:
            return cols_lower[cand.lower()]
    return None


def _safe_query(sql: str, params=None, db_alias: str = EXTERNAL_DB_ALIAS) -> List[Dict[str, Any]]:
    try:
        with connections[db_alias].cursor() as cur:
            cur.execute(sql, params or [])
            cols = [c[0] for c in cur.description] if cur.description else []
            rows = cur.fetchall()
            return [dict(zip(cols, r)) for r in rows]
    except Exception:
        return []


def _load_raw_history(up_to_date: Optional[Union[str, datetime.date]] = None) -> Optional[pd.DataFrame]:
    """
    Try to load history from ExternalScheduling first, then PatientHistory. Returns raw DataFrame.
    """
    df = None

    # Try external model via ORM if available
    try:
        if ExternalScheduling is not None:
            model_fields = [f.name for f in ExternalScheduling._meta.get_fields() if hasattr(f, "name")]
            selected = []
            candidates = ["tdate", "TDate", "pat_reg_no", "PReg_No", "pat_name", "Pat_Name"]
            for cand in candidates:
                matched = next((m for m in model_fields if m.lower() == cand.lower()), None)
                if matched and matched not in selected:
                    selected.append(matched)
            if not any(s.lower() in ("tdate", "date") for s in selected):
                if "tdate" in model_fields:
                    selected.append("tdate")
                elif "date" in model_fields:
                    selected.append("date")
            if selected:
                qs = ExternalScheduling.objects.using(EXTERNAL_DB_ALIAS).values(*selected)
                df = pd.DataFrame(list(qs))
    except Exception:
        logger.exception("ExternalScheduling ORM read failed")

    # Fallback to local PatientHistory
    if (df is None or df.empty) and PatientHistory is not None:
        try:
            model_fields = [f.name for f in PatientHistory._meta.get_fields() if hasattr(f, "name")]
            selected_fields = [f for f in ["date", "preg_no", "pat_name"] if f in model_fields]
            if "date" in selected_fields:
                qs = PatientHistory.objects.values(*selected_fields)
                df = pd.DataFrame(list(qs))
        except Exception:
            logger.exception("PatientHistory ORM read failed")

    # If still empty and external DB accessible, fallback to raw SQL (best-effort)
    if (df is None or df.empty) and ExternalScheduling is not None:
        try:
            rows = _safe_query("SELECT TOP (100000) * FROM Scheduling", db_alias=EXTERNAL_DB_ALIAS)
            if rows:
                df = pd.DataFrame(rows)
        except Exception:
            logger.exception("Raw query fallback failed")

    # apply up_to_date cutoff later in aggregation step
    if df is None or df.empty:
        return None

    return df


def _aggregate_counts_from_raw(df_raw: pd.DataFrame, aggregate_by: str = "day", up_to_date: Optional[Union[str, datetime.date]] = None) -> Optional[pd.DataFrame]:
    """
    Normalize raw df into counts DataFrame with columns ['ds','y'] aggregated by day/week/month.
    """
    if df_raw is None or df_raw.empty:
        return None

    # find date column
    date_cols = [c for c in df_raw.columns if c.lower() in (
        "tdate", "date", "ds", "visit_date", "date_of_visit", "pat_visit_date", "admit_date", "rdate"
    )]
    if not date_cols:
        return None
    date_col = date_cols[0]

    df_raw[date_col] = pd.to_datetime(df_raw[date_col], errors="coerce")
    df_clean = df_raw.dropna(subset=[date_col]).copy()
    if df_clean.empty:
        return None

    df_clean["ds_date"] = df_clean[date_col].dt.date

    pid_field = _detect_patient_id_field(list(df_clean.columns))
    if not pid_field:
        pid_field = "pat_name" if "pat_name" in df_clean.columns else None
    if not pid_field:
        return None

    df_unique = df_clean.drop_duplicates(subset=["ds_date", pid_field]).copy()

    agg = aggregate_by.lower()
    if agg == "month":
        df_unique["month"] = pd.to_datetime(df_unique["ds_date"]).dt.to_period("M")
        counts = df_unique.groupby("month").size().reset_index(name="y")
        counts["ds"] = counts["month"].dt.to_timestamp()
    elif agg == "week":
        df_unique["week"] = pd.to_datetime(df_unique["ds_date"]).dt.to_period("W").apply(lambda p: p.start_time)
        counts = df_unique.groupby("week").size().reset_index(name="y")
        counts.rename(columns={"week": "ds"}, inplace=True)
        counts["ds"] = pd.to_datetime(counts["ds"])
    else:
        counts = df_unique.groupby("ds_date").size().reset_index(name="y")
        counts.rename(columns={"ds_date": "ds"}, inplace=True)
        counts["ds"] = pd.to_datetime(counts["ds"])

    counts = counts.sort_values("ds").reset_index(drop=True)

    # apply up_to_date cutoff if provided
    if up_to_date is not None:
        up_to = pd.to_datetime(up_to_date).date()
        counts = counts[counts["ds"].dt.date <= up_to]
        if counts.empty:
            return None

    return counts[["ds", "y"]]


def get_longest_contiguous_block(counts: pd.DataFrame) -> Tuple[Optional[pd.Timestamp], Optional[pd.Timestamp], pd.DataFrame]:
    """
    Return the start and end Timestamp of the longest contiguous observed block and its DataFrame.
    """
    if counts is None or counts.empty:
        return (None, None, pd.DataFrame(columns=["ds", "y"]))

    # expand to daily index to identify true contiguous days
    daily = counts.set_index("ds").asfreq("D").reset_index()
    daily["has_obs"] = ~daily["y"].isna()

    runs = []
    run_start = None
    run_end = None
    for i, row in daily.iterrows():
        if row["has_obs"]:
            if run_start is None:
                run_start = row["ds"]
            run_end = row["ds"]
        else:
            if run_start is not None:
                runs.append((run_start, run_end))
                run_start = None
                run_end = None

    if run_start is not None:
        runs.append((run_start, run_end))

    if not runs:
        return (None, None, pd.DataFrame(columns=["ds", "y"]))

    best = max(runs, key=lambda r: (r[1].date() - r[0].date()).days)
    start, end = best
    block_df = counts[(counts["ds"] >= start) & (counts["ds"] <= end)].reset_index(drop=True)
    return (start, end, block_df)


def history_diagnostics(aggregate_by: str = "day", up_to_date: Optional[Union[str, datetime.date]] = None) -> Dict[str, Any]:
    """
    Return diagnostics about available history. Useful for debugging.
    """
    raw = _load_raw_history(up_to_date=up_to_date)
    counts = _aggregate_counts_from_raw(raw, aggregate_by=aggregate_by, up_to_date=up_to_date)
    if counts is None or counts.empty:
        return {"status": "no_history", "counts_tail": None}

    first = counts["ds"].iloc[0].date()
    last = counts["ds"].iloc[-1].date()
    n_obs = counts.shape[0]

    daily = counts.set_index("ds").asfreq("D").reset_index()
    daily["has_obs"] = ~daily["y"].isna()
    gaps = []
    in_gap = False
    gap_start = None
    for idx, row in daily.iterrows():
        if not row["has_obs"] and not in_gap:
            in_gap = True
            gap_start = row["ds"].date()
        if row["has_obs"] and in_gap:
            gap_end = (row["ds"].date() - datetime.timedelta(days=1))
            gaps.append({"start": gap_start, "end": gap_end, "days": (gap_end - gap_start).days + 1})
            in_gap = False
            gap_start = None
    if in_gap:
        gap_end = daily["ds"].iloc[-1].date()
        gaps.append({"start": gap_start, "end": gap_end, "days": (gap_end - gap_start).days + 1})

    start, end, block_df = get_longest_contiguous_block(counts)

    return {
        "status": "ok",
        "first_date": str(first),
        "last_date": str(last),
        "n_observed_dates": int(n_obs),
        "gaps": gaps,
        "longest_block_start": str(start.date()) if start is not None else None,
        "longest_block_end": str(end.date()) if end is not None else None,
        "longest_block_length_days": int((end.date() - start.date()).days + 1) if start is not None else 0,
        "counts_tail": counts.tail(15).to_dict(orient="records")
    }


# ----------------- Prophet fitting and storage -----------------

def _fit_prophet_safe(df: pd.DataFrame, daily_seasonality: bool = True) -> Optional[Prophet]:
    try:
        model = Prophet(daily_seasonality=daily_seasonality, weekly_seasonality=True, yearly_seasonality=True)
        model.fit(df)
        return model
    except Exception:
        logger.exception("Prophet fit failed")
        return None


def _make_future_between(start_date: Union[str, datetime.date], end_date: Union[str, datetime.date], freq: str) -> pd.DataFrame:
    s = pd.to_datetime(start_date)
    e = pd.to_datetime(end_date)
    if e < s:
        raise ValueError("end_date must be >= start_date")
    idx = pd.date_range(start=s, end=e, freq=freq)
    return pd.DataFrame({"ds": idx})


def _store_forecast_rows(
    forecast_df: pd.DataFrame,
    prediction_type: str,
    start_date: datetime.date,
    end_date: datetime.date,
    outlier_threshold: Optional[float] = 1000.0,
) -> Dict[str, int]:
    sd = pd.to_datetime(start_date).date()
    ed = pd.to_datetime(end_date).date()
    stored = skipped_missing = skipped_outliers = 0

    with transaction.atomic():
        for _, row in forecast_df.iterrows():
            dt = pd.to_datetime(row["ds"]).date()
            if dt < sd or dt > ed:
                continue

            try:
                yhat = int(round(float(row["yhat"])))
            except Exception:
                skipped_missing += 1
                continue

            if outlier_threshold and yhat > outlier_threshold:
                skipped_outliers += 1
                continue

            ylow = row.get("yhat_lower", None)
            yhigh = row.get("yhat_upper", None)
            try:
                ylow = int(round(float(ylow))) if ylow is not None and not pd.isna(ylow) else None
                yhigh = int(round(float(yhigh))) if yhigh is not None and not pd.isna(yhigh) else None
            except Exception:
                ylow = yhigh = None

            Prediction.objects.update_or_create(
                prediction_type=prediction_type,
                date=dt,
                defaults={"predicted_value": yhat, "yhat_lower": ylow, "yhat_upper": yhigh},
            )
            stored += 1

    return {"stored": stored, "skipped_missing": skipped_missing, "skipped_outliers": skipped_outliers}


def _historical_mean_recent(counts: pd.DataFrame, last_n_days: int = 90) -> Optional[float]:
    """
    Compute simple mean of y over the last N days of counts (ignoring NaNs).
    """
    if counts is None or counts.empty:
        return None
    # ensure sorted
    counts_sorted = counts.sort_values("ds").reset_index(drop=True)
    tail = counts_sorted.tail(last_n_days)
    if tail.empty:
        return None
    return float(tail["y"].mean())


# ----------------- core: choose longest block, fit, forecast, store -----------------

def run_prophet_for_date_range(
    start_date: Union[str, datetime.date],
    end_date: Union[str, datetime.date],
    aggregate_by: str = "day",
    freq: Optional[str] = None,
    prediction_type: Optional[str] = None,
    overwrite: bool = True,
    outlier_threshold: Optional[float] = 1000.0,
    up_to_history_date: Optional[Union[str, datetime.date]] = None,
    # new options for pragmatic fix:
    blend_with_history: bool = True,
    blend_alpha: float = 0.6,
    blend_history_days: int = 90,
) -> Dict[str, Any]:
    """
    Train Prophet on the longest contiguous historical block (to avoid stray test rows),
    forecast between start_date and end_date, persist results, and optionally blend predictions
    with recent historical mean to avoid sudden drops.

    Returns a dict with status, stored counts, and 'history_used_up_to' for transparency.
    """

    agg = aggregate_by.lower()
    if freq is None:
        freq = "D" if agg == "day" else ("W-MON" if agg == "week" else "MS")
    if prediction_type is None:
        prediction_type = "daily_avg" if agg == "day" else ("weekly_total" if agg == "week" else "monthly_total")

    if up_to_history_date is None:
        up_to_history_date = datetime.date(2025, 12, 31)

    # 1) load raw and aggregate
    raw = _load_raw_history(up_to_date=up_to_history_date)
    counts = _aggregate_counts_from_raw(raw, aggregate_by=agg, up_to_date=up_to_history_date)
    if counts is None or counts.empty:
        return {"status": "no_history", "stored": 0, "history_used_up_to": None}

    # 2) find longest contiguous block and use it for training
    start_block, end_block, block_df = get_longest_contiguous_block(counts)
    if start_block is None or end_block is None or block_df is None or block_df.empty:
        return {"status": "no_contiguous_block", "stored": 0, "history_used_up_to": None}

    history_used_up_to = end_block.date()

    # prophet requires columns ds (datetime) and y (numeric)
    train_df = block_df.reset_index(drop=True).copy()
    train_df = train_df[["ds", "y"]]
    # If there are still any gaps inside the block (shouldn't be) fill them with zeros
    train_df = train_df.set_index("ds").asfreq("D", fill_value=0).reset_index()

    model = _fit_prophet_safe(train_df, daily_seasonality=(agg == "day"))
    if model is None:
        return {"status": "fit_failed", "stored": 0, "history_used_up_to": str(history_used_up_to)}

    # 3) make future frame & predict
    future = _make_future_between(start_date, end_date, freq)
    forecast = model.predict(future)

    # 4) optionally blend with recent historical mean to avoid stair-step drops
    if blend_with_history:
        hist_mean = _historical_mean_recent(train_df, last_n_days=blend_history_days)
        if hist_mean is not None:
            # apply blending to forecast DataFrame (yhat, yhat_lower, yhat_upper)
            # blended = alpha * hist_mean + (1 - alpha) * yhat
            alpha = float(blend_alpha)
            alpha = min(max(alpha, 0.0), 1.0)
            # compute blended yhat and approximate CI around blended value
            def blend_row(row):
                try:
                    orig = float(row["yhat"])
                except Exception:
                    return row
                blended = alpha * float(hist_mean) + (1 - alpha) * orig
                row["yhat"] = blended
                # preserve width of interval but center around blended
                try:
                    lower = float(row.get("yhat_lower", blended))
                    upper = float(row.get("yhat_upper", blended))
                    width = (upper - lower) / 2.0
                    row["yhat_lower"] = blended - width
                    row["yhat_upper"] = blended + width
                except Exception:
                    row["yhat_lower"] = blended
                    row["yhat_upper"] = blended
                return row

            forecast = forecast.apply(blend_row, axis=1)

    # 5) store into Prediction model
    sd = pd.to_datetime(start_date).date()
    ed = pd.to_datetime(end_date).date()
    if overwrite:
        Prediction.objects.filter(prediction_type=prediction_type, date__gte=sd, date__lte=ed).delete()

    stats = _store_forecast_rows(forecast, prediction_type, sd, ed, outlier_threshold)
    return {"status": "ok", **stats, "prediction_type": prediction_type, "history_used_up_to": str(history_used_up_to)}


# ----------------- convenience wrappers -----------------

def forecast_daily_average(start_date, end_date, **kwargs):
    return run_prophet_for_date_range(start_date, end_date, "day", "D", "daily", **kwargs)


def forecast_weekly_totals(start_week, end_week, **kwargs):
    return run_prophet_for_date_range(start_week, end_week, "week", "W-MON", "weekly", **kwargs)


def forecast_monthly_totals(start_month, end_month, **kwargs):
    return run_prophet_for_date_range(start_month, end_month, "month", "MS", "monthly", **kwargs)


def run_prophet_and_store(
    freq: str = "D",
    periods: int = 30,
    prediction_type: Optional[str] = None,
    overwrite: bool = True,
    outlier_threshold: Optional[float] = 1000.0,
    blend_with_history: bool = True,
    blend_alpha: float = 0.6,
    blend_history_days: int = 90,
):
    today = _today_localdate()
    try:
        rng = pd.date_range(start=today, periods=periods, freq=freq)
        end_date = rng[-1].date()
    except Exception:
        if str(freq).upper().startswith("D"):
            end_date = today + datetime.timedelta(days=periods - 1)
        elif str(freq).upper().startswith("W"):
            end_date = today + datetime.timedelta(weeks=periods)
        else:
            end_date = today + datetime.timedelta(days=30 * periods)

    agg = "day" if str(freq).upper().startswith("D") else ("week" if str(freq).upper().startswith("W") else "month")
    return run_prophet_for_date_range(
        start_date=today,
        end_date=end_date,
        aggregate_by=agg,
        freq=freq,
        prediction_type=prediction_type,
        overwrite=overwrite,
        outlier_threshold=outlier_threshold,
        up_to_history_date=datetime.date(2025, 12, 31),
        blend_with_history=blend_with_history,
        blend_alpha=blend_alpha,
        blend_history_days=blend_history_days,
    )
