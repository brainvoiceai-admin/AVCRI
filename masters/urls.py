from django.urls import path
from . import views
from .views import ProcuredManagementView, ProcuredDeleteView,OilClassManagementView, OilClassDeleteView,UsageTypeManagementView, UsageTypeDeleteView,PrescriptionTimeManagementView, PrescriptionTimeDeleteView,PrescriptionScopeManagementView, PrescriptionScopeDeleteView
urlpatterns = [
    path('procured', ProcuredManagementView.as_view(), name='procured_manage'), 
    path('<int:pk>/', ProcuredManagementView.as_view(), name='procured_manage_update'),
    path('<int:pk>/delete/', ProcuredDeleteView.as_view(), name='procured_delete'),
    path('oils/', OilClassManagementView.as_view(), name='oilclass_manage'), 
    path('oils/<int:pk>/', OilClassManagementView.as_view(), name='oilclass_manage_update'),
    path('oils/<int:pk>/delete/', OilClassDeleteView.as_view(), name='oilclass_delete'),
    path('usages/', UsageTypeManagementView.as_view(), name='usagetype_manage'), 
    path('usages/<int:pk>/', UsageTypeManagementView.as_view(), name='usagetype_manage_update'),
    path('usages/<int:pk>/delete/', UsageTypeDeleteView.as_view(), name='usagetype_delete'),
    path('times/', PrescriptionTimeManagementView.as_view(), name='prestime_manage'), 
    path('times/<int:pk>/', PrescriptionTimeManagementView.as_view(), name='prestime_manage_update'),
    path('times/<int:pk>/delete/', PrescriptionTimeDeleteView.as_view(), name='prestime_delete'),
    path('prescopes/', PrescriptionScopeManagementView.as_view(), name='prescope_manage'), 
    path('prescopes/<int:pk>/', PrescriptionScopeManagementView.as_view(), name='prescope_manage_update'),
    path('prescopes/<int:pk>/delete/', PrescriptionScopeDeleteView.as_view(), name='prescope_delete'),
    path('units/', views.UnitNoListView.as_view(), name='unit_list'),
    path('units/add/', views.UnitNoCreateView.as_view(), name='unit_add'),
    path('units/<int:pk>/update/', views.UnitNoUpdateView.as_view(), name='unit_update'),
    path('units/<int:pk>/delete/', views.UnitNoDeleteView.as_view(), name='unit_delete'),
    path('units/<int:pk>/enable/', views.unit_no_enable, name='unit_enable'),
    path('units/<int:pk>/disable/', views.unit_no_disable, name='unit_disable'),
]