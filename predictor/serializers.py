# predictor/serializers.py
from rest_framework import serializers
from .models import Prediction, ForecastRun
from django.contrib.auth import get_user_model

User = get_user_model()


class PredictionSerializer(serializers.ModelSerializer):
    """Serializer for Prediction model"""
    class Meta:
        model = Prediction
        fields = ['id', 'date', 'prediction_type', 'predicted_value', 
                 'yhat_lower', 'yhat_upper', 'actual_value', 'created_at']
        read_only_fields = ['id', 'created_at']


class ForecastRunSerializer(serializers.ModelSerializer):
    """Serializer for ForecastRun model"""
    started_by_username = serializers.CharField(source='started_by.username', read_only=True)
    duration_display = serializers.SerializerMethodField()
    
    class Meta:
        model = ForecastRun
        fields = ['id', 'run_type', 'status', 'started_by', 'started_by_username',
                 'started_at', 'completed_at', 'error_message', 'start_date', 'end_date',
                 'periods', 'aggregate_by', 'predictions_created', 'predictions_updated',
                 'outliers_skipped', 'duration_display']
        read_only_fields = ['id', 'started_at', 'completed_at', 'duration_display']
    
    def get_duration_display(self, obj):
        """Get human-readable duration"""
        duration = obj.duration
        if duration:
            total_seconds = int(duration.total_seconds())
            if total_seconds < 60:
                return f"{total_seconds}s"
            elif total_seconds < 3600:
                minutes = total_seconds // 60
                seconds = total_seconds % 60
                return f"{minutes}m {seconds}s"
            else:
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                return f"{hours}h {minutes}m"
        return None


class ForecastRunCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating ForecastRun"""
    class Meta:
        model = ForecastRun
        fields = ['run_type', 'start_date', 'end_date', 'periods', 'aggregate_by']
    
    def validate(self, data):
        """Validate forecast run data"""
        if data['start_date'] > data['end_date']:
            raise serializers.ValidationError("Start date must be before end date")
        
        if data['periods'] <= 0:
            raise serializers.ValidationError("Periods must be greater than 0")
        
        return data


class PredictionSummarySerializer(serializers.Serializer):
    """Serializer for prediction summary statistics"""
    prediction_type = serializers.CharField()
    total_predictions = serializers.IntegerField()
    date_range_start = serializers.DateField()
    date_range_end = serializers.DateField()
    average_prediction = serializers.FloatField()
    min_prediction = serializers.FloatField()
    max_prediction = serializers.FloatField()
    last_updated = serializers.DateTimeField()
