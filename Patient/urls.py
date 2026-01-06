from django.urls import path
from . import views

# urlpatterns = [
#     path('', views.home, name='home'),
   
    

# ]
urlpatterns = [
    path('', views.home, name='home'),
  # Removed URLs for deleted templates (not in navigation):
  # path('patient_lookup/', views.patient_lookup_view, name='patient_lookup'),
    path('therapy/', views.therapy_entry_view, name='therapy_entry'),
    path('prescription/', views.prescription_entry_view, name='prescription_entry'),
    # path('review/', views.review_view, name='review_page'),
    path('submit/', views.submit_all_data, name='submit_all_data'),
    path('get-item-details/', views.get_item_details, name='get_item_details'),
    path('search-patients/', views.search_patients_api, name='search_patients'),
    path('get-patient-details/', views.get_patient_details_api, name='get_patient_details'),
    path('search-therapies/', views.search_therapies_api, name='search_therapies'),

#patient booking view
# Removed Treatment Schedule - not needed
# path("patients/", views.PatientListView.as_view(), name="patient_list"),
path("patients/<int:visit_id>/sessions/", views.PatientSessionsView.as_view(), name="patient_sessions"),

#patient booking cancellation view
    # booking actions
path("session/cancel-multi/", views.cancel_session_bookings, name="cancel_session_bookings"),
path("session/complete-multi/", views.complete_session_bookings, name="complete_session_bookings"),


# therapy item actions
path("therapy-item/<int:item_id>/update/", views.update_therapy_item, name="update_therapy_item"),
path("therapy-item/<int:item_id>/cancel/", views.cancel_therapy_item, name="cancel_therapy_item"),


path('/patients/<visit_id>/add-therapy-item/', views.add_therapy_item, name='add_therapy_item'),
 

# prescription item actions
path("prescription-item/<int:item_id>/update/", views.update_prescription_item, name="update_prescription_item"),
path("prescription-item/<int:item_id>/cancel/", views.cancel_prescription_item, name="cancel_prescription_item"),


path("prescription/<int:prescription_id>/add-item/", views.add_prescription_item, name="add_prescription_item"),
path('api/get-item-details/', views.get_item_details, name='get_item_details'),
path('prescription/<int:prescription_id>/add-item/', views.add_prescription_item, name='add_prescription_item'),
  path('available_slots/', views.available_slots, name='available_slots'),
  path('time_slots/', views.time_slots, name='time_slots'),
  path('unit_numbers/', views.unit_numbers, name='unit_numbers'),
  path('allocation-result/', views.allocation_result_view, name='allocation_result'),

]