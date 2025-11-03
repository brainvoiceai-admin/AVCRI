# predictor/views.py
from datetime import date, datetime, timedelta
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views import View
from django.db.models import Avg, Min, Max, Count
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import generics
import json
import csv
import threading
from django.core.paginator import Paginator

from .models import Prediction, ForecastRun
from .serializers import (
    PredictionSerializer, ForecastRunSerializer, 
    ForecastRunCreateSerializer, PredictionSummarySerializer
)
from .forecast import run_prophet_for_date_range
from authentication.decorators import admin_required, role_required

VALID = ("daily", "weekly", "monthly")

@require_GET
def prediction_api(request):
    """Legacy API endpoint for backward compatibility"""
    t = request.GET.get("type", "daily").lower()
    if t not in VALID:
        return HttpResponseBadRequest("Invalid type. Use daily|weekly|monthly")

    upcoming_flag = request.GET.get("upcoming")
    qs = Prediction.objects.filter(prediction_type=t).order_by("date")
    if upcoming_flag in ("1","true","True","yes"):
        qs = qs.filter(date__gte=date.today())

    data = []
    for p in qs:
        data.append({
            "date": p.date.isoformat(),
            "prediction_type": p.prediction_type,
            # round to integer before returning (safe if None)
            "predicted_value": int(round(p.predicted_value)) if p.predicted_value is not None else None,
            "yhat_lower": int(round(p.yhat_lower)) if p.yhat_lower is not None else None,
            "yhat_upper": int(round(p.yhat_upper)) if p.yhat_upper is not None else None,
            "actual_value": int(round(p.actual_value)) if getattr(p, "actual_value", None) is not None else None,
        })
    return JsonResponse(data, safe=False)


class PredictionListAPIView(generics.ListAPIView):
    """API endpoint to list predictions with filtering"""
    serializer_class = PredictionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = Prediction.objects.all()
        
        # Filter by prediction type
        prediction_type = self.request.query_params.get('type')
        if prediction_type and prediction_type in VALID:
            queryset = queryset.filter(prediction_type=prediction_type)
        
        # Filter by date range
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        
        if start_date:
            queryset = queryset.filter(date__gte=start_date)
        if end_date:
            queryset = queryset.filter(date__lte=end_date)
        
        # Filter upcoming predictions
        upcoming = self.request.query_params.get('upcoming')
        if upcoming in ('1', 'true', 'True', 'yes'):
            queryset = queryset.filter(date__gte=date.today())
        
        return queryset.order_by('date')


class PredictionDetailAPIView(generics.RetrieveAPIView):
    """API endpoint to get a specific prediction"""
    queryset = Prediction.objects.all()
    serializer_class = PredictionSerializer
    permission_classes = [IsAuthenticated]


class PredictionSummaryAPIView(APIView):
    """API endpoint to get prediction summary statistics"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        prediction_type = request.query_params.get('type', 'daily')
        
        if prediction_type not in VALID:
            return Response(
                {"error": "Invalid prediction type"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        queryset = Prediction.objects.filter(prediction_type=prediction_type)
        
        # If no predictions exist, return empty stats instead of 404
        if not queryset.exists():
            stats = {
                'prediction_type': prediction_type,
                'total_predictions': 0,
                'average_prediction': 0.0,
                'min_prediction': 0.0,
                'max_prediction': 0.0,
                'date_range_start': None,
                'date_range_end': None,
                'last_updated': None
            }
            serializer = PredictionSummarySerializer(stats)
            return Response(serializer.data)
        
        # Calculate statistics
        stats = queryset.aggregate(
            total_predictions=Count('id'),
            average_prediction=Avg('predicted_value'),
            min_prediction=Min('predicted_value'),
            max_prediction=Max('predicted_value'),
            date_range_start=Min('date'),
            date_range_end=Max('date'),
            last_updated=Max('created_at')
        )
        
        stats['prediction_type'] = prediction_type
        
        serializer = PredictionSummarySerializer(stats)
        return Response(serializer.data)


class ForecastRunListAPIView(generics.ListCreateAPIView):
    """API endpoint to list and create forecast runs"""
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return ForecastRunCreateSerializer
        return ForecastRunSerializer

    def get_queryset(self):
        queryset = ForecastRun.objects.all()
        
        # Filter by run type
        run_type = self.request.query_params.get('run_type')
        if run_type:
            queryset = queryset.filter(run_type=run_type)
        
        # Filter by status
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        return queryset.order_by('-started_at')

    def perform_create(self, serializer):
        """Create a new forecast run and start the forecast process"""
        forecast_run = serializer.save(started_by=self.request.user, status='pending')
        
        # Start forecast in background thread
        def run_forecast():
            try:
                forecast_run.status = 'running'
                forecast_run.save()
                
                # Run the forecast based on type
                if forecast_run.run_type == 'daily':
                    result = run_prophet_for_date_range(
                        start_date=forecast_run.start_date,
                        end_date=forecast_run.end_date,
                        aggregate_by='day',
                        freq='D',
                        prediction_type='daily'
                    )
                elif forecast_run.run_type == 'weekly':
                    result = run_prophet_for_date_range(
                        start_date=forecast_run.start_date,
                        end_date=forecast_run.end_date,
                        aggregate_by='week',
                        freq='W-MON',
                        prediction_type='weekly'
                    )
                elif forecast_run.run_type == 'monthly':
                    result = run_prophet_for_date_range(
                        start_date=forecast_run.start_date,
                        end_date=forecast_run.end_date,
                        aggregate_by='month',
                        freq='MS',
                        prediction_type='monthly'
                    )
                elif forecast_run.run_type == 'all':
                    # Run all three types
                    daily_result = run_prophet_for_date_range(
                        start_date=forecast_run.start_date,
                        end_date=forecast_run.end_date,
                        aggregate_by='day',
                        freq='D',
                        prediction_type='daily'
                    )
                    weekly_result = run_prophet_for_date_range(
                        start_date=forecast_run.start_date,
                        end_date=forecast_run.end_date,
                        aggregate_by='week',
                        freq='W-MON',
                        prediction_type='weekly'
                    )
                    monthly_result = run_prophet_for_date_range(
                        start_date=forecast_run.start_date,
                        end_date=forecast_run.end_date,
                        aggregate_by='month',
                        freq='MS',
                        prediction_type='monthly'
                    )
                    
                    # Combine results
                    result = {
                        'status': 'ok',
                        'stored': (daily_result.get('stored', 0) + 
                                 weekly_result.get('stored', 0) + 
                                 monthly_result.get('stored', 0)),
                        'skipped_missing': (daily_result.get('skipped_missing', 0) + 
                                          weekly_result.get('skipped_missing', 0) + 
                                          monthly_result.get('skipped_missing', 0)),
                        'skipped_outliers': (daily_result.get('skipped_outliers', 0) + 
                                           weekly_result.get('skipped_outliers', 0) + 
                                           monthly_result.get('skipped_outliers', 0))
                    }
                else:
                    raise ValueError(f"Unknown run type: {forecast_run.run_type}")
                
                # Mark as completed
                forecast_run.mark_completed(
                    predictions_created=result.get('stored', 0),
                    predictions_updated=0,  # We're using overwrite=True
                    outliers_skipped=result.get('skipped_outliers', 0)
                )
                
            except Exception as e:
                forecast_run.mark_failed(str(e))
        
        # Start the background thread
        thread = threading.Thread(target=run_forecast)
        thread.daemon = True
        thread.start()
        
        return forecast_run


class ForecastRunDetailAPIView(generics.RetrieveAPIView):
    """API endpoint to get a specific forecast run"""
    queryset = ForecastRun.objects.all()
    serializer_class = ForecastRunSerializer
    permission_classes = [IsAuthenticated]


@method_decorator(csrf_exempt, name='dispatch')
class TriggerForecastAPIView(APIView):
    """API endpoint to trigger a forecast run"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # Check if user has admin or super_admin role
        if not request.user.is_authenticated:
            return Response(
                {"error": "Authentication required."}, 
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        if request.user.role not in ['admin', 'super_admin']:
            return Response(
                {"error": f"Access denied. Admin privileges required. Current role: {request.user.role}"}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        """Trigger a forecast run"""
        data = request.data
        
        # Set default values
        run_type = data.get('run_type', 'daily')
        periods = data.get('periods', 30)
        aggregate_by = data.get('aggregate_by', 'day')
        
        # Calculate date range
        start_date = date.today()
        if run_type == 'daily':
            end_date = start_date + timedelta(days=periods - 1)
        elif run_type == 'weekly':
            end_date = start_date + timedelta(weeks=periods)
        elif run_type == 'monthly':
            end_date = start_date + timedelta(days=30 * periods)
        else:
            end_date = start_date + timedelta(days=periods - 1)
        
        # Create forecast run
        forecast_run = ForecastRun.objects.create(
            run_type=run_type,
            started_by=request.user,
            start_date=start_date,
            end_date=end_date,
            periods=periods,
            aggregate_by=aggregate_by,
            status='pending'
        )
        
        # Start forecast in background
        def run_forecast():
            try:
                forecast_run.status = 'running'
                forecast_run.save()
                
                result = run_prophet_for_date_range(
                    start_date=forecast_run.start_date,
                    end_date=forecast_run.end_date,
                    aggregate_by=forecast_run.aggregate_by,
                    prediction_type=forecast_run.run_type
                )
                
                forecast_run.mark_completed(
                    predictions_created=result.get('stored', 0),
                    outliers_skipped=result.get('skipped_outliers', 0)
                )
                
            except Exception as e:
                forecast_run.mark_failed(str(e))
        
        thread = threading.Thread(target=run_forecast)
        thread.daemon = True
        thread.start()
        
        serializer = ForecastRunSerializer(forecast_run)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ExportPredictionsAPIView(APIView):
    """API endpoint to export predictions as CSV"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Export predictions as CSV"""
        prediction_type = request.query_params.get('type', 'daily')
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        
        queryset = Prediction.objects.filter(prediction_type=prediction_type)
        
        if start_date:
            queryset = queryset.filter(date__gte=start_date)
        if end_date:
            queryset = queryset.filter(date__lte=end_date)
        
        queryset = queryset.order_by('date')
        
        # Create CSV response
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="predictions_{prediction_type}_{date.today()}.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['Date', 'Prediction Type', 'Predicted Value', 'Lower Bound', 'Upper Bound', 'Actual Value', 'Created At'])
        
        for prediction in queryset:
            writer.writerow([
                prediction.date,
                prediction.prediction_type,
                prediction.predicted_value,
                prediction.yhat_lower,
                prediction.yhat_upper,
                prediction.actual_value,
                prediction.created_at
            ])
        
        return response


@login_required
@admin_required
def prediction_dashboard(request):
    """Main prediction dashboard view"""
    return render(request, "predictor/dashboard.html", {})
