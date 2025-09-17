from . import views
from django.urls import path
urlpatterns = [
    path('therapy/', views.table_view, name='therapy_list'),
    path('registration-search/', views.registration_search, name='registration_search'),
]