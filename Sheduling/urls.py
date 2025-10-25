from django.urls import path
from . import views

urlpatterns = [
   
    path('therapy-entry/', views.therapy_entry, name='patient_therapy'),
    path('api/allocate_therapy/', views.allocate_therapy, name='allocate_therapy'),
    path('prescriptions/', views.prescription_entry_page, name='prescription_entry_page'),
]