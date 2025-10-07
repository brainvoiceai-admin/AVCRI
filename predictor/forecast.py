# predictor/forecast.py
import datetime
from typing import Optional, Dict
import pandas as pd
from django.db import transaction
from prophet import Prophet
from Patient.models import PatientHistory
from .models import Prediction

def _prepare_data() -> Optional[pd.DataFrame]:
    """
    Load history from PatientHistory and produce a DataFrame with columns ['ds','y']
    suitable for Prophet. Here we treat a "session" as unique by the tuple:
      (date, room_no, t_room, treatment)
    This deduplicates rows created because multiple therapists were assigned to the
    same session (same room & slot & treatment), counting the session only once.
    """
    # query the columns we'll need; if a field does not exist, fall back to available ones
    # adjust the selected_fields list if your model has different column names
    selected_fields = ["date", "room_no", "t_room", "treatment"]
    qs = PatientHistory.objects.values(*selected_fields).order_by("date")
    df = pd.DataFrame(list(qs))

    if df.empty:
        return None

    # Ensure the date column is datetime-like
    df["date"] = pd.to_datetime(df["date"])

    # Deduplicate by session keys:
    # - If any of the session columns are missing in the DataFrame (e.g., not present in model),
    #   drop them from the dedupe list so we don't error.
    session_keys = [k for k in ["date", "room_no", "t_room", "treatment"] if k in df.columns]
    # We only want to dedupe by the non-date fields plus date truncated to date (no time)
    # So create a helper 'ds_date' column that is just the date (not datetime)
    df["ds_date"] = df["date"].dt.date

    # Build dedupe subset using the date + other session keys (excluding original 'date')
    dedupe_subset = ["ds_date"] + [k for k in ["room_no", "t_room", "treatment"] if k in df.columns]

    # Drop duplicates so multiple therapist rows for same session become one
    df_unique_sessions = df.drop_duplicates(subset=dedupe_subset)

    # Now count sessions per date
    counts = df_unique_sessions.groupby("ds_date").size().reset_index(name="y")
    counts.rename(columns={"ds_date": "ds"}, inplace=True)
    # convert ds to datetime
    counts["ds"] = pd.to_datetime(counts["ds"])
    return counts


def _make_future_from_today(model: Prophet, periods: int, freq: str) -> pd.DataFrame:
    """
    Make a future dataframe starting at today (so forecasts are 'upcoming from now').
    If freq is month-end use 'ME' or accept whichever freq you pass.
    Returns DataFrame with a 'ds' column (datetime).
    """
    today = pd.to_datetime(datetime.date.today())
    # create date_range from today with given freq and periods
    idx = pd.date_range(start=today, periods=periods, freq=freq)
    return pd.DataFrame({"ds": idx})

@transaction.atomic
def run_prophet_and_store(
    freq: str = "D",
    periods: int = 30,
    prediction_type: str = "daily",
    overwrite: bool = True,
    outlier_threshold: Optional[float] = 1000.0,
) -> Dict:
    """
    Train Prophet on history and store `periods` forecasts using frequency `freq`.
    - freq: pandas frequency string, e.g. "D", "W", "ME" (month end)
    - periods: number of future points to generate
    - prediction_type: "daily"|"weekly"|"monthly" (used in Prediction.prediction_type)
    - overwrite: if True delete existing future predictions for that type (date >= today)
    - outlier_threshold: skip saving any rounded forecast > threshold (set None to disable)
    """
    df = _prepare_data()
    if df is None:
        return {"status": "no_history", "stored": 0, "skipped_missing": 0, "skipped_outliers": 0}

    # Fit Prophet model
    model = Prophet(daily_seasonality=True, weekly_seasonality=True, yearly_seasonality=True)
    model.fit(df)

    # Build future starting from today so "upcoming" forecasts align with real upcoming dates
    future = _make_future_from_today(model, periods=periods, freq=freq)

    # Predict
    forecast = model.predict(future)

    # Optionally remove existing future predictions of this type (from today onward)
    if overwrite:
        Prediction.objects.filter(prediction_type=prediction_type, date__gte=datetime.date.today()).delete()

    stored = 0
    skipped_missing = 0
    skipped_outliers = 0

    # iterate rows in forecast (in chronological order)
    for _, row in forecast.iterrows():
        # row['ds'] is pandas Timestamp
        dt = row["ds"].date()

        # pick numeric yhat values; treat NaN as None
        yhat = None
        if not pd.isna(row.get("yhat")):
            try:
                yhat = int(round(float(row["yhat"])))
            except Exception:
                yhat = None

        if yhat is None:
            skipped_missing += 1
            continue

        # skip outliers if threshold provided
        if outlier_threshold is not None and yhat > outlier_threshold:
            skipped_outliers += 1
            continue

        # yhat_lower / yhat_upper may be NaN
        yhat_lower = None
        if not pd.isna(row.get("yhat_lower")):
            try:
                yhat_lower = int(round(float(row["yhat_lower"])))
            except Exception:
                yhat_lower = None

        yhat_upper = None
        if not pd.isna(row.get("yhat_upper")):
            try:
                yhat_upper = int(round(float(row["yhat_upper"])))
            except Exception:
                yhat_upper = None

        # store (creates or updates)
        Prediction.objects.update_or_create(
            prediction_type=prediction_type,
            date=dt,
            defaults={
                "predicted_value": yhat,
                "yhat_lower": yhat_lower,
                "yhat_upper": yhat_upper,
            },
        )
        stored += 1

    return {
        "status": "ok",
        "stored": stored,
        "skipped_missing": skipped_missing,
        "skipped_outliers": skipped_outliers,
    }
