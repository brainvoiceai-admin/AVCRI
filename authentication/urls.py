from . import views
from django.urls import path
urlpatterns = [
   
path('login/', views.login_view, name='login'),
path("therapist/dashboard/", views.therapist_dashboard, name="therapistdash"),
path("scheduling_dashboard/dashboard/", views.scheduling_dashboard, name="therapistadmindash"),
path("doctor/dashboard/", views.doctor_dashboard, name="doctordash"),
path("gmhr/dashboard/", views.gm_hr_dashboard, name="gmdash"),
path("superadmin/dashboard/", views.superadmin_dashboard, name="superadmindash"),
path("dashboard/medicin_prescription", views.medicin_prescription, name="medicin_prescription"),
path("Patient_dashboard/dashboard/", views.Patient_dashboard, name="patientdash"),
path("Tenantsdash/dashboard/", views.Tenants_dashboard, name="Tenantsdash"),
path("Helpdeskadmindash/dashboard/", views.Helpdeskadmindash, name="Helpdeskadmindash"),
path("logout/", views.logout_view, name="logout"),
path("medicin_prescription_table/dashboard/", views.medicin_prescription_table, name="medicin_prescription_table"),
path("Manage_user/dashboard/", views.Manage_user, name="Manage_user"),
path("Audit_Log/dashboard/", views.Audit_Log, name="Audit_Log"),
path("view_patient_details/dashboard/", views.view_patient_details, name="view_patient_details"),
path("therapist_feedback_form/dashboard/", views.therapist_feedback_form, name="therapist_feedback_form"),
path("Therapy_Report/dashboard/", views.Therapy_Report, name="Therapy_Report"),
path("housekeepingdash/dashboard/", views.housekeepingdash, name="housekeepingdash"),
path("Patient_feedback_review/dashboard/", views.Patient_feedback_review, name="Patient_feedback_review"),
path("nurse_dash/dashboard/", views.nurse_dash, name="nurse_dash"),
path("ip_pharmacy/dashboard/", views.ip_pharmacy, name="ip_pharmacy"),
path("prescription_dash/dashboard/", views.prescription_dash, name="prescription_dash"),
path("patient_profile/dashboard/", views.patient_profile, name="patient_profile"),
]