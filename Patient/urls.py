from django.urls import path
from . import views

# urlpatterns = [
#     path('', views.home, name='home'),
   
    
 
# ]
urlpatterns = [
    path('', views.home, name='home'),
  path('patient_lookup/', views.patient_lookup_view, name='patient_lookup'),
    path('therapy/', views.therapy_entry_view, name='therapy_entry'),
    path('prescription/', views.prescription_entry_view, name='prescription_entry'),
    path('review/', views.review_view, name='review_page'),
    path('submit/', views.submit_all_data, name='submit_all_data'),
    path('get-item-details/', views.get_item_details, name='get_item_details'),
    path('search-patients/', views.search_patients_api, name='search_patients'),
    path('get-patient-details/', views.get_patient_details_api, name='get_patient_details'),
    path('search-therapies/', views.search_therapies_api, name='search_therapies'),
]