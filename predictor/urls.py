from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

app_name = "predictor"

# Create router for API views
router = DefaultRouter()

urlpatterns = [
    # Legacy API endpoint (for backward compatibility)
    path("api/predictions/", views.prediction_api, name="prediction_api"),
    
    # Dashboard view
    path("dashboard/", views.prediction_dashboard, name="prediction_dashboard"),
    
    # REST API endpoints (order matters - more specific patterns first)
    path("api/v1/predictions/summary/", views.PredictionSummaryAPIView.as_view(), name="prediction_summary"),
    path("api/v1/predictions/export/", views.ExportPredictionsAPIView.as_view(), name="export_predictions"),
    path("api/v1/predictions/<int:pk>/", views.PredictionDetailAPIView.as_view(), name="prediction_detail"),
    path("api/v1/predictions/", views.PredictionListAPIView.as_view(), name="prediction_list"),
    
    # Forecast run endpoints
    path("api/v1/forecast-runs/", views.ForecastRunListAPIView.as_view(), name="forecast_run_list"),
    path("api/v1/forecast-runs/<int:pk>/", views.ForecastRunDetailAPIView.as_view(), name="forecast_run_detail"),
    path("api/v1/forecast-runs/trigger/", views.TriggerForecastAPIView.as_view(), name="trigger_forecast"),
]
