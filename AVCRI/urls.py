"""
URL configuration for AVCRI project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse
from django.conf import settings
from django.conf.urls.static import static
from Patient import views as patient_views

# Temporary handler for WebSocket notifications endpoint (disabled)
def ws_notifications_disabled(request):
    """Handler for /ws/notifications/ endpoint - notifications are temporarily disabled"""
    return JsonResponse({'status': 'disabled', 'message': 'Notifications are temporarily disabled'}, status=200)

urlpatterns = [
    path('admin/', admin.site.urls),
    # Explicit patient history endpoint for PatientHistory popup
    path('patient-history/', patient_views.patient_history_api, name='patient_history_root'),
    path('', include(('Patient.urls', 'patient'), namespace='patient')),
      path('authentication/', include(('authentication.urls', 'authentication'), namespace='authentication')),
      path('therapy/', include('MySql_Data_pull.urls')),
      path("predictor/", include("predictor.urls")),
      path("sheduling/", include("Sheduling.urls")),
      path("Masters/", include("masters.urls")),
      path("masters/", include("masters.urls")),
      # Temporary route to handle WebSocket notification requests (disabled)
      path('ws/notifications/', ws_notifications_disabled, name='ws_notifications_disabled'),
]

# Serve media files during development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Always serve static files (WhiteNoise handles this in production, but we add fallback)
# This ensures static files work even when DEBUG=False
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
urlpatterns += staticfiles_urlpatterns()

# Custom error handlers
handler400 = 'AVCRI.error_handlers.handler400'
handler403 = 'AVCRI.error_handlers.handler403'
handler404 = 'AVCRI.error_handlers.handler404'
handler500 = 'AVCRI.error_handlers.handler500'

