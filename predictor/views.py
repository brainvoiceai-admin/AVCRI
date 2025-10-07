# predictor/views.py
from datetime import date
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .models import Prediction

VALID = ("daily", "weekly", "monthly")

@require_GET
def prediction_api(request):
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

def prediction_dashboard(request):
    return render(request, "predictor/chart.html", {})
