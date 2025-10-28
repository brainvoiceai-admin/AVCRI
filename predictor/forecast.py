# predictor/forecast.py
import datetime
from typing import Optional, Dict, Union, List
import pandas as pd
from django.db import transaction
from django.utils import timezone
from prophet import Prophet
from Patient.models import PatientHistory
from .models import Prediction


# ---------------- helpers / data preparation ----------------

def _today_localdate() -> datetime.date:
    """Return current local date using Django timezone utilities."""
    return timezone.localdate()


def _detect_patient_id_field(columns: List[str]) -> Optional[str]:
    """Return a candidate patient id field present in columns or None."""
    candidates = ["preg_no", "pat_reg_no", "patient_id", "reg_no", "register_number"]
    cols_lower = {c.lower(): c for c in columns}
    for cand in candidates:
        if cand.lower() in cols_lower:
            return cols_lower[cand.lower()]
    return None


def _prepare_data(
    aggregate_by: str = "day",
    up_to_date: Optional[Union[str, datetime.date]] = None,
) -> Optional[pd.DataFrame]:
    """
    Load PatientHistory data and return DataFrame ['ds','y'] for Prophet.
    Counts each unique patient once per day (no matter how many therapies/therapists).
    """
    # ensure date field exists
    model_fields = [f.name for f in PatientHistory._meta.get_fields() if hasattr(f, "name")]
    selected_fields = [f for f in ["date", "preg_no", "pat_name"] if f in model_fields]
    if "date" not in selected_fields:
        return None

    qs = PatientHistory.objects.values(*selected_fields).order_by("date")
    df = pd.DataFrame(list(qs))
    if df.empty:
        return None

    # clean date
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df["ds_date"] = df["date"].dt.date

    # cut off if specified
    if up_to_date:
        up_to = pd.to_datetime(up_to_date).date()
        df = df[df["ds_date"] <= up_to]
        if df.empty:
            return None

    # detect patient id
    pid_field = _detect_patient_id_field(df.columns)
    if not pid_field:
        pid_field = "pat_name" if "pat_name" in df.columns else None

    if not pid_field:
        return None  # cannot compute without any patient id

    # Deduplicate by (date, patient)
    df_unique = df.drop_duplicates(subset=["ds_date", pid_field]).copy()

    # Aggregate by day/week/month
    agg = aggregate_by.lower()
    if agg == "month":
        df_unique["month"] = pd.to_datetime(df_unique["ds_date"]).dt.to_period("M")
        counts = df_unique.groupby("month").size().reset_index(name="y")
        counts["ds"] = counts["month"].dt.to_timestamp()
    elif agg == "week":
        # Use start of week (Monday) for the period start
        df_unique["week"] = pd.to_datetime(df_unique["ds_date"]).dt.to_period("W").apply(lambda p: p.start_time)
        counts = df_unique.groupby("week").size().reset_index(name="y")
        counts.rename(columns={"week": "ds"}, inplace=True)
        counts["ds"] = pd.to_datetime(counts["ds"])
    else:
        counts = df_unique.groupby("ds_date").size().reset_index(name="y")
        counts.rename(columns={"ds_date": "ds"}, inplace=True)
        counts["ds"] = pd.to_datetime(counts["ds"])

    counts = counts.sort_values("ds").reset_index(drop=True)

    # Prophet expects columns ['ds','y'] and ds as datetimes
    return counts[["ds", "y"]]


def _fit_prophet_safe(df: pd.DataFrame, daily_seasonality: bool = True) -> Optional[Prophet]:
    """Try to fit a Prophet model, return model or None on failure."""
    try:
        model = Prophet(daily_seasonality=daily_seasonality, weekly_seasonality=True, yearly_seasonality=True)
        model.fit(df)
        return model
    except Exception:
        return None


def _make_future_between(start_date: Union[str, datetime.date], end_date: Union[str, datetime.date], freq: str):
    """Return a DataFrame with a 'ds' column between start and end inclusive at given freq."""
    s = pd.to_datetime(start_date)
    e = pd.to_datetime(end_date)
    if e < s:
        raise ValueError("end_date must be >= start_date")
    idx = pd.date_range(start=s, end=e, freq=freq)
    return pd.DataFrame({"ds": idx})


# ---------------- store predictions ----------------

def _store_forecast_rows(
    forecast_df: pd.DataFrame,
    prediction_type: str,
    start_date: datetime.date,
    end_date: datetime.date,
    outlier_threshold: Optional[float] = 1000.0,
) -> Dict:
    """
    Persist forecast rows into Prediction model for dates between start_date and end_date.
    Returns stats dict: stored, skipped_missing, skipped_outliers
    """
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

            try:
                ylow = int(round(float(row.get("yhat_lower", None)))) if not pd.isna(row.get("yhat_lower")) else None
                yhigh = int(round(float(row.get("yhat_upper", None)))) if not pd.isna(row.get("yhat_upper")) else None
            except Exception:
                ylow = yhigh = None

            Prediction.objects.update_or_create(
                prediction_type=prediction_type,
                date=dt,
                defaults={"predicted_value": yhat, "yhat_lower": ylow, "yhat_upper": yhigh},
            )
            stored += 1

    return {
        "stored": stored,
        "skipped_missing": skipped_missing,
        "skipped_outliers": skipped_outliers,
    }


# ---------------- core forecasting ----------------

def run_prophet_for_date_range(
    start_date: Union[str, datetime.date],
    end_date: Union[str, datetime.date],
    aggregate_by: str = "day",
    freq: Optional[str] = None,
    prediction_type: Optional[str] = None,
    overwrite: bool = True,
    outlier_threshold: Optional[float] = 1000.0,
    up_to_history_date: Optional[Union[str, datetime.date]] = None,
) -> Dict:
    """
    Fit Prophet on historical PatientHistory (up to up_to_history_date if provided),
    forecast between start_date and end_date (inclusive) with frequency 'freq',
    and persist results labelled with prediction_type.

    aggregate_by: 'day'|'week'|'month' to build history series.
    freq: pandas freq string (e.g. 'D','W-MON','MS','M')
    """
    agg = aggregate_by.lower()
    if freq is None:
        freq = "D" if agg == "day" else ("W-MON" if agg == "week" else "MS")
    if prediction_type is None:
        prediction_type = "daily_avg" if agg == "day" else ("weekly_total" if agg == "week" else "monthly_total")

    df = _prepare_data(aggregate_by=agg, up_to_date=up_to_history_date)
    if df is None or df.empty:
        return {"status": "no_history", "stored": 0}

    model = _fit_prophet_safe(df, daily_seasonality=(agg == "day"))
    if not model:
        return {"status": "fit_failed", "stored": 0}

    future = _make_future_between(start_date, end_date, freq)
    forecast = model.predict(future)

    sd = pd.to_datetime(start_date).date()
    ed = pd.to_datetime(end_date).date()
    if overwrite:
        Prediction.objects.filter(prediction_type=prediction_type, date__gte=sd, date__lte=ed).delete()

    stats = _store_forecast_rows(forecast, prediction_type, sd, ed, outlier_threshold)
    return {"status": "ok", **stats, "prediction_type": prediction_type}


# ---------------- wrappers ----------------

def forecast_daily_average(start_date, end_date, **kwargs):
    """Convenience wrapper for daily forecasts."""
    return run_prophet_for_date_range(start_date, end_date, "day", "D", "daily", **kwargs)


def forecast_weekly_totals(start_week, end_week, **kwargs):
    """Convenience wrapper for weekly forecasts (weeks starting Monday)."""
    return run_prophet_for_date_range(start_week, end_week, "week", "W-MON", "weekly", **kwargs)


def forecast_monthly_totals(start_month, end_month, **kwargs):
    """Convenience wrapper for monthly forecasts (month-start)."""
    return run_prophet_for_date_range(start_month, end_month, "month", "MS", "monthly", **kwargs)


# ---------------- compatibility wrapper for management commands ----------------

def run_prophet_and_store(
    freq: str = "D",
    periods: int = 30,
    prediction_type: Optional[str] = None,
    overwrite: bool = True,
    outlier_threshold: Optional[float] = 1000.0,
):
    """
    Backwards-compatible wrapper used by management commands.
    - freq: pandas/prophet freq string like "D", "W-MON", "MS", "M".
    - periods: how many freq-units ahead to forecast.
    - prediction_type: optional string recorded in Prediction (if None, underlying function will pick).
    """
    # determine start = today (local)
    today = _today_localdate()

    # try to compute end_date using pandas date_range for correct freq semantics
    try:
        rng = pd.date_range(start=today, periods=periods, freq=freq)
        end_date = rng[-1].date()
    except Exception:
        # fallback approximations
        if str(freq).upper().startswith("D"):
            end_date = today + datetime.timedelta(days=periods - 1)
        elif str(freq).upper().startswith("W"):
            end_date = today + datetime.timedelta(weeks=periods)
        else:
            # approximate months by adding 30 days per period
            end_date = today + datetime.timedelta(days=30 * periods)

    # choose aggregate_by from freq for compatibility
    agg = "day" if str(freq).upper().startswith("D") else ("week" if str(freq).upper().startswith("W") else "month")

    return run_prophet_for_date_range(
        start_date=today,
        end_date=end_date,
        aggregate_by=agg,
        freq=freq,
        prediction_type=prediction_type,
        overwrite=overwrite,
        outlier_threshold=outlier_threshold,
    )