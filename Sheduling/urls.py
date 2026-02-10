from django.urls import path
from . import views, prescription_views, procurement_views, patient_views, therapist_views, availability_views, matrix_views

urlpatterns = [
   
    path('therapy-entry/', views.therapy_entry, name='patient_therapy'),
    path('api/allocate_therapy/', views.allocate_therapy, name='allocate_therapy'),
    path('prescriptions/', views.prescription_entry_page, name='prescription_entry_page'),
    path('scheduling/', views.scheduling_dashboard, name='scheduling_dashboard'),
    path('user-therapy-entry/', views.user_therapy_entry_dashboard, name='user_therapy_entry_dashboard'),
    path('scheduling/api/schedule-therapies/', views.schedule_therapies_api, name='schedule_therapies_api'),
    path('scheduling/api/final-schedule/', views.final_schedule_api, name='final_schedule_api'),
    path('scheduling/api/therapy-data/', views.get_therapy_data_api, name='get_therapy_data_api'),
    path('scheduling/api/final-schedule/status/', views.final_schedule_status_api, name='final_schedule_status_api'),
    path('scheduling/api/reschedule-therapy/', views.reschedule_therapy_api, name='reschedule_therapy_api'),
    path('scheduling/api/reschedule-all-failed/', views.reschedule_all_failed_api, name='reschedule_all_failed_api'),
    path('scheduling/api/therapy-change-log/', views.therapy_change_log_api, name='therapy_change_log_api'),


    # Continuity Matrix API
    path('scheduling/api/continuity-matrix/', matrix_views.continuity_matrix_api, name='continuity_matrix_api'),
    
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
    path('procurement/api/change-log/', procurement_views.get_prescription_change_log_api, name='get_procurement_change_log_api'),
    
    # Patient Dashboard URLs (more specific patterns first)
    path('patient/api/patient-data/', patient_views.get_patient_data_api, name='get_patient_data_api'),
    path('patient/api/prescriptions/', patient_views.get_patient_prescriptions_api, name='get_patient_prescriptions_api'),
    path('patient/', patient_views.patient_dashboard, name='patient_dashboard'),
    
    # Therapist Dashboard URLs (more specific patterns first)
    path('therapist/api/therapist-data/', therapist_views.get_therapist_data_api, name='get_therapist_data_api'),
    path('therapist/api/sessions-by-date/', therapist_views.get_therapist_sessions_by_date_api, name='get_therapist_sessions_by_date_api'),
    path('therapist/', therapist_views.therapist_dashboard, name='therapist_dashboard'),
    path('therapist-difficulty/', therapist_views.therapist_difficulty_dashboard, name='therapist_difficulty_dashboard'),
    path('therapist-difficulty/api/data/', therapist_views.get_therapist_difficulty_data, name='therapist_difficulty_data'),
    
    # Therapist Availability URLs
    path('therapist-availability/', availability_views.therapist_availability_dashboard, name='therapist_availability_dashboard'),
    path('therapist-availability/api/available-therapists/', availability_views.get_available_therapists_api, name='get_available_therapists_api'),
    path('therapist-availability/api/therapists-on-leave/', availability_views.get_therapists_on_leave_api, name='get_therapists_on_leave_api'),
    path('therapist-availability/api/time-slots/', availability_views.get_time_slots_api, name='get_time_slots_api'),
    
    # Treatment Room Availability URLs
    path('room-availability/', availability_views.room_availability_dashboard, name='room_availability_dashboard'),
    path('room-availability/api/available-rooms/', availability_views.get_available_rooms_api, name='get_available_rooms_api'),
    path('room-availability/api/occupied-rooms/', availability_views.get_occupied_rooms_api, name='get_occupied_rooms_api'),
    path('room-availability/api/time-slots/', availability_views.get_time_slots_api, name='get_room_time_slots_api'),
    
    # Bulk Excel Upload/Download for Testing
    path('therapy-bulk-excel/', views.therapy_bulk_excel, name='therapy_bulk_excel'),
]