from django.db import models

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
