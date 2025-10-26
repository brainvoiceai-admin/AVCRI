from django.urls import path
from . import views, prescription_views, procurement_views

urlpatterns = [
   
    path('therapy-entry/', views.therapy_entry, name='patient_therapy'),
    path('api/allocate_therapy/', views.allocate_therapy, name='allocate_therapy'),
    path('prescriptions/', views.prescription_entry_page, name='prescription_entry_page'),
    path('scheduling/', views.scheduling_dashboard, name='scheduling_dashboard'),
    path('scheduling/api/schedule-therapies/', views.schedule_therapies_api, name='schedule_therapies_api'),
    path('scheduling/api/therapy-data/', views.get_therapy_data_api, name='get_therapy_data_api'),
    path('scheduling/api/reschedule-therapy/', views.reschedule_therapy_api, name='reschedule_therapy_api'),
    path('scheduling/api/reschedule-all-failed/', views.reschedule_all_failed_api, name='reschedule_all_failed_api'),
    
    # Prescription Scheduling URLs
    path('prescription-scheduling/', prescription_views.prescription_scheduling_dashboard, name='prescription_scheduling_dashboard'),
    path('prescription/api/prescription-data/', prescription_views.get_prescription_data_api, name='get_prescription_data_api'),
    path('prescription/api/prescription-details/', prescription_views.get_prescription_details_api, name='get_prescription_details_api'),
    path('prescription/api/send-final-prescription/', prescription_views.send_final_prescription_api, name='send_final_prescription_api'),
    path('prescription/api/change-log/', prescription_views.get_change_log_api, name='get_change_log_api'),
    path('prescription/api/update-status/', prescription_views.update_prescription_status_api, name='update_prescription_status_api'),
    
    # Procurement Dashboard URLs
    path('procurement/', procurement_views.procurement_dashboard, name='procurement_dashboard'),
    path('procurement/api/prescriptions/', procurement_views.get_procurement_prescriptions_api, name='get_procurement_prescriptions_api'),
    path('procurement/api/mark-dispatched/', procurement_views.mark_as_dispatched_api, name='mark_as_dispatched_api'),
    path('procurement/api/prescription-details/', procurement_views.get_prescription_details_api, name='get_procurement_prescription_details_api'),
    path('procurement/api/prescription-items/', procurement_views.get_prescription_details_api, name='get_procurement_prescription_items_api'),
]