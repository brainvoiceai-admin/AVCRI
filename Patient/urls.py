from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('admindash/', views.admindash, name='admindash'),
    path('assign/', views.assign_page, name='assign_page'),
    path('get-therapy-details/<int:therapy_id>/', views.get_therapy_details, name='get_therapy_details'),
]