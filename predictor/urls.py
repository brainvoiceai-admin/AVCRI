from django.urls import path
from . import views

app_name = "predictor"

urlpatterns = [
    path("api/predictions/", views.prediction_api, name="prediction_api"),
    path("dashboard/", views.prediction_dashboard, name="prediction_dashboard"),
]
