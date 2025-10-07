import pandas as pd
from prophet import Prophet
from datetime import date, timedelta
from predictor.models import Prediction
from Patient.models import PatientHistory  # adjust if different

def _prepare_data():
    # use PatientHistory to build time series
    qs = PatientHistory.objects.values("date").order_by("date")
    df = pd.DataFrame(list(qs))
    if df.empty:
        return None
    df = df.groupby("date").size().reset_index(name="y")
    df.rename(columns={"date": "ds"}, inplace=True)
    return df

def run_daily_forecast():
    df = _prepare_data()
    if df is None: return
    model = Prophet()
    model.fit(df)
    future = model.make_future_dataframe(periods=30, freq="D")  # 30 days ahead
    forecast = model.predict(future)

    for _, row in forecast.tail(30).iterrows():
        Prediction.objects.update_or_create(
            date=row["ds"].date(),
            prediction_type="daily",
            defaults={"predicted_value": float(row["yhat"])}
        )

def run_weekly_forecast():
    df = _prepare_data()
    if df is None: return
    model = Prophet()
    model.fit(df)
    future = model.make_future_dataframe(periods=12, freq="W")
    forecast = model.predict(future)

    for _, row in forecast.tail(12).iterrows():
        Prediction.objects.update_or_create(
            date=row["ds"].date(),
            prediction_type="weekly",
            defaults={"predicted_value": float(row["yhat"])}
        )

def run_monthly_forecast():
    df = _prepare_data()
    if df is None: return
    model = Prophet()
    model.fit(df)
    future = model.make_future_dataframe(periods=6, freq="M")
    forecast = model.predict(future)

    for _, row in forecast.tail(6).iterrows():
        Prediction.objects.update_or_create(
            date=row["ds"].date(),
            prediction_type="monthly",
            defaults={"predicted_value": float(row["yhat"])}
        )
