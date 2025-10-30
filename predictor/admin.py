from django.contrib import admin
from .models import Prediction, ForecastRun

@admin.register(Prediction)
class PredictionAdmin(admin.ModelAdmin):
    list_display = ['date', 'prediction_type', 'predicted_value', 'yhat_lower', 'yhat_upper', 'actual_value', 'created_at']
    list_filter = ['prediction_type', 'date', 'created_at']
    search_fields = ['prediction_type']
    ordering = ['-date', '-created_at']
    readonly_fields = ['created_at']
    
    fieldsets = (
        ('Prediction Details', {
            'fields': ('date', 'prediction_type', 'predicted_value')
        }),
        ('Confidence Intervals', {
            'fields': ('yhat_lower', 'yhat_upper'),
            'classes': ('collapse',)
        }),
        ('Actual Values', {
            'fields': ('actual_value',),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        })
    )

@admin.register(ForecastRun)
class ForecastRunAdmin(admin.ModelAdmin):
    list_display = ['run_type', 'status', 'started_by', 'started_at', 'completed_at', 'predictions_created', 'duration_display']
    list_filter = ['run_type', 'status', 'started_at', 'aggregate_by']
    search_fields = ['started_by__username', 'run_type']
    ordering = ['-started_at']
    readonly_fields = ['started_at', 'completed_at', 'duration_display']
    
    fieldsets = (
        ('Run Details', {
            'fields': ('run_type', 'status', 'started_by')
        }),
        ('Parameters', {
            'fields': ('start_date', 'end_date', 'periods', 'aggregate_by')
        }),
        ('Results', {
            'fields': ('predictions_created', 'predictions_updated', 'outliers_skipped')
        }),
        ('Timestamps', {
            'fields': ('started_at', 'completed_at', 'duration_display'),
            'classes': ('collapse',)
        }),
        ('Error Information', {
            'fields': ('error_message',),
            'classes': ('collapse',)
        })
    )
    
    def duration_display(self, obj):
        """Display duration in human-readable format"""
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
        return "N/A"
    duration_display.short_description = "Duration"
