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
    Load history from PatientHistory and produce a DataFrame with columns ['ds','y'].
    A "session" is unique by (date, room_no, t_room, treatment), so multiple therapists
    on the same treatment count as one.
    """
    selected_fields = ["date", "room_no", "t_room", "treatment"]
    qs = PatientHistory.objects.values(*selected_fields).order_by("date")
    df = pd.DataFrame(list(qs))
    if df.empty:
        return None

    df["date"] = pd.to_datetime(df["date"])
    df["ds_date"] = df["date"].dt.date
    dedupe_subset = ["ds_date"] + [k for k in ["room_no", "t_room", "treatment"] if k in df.columns]
    df_unique = df.drop_duplicates(subset=dedupe_subset)

    counts = df_unique.groupby("ds_date").size().reset_index(name="y")
    counts.rename(columns={"ds_date": "ds"}, inplace=True)
    counts["ds"] = pd.to_datetime(counts["ds"])
    return counts


def _make_future_from_today(model: Prophet, periods: int, freq: str) -> pd.DataFrame:
    """
    Generate future dates starting from today.
    """
    today = pd.to_datetime(datetime.date.today())
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
    Train Prophet and store predictions.
    """
    df = _prepare_data()
    if df is None:
        return {"status": "no_history", "stored": 0, "skipped_missing": 0, "skipped_outliers": 0}

    model = Prophet(daily_seasonality=True, weekly_seasonality=True, yearly_seasonality=True)
    model.fit(df)

    future = _make_future_from_today(model, periods=periods, freq=freq)
    forecast = model.predict(future)

    if overwrite:
        Prediction.objects.filter(prediction_type=prediction_type, date__gte=datetime.date.today()).delete()

    stored = skipped_missing = skipped_outliers = 0
    for _, row in forecast.iterrows():
        dt = row["ds"].date()

        yhat = None
        if not pd.isna(row.get("yhat")):
            try:
                yhat = int(round(float(row["yhat"])))
            except Exception:
                yhat = None

        if yhat is None:
            skipped_missing += 1
            continue
        if outlier_threshold is not None and yhat > outlier_threshold:
            skipped_outliers += 1
            continue

        yhat_lower = None
        yhat_upper = None
        if not pd.isna(row.get("yhat_lower")):
            try:
                yhat_lower = int(round(float(row["yhat_lower"])))
            except Exception:
                pass
        if not pd.isna(row.get("yhat_upper")):
            try:
                yhat_upper = int(round(float(row["yhat_upper"])))
            except Exception:
                pass

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
