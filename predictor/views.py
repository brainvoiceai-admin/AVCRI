# predictor/views.py
from datetime import date, datetime as dt
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.views.decorators.http import require_GET
from .models import Prediction

VALID = ("daily", "weekly", "monthly")

def _parse_date(s):
    if not s:
        return None
    try:
        return dt.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

@require_GET
def prediction_api(request):
    """
    GET params:
      type=daily|weekly|monthly (default=daily)
      upcoming=1 (optional)
      start=YYYY-MM-DD
      end=YYYY-MM-DD
    """
    t = request.GET.get("type", "daily").lower()
    if t not in VALID:
        return HttpResponseBadRequest("Invalid type")

    qs = Prediction.objects.filter(prediction_type=t).order_by("date")

    if request.GET.get("upcoming") in ("1", "true", "True"):
        qs = qs.filter(date__gte=date.today())

    start_date = _parse_date(request.GET.get("start"))
    end_date = _parse_date(request.GET.get("end"))
    if start_date:
        qs = qs.filter(date__gte=start_date)
    if end_date:
        qs = qs.filter(date__lte=end_date)

    data = []
    for p in qs:
        data.append({
            "date": p.date.isoformat(),
            "prediction_type": p.prediction_type,
            "predicted_value": int(round(p.predicted_value)) if p.predicted_value is not None else None,
            "yhat_lower": int(round(p.yhat_lower)) if p.yhat_lower is not None else None,
            "yhat_upper": int(round(p.yhat_upper)) if p.yhat_upper is not None else None,
            "actual_value": int(round(p.actual_value)) if getattr(p, "actual_value", None) is not None else None,
        })
    return JsonResponse(data, safe=False)

def prediction_dashboard(request):
    return render(request, "predictor/chart.html", {})
