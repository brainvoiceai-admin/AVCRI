from django.urls import path
from . import views

urlpatterns = [
    path('procured', views.ProcuredManagementView.as_view(), name='procured_manage'), 
    path('<int:pk>/', views.ProcuredManagementView.as_view(), name='procured_manage_update'),
    path('<int:pk>/delete/', views.ProcuredDeleteView.as_view(), name='procured_delete'),
    path('oils/', views.OilClassManagementView.as_view(), name='oilclass_manage'), 
    path('oils/<int:pk>/', views.OilClassManagementView.as_view(), name='oilclass_manage_update'),
    path('oils/<int:pk>/delete/', views.OilClassDeleteView.as_view(), name='oilclass_delete'),
    path('usages/', views.UsageTypeManagementView.as_view(), name='usagetype_manage'), 
    path('usages/<int:pk>/', views.UsageTypeManagementView.as_view(), name='usagetype_manage_update'),
    path('usages/<int:pk>/delete/', views.UsageTypeDeleteView.as_view(), name='usagetype_delete'),
    path('times/', views.PrescriptionTimeManagementView.as_view(), name='prestime_manage'), 
    path('times/<int:pk>/', views.PrescriptionTimeManagementView.as_view(), name='prestime_manage_update'),
    path('times/<int:pk>/delete/', views.PrescriptionTimeDeleteView.as_view(), name='prestime_delete'),
    path('prescopes/', views.PrescriptionScopeManagementView.as_view(), name='prescope_manage'), 
    path('prescopes/<int:pk>/', views.PrescriptionScopeManagementView.as_view(), name='prescope_manage_update'),
    path('prescopes/<int:pk>/delete/', views.PrescriptionScopeDeleteView.as_view(), name='prescope_delete'),
    path('units/', views.UnitNoListView.as_view(), name='unit_list'),
    path('units/add/', views.UnitNoCreateView.as_view(), name='unit_add'),
    path('units/<int:pk>/update/', views.UnitNoUpdateView.as_view(), name='unit_update'),
    path('units/<int:pk>/delete/', views.UnitNoDeleteView.as_view(), name='unit_delete'),
    path('units/<int:pk>/enable/', views.unit_no_enable, name='unit_enable'),
    path('units/<int:pk>/disable/', views.unit_no_disable, name='unit_disable'),
    # API endpoints for master data
    path('api/master-data/', views.get_master_data, name='get_master_data'),
    path('api/master-item/', views.create_master_item, name='create_master_item'),
    path('api/master-item/<int:item_id>/', views.update_master_item, name='update_master_item'),
    path('api/master-item/<int:item_id>/delete/', views.delete_master_item, name='delete_master_item'),
    # Therapist management API endpoints
    path('api/therapist/', views.create_therapist, name='create_therapist'),
    path('api/therapist/<int:therapist_id>/', views.update_therapist, name='update_therapist'),
    path('api/therapist/<int:therapist_id>/delete/', views.delete_therapist, name='delete_therapist'),
    path('api/therapist-leave/', views.create_therapist_leave, name='create_therapist_leave'),
    path('api/therapist-leave/<int:leave_id>/delete/', views.delete_therapist_leave, name='delete_therapist_leave'),
    # Master Management Dashboard
    path('dashboard/', views.master_management_dashboard, name='master_management_dashboard'),
    # Therapy Master CRUD
    path('therapy/', views.TherapyMasterManagementView.as_view(), name='therapy_master_manage'),
    path('therapy/add/', views.TherapyMasterCreateView.as_view(), name='therapy_master_add'),
    path('therapy/<int:pk>/update/', views.TherapyMasterUpdateView.as_view(), name='therapy_master_update'),
    path('therapy/<int:pk>/delete/', views.TherapyMasterDeleteView.as_view(), name='therapy_master_delete'),
    # Item Master CRUD
    path('items/', views.ItemMasterManagementView.as_view(), name='item_master_manage'),
    path('items/add/', views.ItemMasterCreateView.as_view(), name='item_master_add'),
    path('items/<int:pk>/update/', views.ItemMasterUpdateView.as_view(), name='item_master_update'),
    path('items/<int:pk>/delete/', views.ItemMasterDeleteView.as_view(), name='item_master_delete'),
    # Slot Master CRUD
    path('slots/', views.SlotMasterManagementView.as_view(), name='slot_master_manage'),
    path('slots/add/', views.SlotMasterCreateView.as_view(), name='slot_master_add'),
    path('slots/<int:pk>/update/', views.SlotMasterUpdateView.as_view(), name='slot_master_update'),
    path('slots/<int:pk>/delete/', views.SlotMasterDeleteView.as_view(), name='slot_master_delete'),
    # Therapist Master CRUD
    path('therapists/', views.TherapistMasterManagementView.as_view(), name='therapist_master_manage'),
    path('therapists/add/', views.TherapistMasterCreateView.as_view(), name='therapist_master_add'),
    path('therapists/<int:pk>/update/', views.TherapistMasterUpdateView.as_view(), name='therapist_master_update'),
    path('therapists/<int:pk>/delete/', views.TherapistMasterDeleteView.as_view(), name='therapist_master_delete'),
]