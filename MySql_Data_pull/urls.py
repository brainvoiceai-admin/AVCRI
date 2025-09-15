from . import views
from django.urls import path
urlpatterns = [
    path('therapy/', views.table_view, name='therapy_list'),
]