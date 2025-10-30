from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()

class Prediction(models.Model):
    PREDICTION_CHOICES = [
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
    ]

    date = models.DateField()
    prediction_type = models.CharField(max_length=20, choices=PREDICTION_CHOICES, default='daily')
    predicted_value = models.FloatField()
    yhat_lower = models.FloatField(null=True, blank=True)   # new
    yhat_upper = models.FloatField(null=True, blank=True)   # new
    actual_value = models.FloatField(null=True, blank=True) # optional: actual patients that day
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("date", "prediction_type")
        ordering = ("date",)

    def __str__(self):
        return f"{self.prediction_type.capitalize()} prediction for {self.date}: {self.predicted_value:.2f}"


class ForecastRun(models.Model):
    """Model to track forecast execution runs"""
    RUN_TYPE_CHOICES = [
        ('daily', 'Daily Forecast'),
        ('weekly', 'Weekly Forecast'),
        ('monthly', 'Monthly Forecast'),
        ('all', 'All Forecasts'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    run_type = models.CharField(max_length=20, choices=RUN_TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    started_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, 
                                 related_name='forecast_runs')
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True, null=True)
    
    # Forecast parameters
    start_date = models.DateField()
    end_date = models.DateField()
    periods = models.PositiveIntegerField(default=30)
    aggregate_by = models.CharField(max_length=20, default='day')
    
    # Results summary
    predictions_created = models.PositiveIntegerField(default=0)
    predictions_updated = models.PositiveIntegerField(default=0)
    outliers_skipped = models.PositiveIntegerField(default=0)
    
    class Meta:
        ordering = ['-started_at']
        verbose_name = 'Forecast Run'
        verbose_name_plural = 'Forecast Runs'
    
    def __str__(self):
        return f"{self.get_run_type_display()} - {self.get_status_display()} ({self.started_at})"
    
    @property
    def duration(self):
        """Calculate duration of the forecast run"""
        if self.completed_at and self.started_at:
            return self.completed_at - self.started_at
        return None
    
    def mark_completed(self, predictions_created=0, predictions_updated=0, outliers_skipped=0):
        """Mark the forecast run as completed"""
        from django.utils import timezone
        self.status = 'completed'
        self.completed_at = timezone.now()
        self.predictions_created = predictions_created
        self.predictions_updated = predictions_updated
        self.outliers_skipped = outliers_skipped
        self.save()
    
    def mark_failed(self, error_message=""):
        """Mark the forecast run as failed"""
        from django.utils import timezone
        self.status = 'failed'
        self.completed_at = timezone.now()
        self.error_message = error_message
        self.save()
