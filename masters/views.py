from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from authentication.decorators import super_admin_required
from .models import (
    Procured, OilClass, UsageType, PrescriptionTime, 
    PrescriptionScope, UnitNo, TherapyMaster, ItemMaster, SlotMaster,
    TherapistMaster, TherapistLeaveMaster
)
import json

@login_required
@require_http_methods(["GET"])
def get_master_data(request):
    """API endpoint to get master data for dropdowns"""
    master_type = request.GET.get('type', '')
    
    try:
        if master_type == 'therapy':
            data = list(TherapyMaster.objects.filter(is_active=True).values(
                'therapy_code', 'therapy_name', 'therapy_group', 'therapy_category'
            ))
        elif master_type == 'item':
            data = list(ItemMaster.objects.filter(is_active=True).values(
                'item_code', 'item_name', 'item_category'
            ))
        elif master_type == 'slot':
            data = list(SlotMaster.objects.filter(is_active=True).values(
                'slot_number', 'slot_name', 'start_time', 'end_time'
            ))
        elif master_type == 'procured':
            data = list(Procured.objects.filter(is_active=True).values('id', 'name'))
        elif master_type == 'oil_class':
            data = list(OilClass.objects.filter(is_active=True).values('id', 'name'))
        elif master_type == 'usage_type':
            data = list(UsageType.objects.filter(is_active=True).values('id', 'name'))
        elif master_type == 'prescription_time':
            data = list(PrescriptionTime.objects.filter(is_active=True).values('id', 'name'))
        elif master_type == 'prescription_scope':
            data = list(PrescriptionScope.objects.filter(is_active=True).values('id', 'name'))
        elif master_type == 'unit_no':
            data = list(UnitNo.objects.filter(is_active=True).values('id', 'unit_name'))
        elif master_type == 'therapist':
            data = list(TherapistMaster.objects.filter(is_active=True).values(
                'therapist_code', 'therapist_name', 'therapist_grade', 'employee_code', 'is_bathing_therapist'
            ))
        elif master_type == 'therapist_leave':
            therapist_code = request.GET.get('therapist_code', '')
            if therapist_code:
                data = list(TherapistLeaveMaster.objects.filter(
                    therapist__therapist_code=therapist_code, is_active=True
                ).values('leave_day', 'leave_day_name', 'is_active'))
            else:
                data = list(TherapistLeaveMaster.objects.filter(is_active=True).values(
                    'therapist__therapist_code', 'therapist__therapist_name', 'leave_day', 'leave_day_name'
                ))
        else:
            return JsonResponse({'error': 'Invalid master type'}, status=400)
        
        return JsonResponse({'data': data})
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@super_admin_required
@require_http_methods(["POST"])
@csrf_exempt
def create_master_item(request):
    """API endpoint to create master items (Super Admin only)"""
    try:
        data = json.loads(request.body)
        master_type = data.get('type', '')
        
        if master_type == 'therapy':
            item = TherapyMaster.objects.create(
                therapy_code=data['therapy_code'],
                therapy_name=data['therapy_name'],
                therapy_group=data.get('therapy_group', ''),
                therapy_category=data.get('therapy_category', ''),
                therapy_duration=data.get('therapy_duration', ''),
                bathing_required=data.get('bathing_required', ''),
                treatment_room_required=data.get('treatment_room_required', ''),
                cost_of_therapy=data.get('cost_of_therapy', 0)
            )
        elif master_type == 'item':
            item = ItemMaster.objects.create(
                item_code=data['item_code'],
                item_name=data['item_name'],
                item_category=data.get('item_category', ''),
                unit_of_measure=data.get('unit_of_measure', '')
            )
        elif master_type == 'slot':
            item = SlotMaster.objects.create(
                slot_number=data['slot_number'],
                start_time=data['start_time'],
                end_time=data['end_time'],
                slot_name=data.get('slot_name', '')
            )
        else:
            return JsonResponse({'error': 'Invalid master type'}, status=400)
        
        return JsonResponse({'success': True, 'id': item.id})
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@super_admin_required
@require_http_methods(["PUT"])
@csrf_exempt
def update_master_item(request, item_id):
    """API endpoint to update master items (Super Admin only)"""
    try:
        data = json.loads(request.body)
        master_type = data.get('type', '')
        
        if master_type == 'therapy':
            item = TherapyMaster.objects.get(id=item_id)
            item.therapy_name = data.get('therapy_name', item.therapy_name)
            item.therapy_group = data.get('therapy_group', item.therapy_group)
            item.therapy_category = data.get('therapy_category', item.therapy_category)
            item.is_active = data.get('is_active', item.is_active)
        elif master_type == 'item':
            item = ItemMaster.objects.get(id=item_id)
            item.item_name = data.get('item_name', item.item_name)
            item.item_category = data.get('item_category', item.item_category)
            item.is_active = data.get('is_active', item.is_active)
        elif master_type == 'slot':
            item = SlotMaster.objects.get(id=item_id)
            item.slot_name = data.get('slot_name', item.slot_name)
            item.start_time = data.get('start_time', item.start_time)
            item.end_time = data.get('end_time', item.end_time)
            item.is_active = data.get('is_active', item.is_active)
        else:
            return JsonResponse({'error': 'Invalid master type'}, status=400)
        
        item.save()
        return JsonResponse({'success': True})
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@super_admin_required
@require_http_methods(["DELETE"])
@csrf_exempt
def delete_master_item(request, item_id):
    """API endpoint to delete master items (Super Admin only)"""
    try:
        data = json.loads(request.body)
        master_type = data.get('type', '')
        
        if master_type == 'therapy':
            item = TherapyMaster.objects.get(id=item_id)
        elif master_type == 'item':
            item = ItemMaster.objects.get(id=item_id)
        elif master_type == 'slot':
            item = SlotMaster.objects.get(id=item_id)
        else:
            return JsonResponse({'error': 'Invalid master type'}, status=400)
        
        item.delete()
        return JsonResponse({'success': True})
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

# Class-based views for master management
class ProcuredManagementView(ListView):
    model = Procured
    template_name = 'masters/procured_manage.html'
    context_object_name = 'procured_list'
    paginate_by = 20

    def get_queryset(self):
        return Procured.objects.all().order_by('name')
    
    def post(self, request, *args, **kwargs):
        """Handle POST requests for creating new procurement sources or updating existing ones"""
        pk = kwargs.get('pk')
        name = request.POST.get('name')
        is_active = request.POST.get('is_active') == 'on'
        
        if pk:
            # Update existing record (enable/disable)
            try:
                procured = Procured.objects.get(pk=pk)
                procured.is_active = is_active
                procured.save()
                action = "enabled" if is_active else "disabled"
                messages.success(request, f'Procurement source "{procured.name}" {action} successfully.')
            except Procured.DoesNotExist:
                messages.error(request, 'Procurement source not found.')
            except Exception as e:
                messages.error(request, f'Error updating procurement source: {str(e)}')
        else:
            # Create new record
            if name:
                try:
                    Procured.objects.create(
                        name=name,
                        is_active=is_active
                    )
                    messages.success(request, f'Procurement source "{name}" created successfully.')
                except Exception as e:
                    messages.error(request, f'Error creating procurement source: {str(e)}')
            else:
                messages.error(request, 'Name is required.')
        
        return redirect('procured_manage')

class ProcuredDeleteView(DeleteView):
    model = Procured
    success_url = reverse_lazy('procured_manage')
    
    def delete(self, request, *args, **kwargs):
        messages.success(request, 'Procured item deleted successfully.')
        return super().delete(request, *args, **kwargs)

class OilClassManagementView(ListView):
    model = OilClass
    template_name = 'masters/oilclass_manage.html'
    context_object_name = 'oilclass_list'
    paginate_by = 20

    def get_queryset(self):
        return OilClass.objects.all().order_by('name')
    
    def post(self, request, *args, **kwargs):
        """Handle POST requests for creating new oil classes or updating existing ones"""
        pk = kwargs.get('pk')
        name = request.POST.get('name')
        is_active = request.POST.get('is_active') == 'on'
        
        if pk:
            # Update existing record (enable/disable)
            try:
                oil_class = OilClass.objects.get(pk=pk)
                oil_class.is_active = is_active
                oil_class.save()
                action = "enabled" if is_active else "disabled"
                messages.success(request, f'Oil class "{oil_class.name}" {action} successfully.')
            except OilClass.DoesNotExist:
                messages.error(request, 'Oil class not found.')
            except Exception as e:
                messages.error(request, f'Error updating oil class: {str(e)}')
        else:
            # Create new record
            if name:
                try:
                    OilClass.objects.create(
                        name=name,
                        is_active=is_active
                    )
                    messages.success(request, f'Oil class "{name}" created successfully.')
                except Exception as e:
                    messages.error(request, f'Error creating oil class: {str(e)}')
            else:
                messages.error(request, 'Name is required.')
            
            return redirect('oilclass_manage')

class OilClassDeleteView(DeleteView):
    model = OilClass
    success_url = reverse_lazy('oilclass_manage')
    
    def delete(self, request, *args, **kwargs):
        messages.success(request, 'Oil class deleted successfully.')
        return super().delete(request, *args, **kwargs)

class UsageTypeManagementView(ListView):
    model = UsageType
    template_name = 'masters/usagetype_manage.html'
    context_object_name = 'usagetype_list'
    paginate_by = 20

    def get_queryset(self):
        return UsageType.objects.all().order_by('name')
    
    def post(self, request, *args, **kwargs):
        """Handle POST requests for creating new usage types or updating existing ones"""
        pk = kwargs.get('pk')
        name = request.POST.get('name')
        is_active = request.POST.get('is_active') == 'on'
        
        if pk:
            # Update existing record (enable/disable)
            try:
                usage_type = UsageType.objects.get(pk=pk)
                usage_type.is_active = is_active
                usage_type.save()
                action = "enabled" if is_active else "disabled"
                messages.success(request, f'Usage type "{usage_type.name}" {action} successfully.')
            except UsageType.DoesNotExist:
                messages.error(request, 'Usage type not found.')
            except Exception as e:
                messages.error(request, f'Error updating usage type: {str(e)}')
        else:
            # Create new record
            if name:
                try:
                    UsageType.objects.create(
                        name=name,
                        is_active=is_active
                    )
                    messages.success(request, f'Usage type "{name}" created successfully.')
                except Exception as e:
                    messages.error(request, f'Error creating usage type: {str(e)}')
            else:
                messages.error(request, 'Name is required.')
            
            return redirect('usagetype_manage')

class UsageTypeDeleteView(DeleteView):
    model = UsageType
    success_url = reverse_lazy('usagetype_manage')
    
    def delete(self, request, *args, **kwargs):
        messages.success(request, 'Usage type deleted successfully.')
        return super().delete(request, *args, **kwargs)

class PrescriptionTimeManagementView(ListView):
    model = PrescriptionTime
    template_name = 'masters/prestime_manage.html'
    context_object_name = 'prestime_list'
    paginate_by = 20

    def get_queryset(self):
        return PrescriptionTime.objects.all().order_by('name')
    
    def post(self, request, *args, **kwargs):
        """Handle POST requests for creating new prescription times or updating existing ones"""
        pk = kwargs.get('pk')
        name = request.POST.get('name')
        is_active = request.POST.get('is_active') == 'on'
        
        if pk:
            # Update existing record (enable/disable)
            try:
                prescription_time = PrescriptionTime.objects.get(pk=pk)
                prescription_time.is_active = is_active
                prescription_time.save()
                action = "enabled" if is_active else "disabled"
                messages.success(request, f'Prescription time "{prescription_time.name}" {action} successfully.')
            except PrescriptionTime.DoesNotExist:
                messages.error(request, 'Prescription time not found.')
            except Exception as e:
                messages.error(request, f'Error updating prescription time: {str(e)}')
        else:
            # Create new record
            if name:
                try:
                    PrescriptionTime.objects.create(
                        name=name,
                        is_active=is_active
                    )
                    messages.success(request, f'Prescription time "{name}" created successfully.')
                except Exception as e:
                    messages.error(request, f'Error creating prescription time: {str(e)}')
            else:
                messages.error(request, 'Name is required.')
            
            return redirect('prestime_manage')

class PrescriptionTimeDeleteView(DeleteView):
    model = PrescriptionTime
    success_url = reverse_lazy('prestime_manage')
    
    def delete(self, request, *args, **kwargs):
        messages.success(request, 'Prescription time deleted successfully.')
        return super().delete(request, *args, **kwargs)

class PrescriptionScopeManagementView(ListView):
    model = PrescriptionScope
    template_name = 'masters/prescope_manage.html'
    context_object_name = 'prescope_list'
    paginate_by = 20

    def get_queryset(self):
        return PrescriptionScope.objects.all().order_by('name')
    
    def post(self, request, *args, **kwargs):
        """Handle POST requests for creating new prescription scopes or updating existing ones"""
        pk = kwargs.get('pk')
        name = request.POST.get('name')
        is_active = request.POST.get('is_active') == 'on'
        
        if pk:
            # Update existing record (enable/disable)
            try:
                prescription_scope = PrescriptionScope.objects.get(pk=pk)
                prescription_scope.is_active = is_active
                prescription_scope.save()
                action = "enabled" if is_active else "disabled"
                messages.success(request, f'Prescription scope "{prescription_scope.name}" {action} successfully.')
            except PrescriptionScope.DoesNotExist:
                messages.error(request, 'Prescription scope not found.')
            except Exception as e:
                messages.error(request, f'Error updating prescription scope: {str(e)}')
        else:
            # Create new record
            if name:
                try:
                    PrescriptionScope.objects.create(
                        name=name,
                        is_active=is_active
                    )
                    messages.success(request, f'Prescription scope "{name}" created successfully.')
                except Exception as e:
                    messages.error(request, f'Error creating prescription scope: {str(e)}')
            else:
                messages.error(request, 'Name is required.')
            
            return redirect('prescope_manage')

class PrescriptionScopeDeleteView(DeleteView):
    model = PrescriptionScope
    success_url = reverse_lazy('prescope_manage')
    
    def delete(self, request, *args, **kwargs):
        messages.success(request, 'Prescription scope deleted successfully.')
        return super().delete(request, *args, **kwargs)

# UnitNo views
class UnitNoListView(ListView):
    model = UnitNo
    template_name = 'masters/unitno_master.html'
    context_object_name = 'unitno_list'
    paginate_by = 20

    def get_queryset(self):
        return UnitNo.objects.all().order_by('unit_name')
    
    def post(self, request, *args, **kwargs):
        """Handle POST requests for creating new units"""
        unit_name = request.POST.get('unit_name')
        is_active = request.POST.get('is_active') == 'on'
        
        if unit_name:
            try:
                UnitNo.objects.create(
                    unit_name=unit_name,
                    is_active=is_active
                )
                messages.success(request, f'Unit "{unit_name}" created successfully.')
            except Exception as e:
                messages.error(request, f'Error creating unit: {str(e)}')
        else:
            messages.error(request, 'Unit name is required.')
        
        return redirect('unit_list')

class UnitNoCreateView(CreateView):
    model = UnitNo
    fields = ['unit_name', 'is_active']
    template_name = 'masters/unitno_form.html'
    success_url = reverse_lazy('unit_list')
    
    def form_valid(self, form):
        messages.success(self.request, 'Unit created successfully.')
        return super().form_valid(form)

class UnitNoUpdateView(UpdateView):
    model = UnitNo
    fields = ['unit_name', 'is_active']
    template_name = 'masters/unitno_form.html'
    success_url = reverse_lazy('unit_list')
    
    def form_valid(self, form):
        messages.success(self.request, 'Unit updated successfully.')
        return super().form_valid(form)

class UnitNoDeleteView(DeleteView):
    model = UnitNo
    success_url = reverse_lazy('unit_list')

    def delete(self, request, *args, **kwargs):
        messages.success(request, 'Unit deleted successfully.')
        return super().delete(request, *args, **kwargs)

@login_required
@super_admin_required
def unit_no_enable(request, pk):
    unit = get_object_or_404(UnitNo, pk=pk)
    unit.is_active = True
    unit.save()
    messages.success(request, f'Unit {unit.unit_name} enabled successfully.')
    return redirect('unit_list')

@login_required
@super_admin_required
def unit_no_disable(request, pk):
    unit = get_object_or_404(UnitNo, pk=pk)
    unit.is_active = False
    unit.save()
    messages.success(request, f'Unit {unit.unit_name} disabled successfully.')
    return redirect('unit_list')

# Master Management Dashboard
@login_required
@super_admin_required
def master_management_dashboard(request):
    """Comprehensive master management dashboard for Super Admin"""
    context = {
        'master_tables': [
            {
                'name': 'Therapy Master',
                'model': 'TherapyMaster',
                'url': 'therapy_master_manage',
                'description': 'Manage therapy types and details',
                'count': TherapyMaster.objects.count(),
                'active_count': TherapyMaster.objects.filter(is_active=True).count(),
            },
            {
                'name': 'Item Master',
                'model': 'ItemMaster',
                'url': 'item_master_manage',
                'description': 'Manage items used in therapies',
                'count': ItemMaster.objects.count(),
                'active_count': ItemMaster.objects.filter(is_active=True).count(),
            },
            {
                'name': 'Slot Master',
                'model': 'SlotMaster',
                'url': 'slot_master_manage',
                'description': 'Manage therapy time slots',
                'count': SlotMaster.objects.count(),
                'active_count': SlotMaster.objects.filter(is_active=True).count(),
            },
            {
                'name': 'Therapist Master',
                'model': 'TherapistMaster',
                'url': 'therapist_master_manage',
                'description': 'Manage therapists and their details',
                'count': TherapistMaster.objects.count(),
                'active_count': TherapistMaster.objects.filter(is_active=True).count(),
            },
            {
                'name': 'Procurement Sources',
                'model': 'Procured',
                'url': 'procured_manage',
                'description': 'Manage procurement sources',
                'count': Procured.objects.count(),
                'active_count': Procured.objects.filter(is_active=True).count(),
            },
            {
                'name': 'Oil Classes',
                'model': 'OilClass',
                'url': 'oilclass_manage',
                'description': 'Manage oil categories',
                'count': OilClass.objects.count(),
                'active_count': OilClass.objects.filter(is_active=True).count(),
            },
            {
                'name': 'Usage Types',
                'model': 'UsageType',
                'url': 'usagetype_manage',
                'description': 'Manage usage types',
                'count': UsageType.objects.count(),
                'active_count': UsageType.objects.filter(is_active=True).count(),
            },
            {
                'name': 'Prescription Times',
                'model': 'PrescriptionTime',
                'url': 'prestime_manage',
                'description': 'Manage prescription time slots',
                'count': PrescriptionTime.objects.count(),
                'active_count': PrescriptionTime.objects.filter(is_active=True).count(),
            },
            {
                'name': 'Prescription Scopes',
                'model': 'PrescriptionScope',
                'url': 'prescope_manage',
                'description': 'Manage prescription scopes',
                'count': PrescriptionScope.objects.count(),
                'active_count': PrescriptionScope.objects.filter(is_active=True).count(),
            },
            {
                'name': 'Unit Numbers',
                'model': 'UnitNo',
                'url': 'unit_list',
                'description': 'Manage unit measurements',
                'count': UnitNo.objects.count(),
                'active_count': UnitNo.objects.filter(is_active=True).count(),
            },
        ]
    }
    return render(request, 'masters/master_management_dashboard.html', context)

# Therapy Master CRUD Views
class TherapyMasterManagementView(ListView):
    model = TherapyMaster
    template_name = 'masters/therapy_master_manage.html'
    context_object_name = 'therapy_list'
    paginate_by = 20

    def get_queryset(self):
        return TherapyMaster.objects.all().order_by('therapy_name')

class TherapyMasterCreateView(CreateView):
    model = TherapyMaster
    fields = ['therapy_code', 'therapy_name', 'therapy_group', 'therapy_category', 'therapy_duration', 'bathing_required', 'treatment_room_required', 'cost_of_therapy', 'no_of_super_senior_therapist', 'no_of_senior_therapist', 'no_of_junior_therapist', 'no_of_trainee_therapist', 'total_no_of_therapist', 'is_active']
    template_name = 'masters/therapy_master_form.html'
    success_url = reverse_lazy('therapy_master_manage')
    
    def form_valid(self, form):
        messages.success(self.request, 'Therapy created successfully.')
        return super().form_valid(form)

class TherapyMasterUpdateView(UpdateView):
    model = TherapyMaster
    fields = ['therapy_code', 'therapy_name', 'therapy_group', 'therapy_category', 'therapy_duration', 'bathing_required', 'treatment_room_required', 'cost_of_therapy', 'no_of_super_senior_therapist', 'no_of_senior_therapist', 'no_of_junior_therapist', 'no_of_trainee_therapist', 'total_no_of_therapist', 'is_active']
    template_name = 'masters/therapy_master_form.html'
    success_url = reverse_lazy('therapy_master_manage')
    
    def form_valid(self, form):
        messages.success(self.request, 'Therapy updated successfully.')
        return super().form_valid(form)

class TherapyMasterDeleteView(DeleteView):
    model = TherapyMaster
    success_url = reverse_lazy('therapy_master_manage')
    
    def delete(self, request, *args, **kwargs):
        messages.success(request, 'Therapy deleted successfully.')
        return super().delete(request, *args, **kwargs)

# Item Master CRUD Views
class ItemMasterManagementView(ListView):
    model = ItemMaster
    template_name = 'masters/item_master_manage.html'
    context_object_name = 'item_list'
    paginate_by = 20

    def get_queryset(self):
        return ItemMaster.objects.all().order_by('item_name')

class ItemMasterCreateView(CreateView):
    model = ItemMaster
    fields = ['item_code', 'item_name', 'item_category', 'unit_of_measure', 'is_active']
    template_name = 'masters/item_master_form.html'
    success_url = reverse_lazy('item_master_manage')
    
    def form_valid(self, form):
        messages.success(self.request, 'Item created successfully.')
        return super().form_valid(form)

class ItemMasterUpdateView(UpdateView):
    model = ItemMaster
    fields = ['item_code', 'item_name', 'item_category', 'unit_of_measure', 'is_active']
    template_name = 'masters/item_master_form.html'
    success_url = reverse_lazy('item_master_manage')
    
    def form_valid(self, form):
        messages.success(self.request, 'Item updated successfully.')
        return super().form_valid(form)

class ItemMasterDeleteView(DeleteView):
    model = ItemMaster
    success_url = reverse_lazy('item_master_manage')
    
    def delete(self, request, *args, **kwargs):
        messages.success(request, 'Item deleted successfully.')
        return super().delete(request, *args, **kwargs)

# Slot Master CRUD Views
class SlotMasterManagementView(ListView):
    model = SlotMaster
    template_name = 'masters/slot_master_manage.html'
    context_object_name = 'slot_list'
    paginate_by = 20

    def get_queryset(self):
        return SlotMaster.objects.all().order_by('slot_number')

class SlotMasterCreateView(CreateView):
    model = SlotMaster
    fields = ['slot_number', 'slot_name', 'start_time', 'end_time', 'is_active']
    template_name = 'masters/slot_master_form.html'
    success_url = reverse_lazy('slot_master_manage')
    
    def form_valid(self, form):
        messages.success(self.request, 'Slot created successfully.')
        return super().form_valid(form)

class SlotMasterUpdateView(UpdateView):
    model = SlotMaster
    fields = ['slot_number', 'slot_name', 'start_time', 'end_time', 'is_active']
    template_name = 'masters/slot_master_form.html'
    success_url = reverse_lazy('slot_master_manage')
    
    def form_valid(self, form):
        messages.success(self.request, 'Slot updated successfully.')
        return super().form_valid(form)

class SlotMasterDeleteView(DeleteView):
    model = SlotMaster
    success_url = reverse_lazy('slot_master_manage')
    
    def delete(self, request, *args, **kwargs):
        messages.success(request, 'Slot deleted successfully.')
        return super().delete(request, *args, **kwargs)

# Therapist Master CRUD Views
class TherapistMasterManagementView(ListView):
    model = TherapistMaster
    template_name = 'masters/therapist_master_manage.html'
    context_object_name = 'therapist_list'
    paginate_by = 20

    def get_queryset(self):
        return TherapistMaster.objects.prefetch_related('leaves').all().order_by('therapist_name')

class TherapistMasterCreateView(CreateView):
    model = TherapistMaster
    fields = ['therapist_code', 'therapist_name', 'therapist_grade', 'employee_code', 'is_bathing_therapist', 'is_active']
    template_name = 'masters/therapist_master_form.html'
    success_url = reverse_lazy('therapist_master_manage')
    
    def form_valid(self, form):
        """Create user account and profile when creating therapist master"""
        therapist_code = form.cleaned_data['therapist_code']
        therapist_name = form.cleaned_data['therapist_name']
        therapist_grade = form.cleaned_data.get('therapist_grade', 'Junior')
        employee_code = form.cleaned_data['employee_code']
        is_bathing_therapist = form.cleaned_data.get('is_bathing_therapist', True)
        
        # Check if therapist already has a user
        existing_therapist = TherapistMaster.objects.filter(therapist_code=therapist_code).first()
        if existing_therapist and existing_therapist.user:
            messages.warning(self.request, f'Therapist "{therapist_code}" already has a user account.')
            return super().form_valid(form)
        
        # Generate username and email
        username = therapist_code.lower().replace(' ', '_')
        email = f"{username}@avcri.local"
        
        # Check if username exists
        from authentication.models import CustomUser
        if CustomUser.objects.filter(username=username).exists():
            username = f"{username}_{therapist_code}"
        
        # Split name
        name_parts = therapist_name.split(maxsplit=1)
        first_name = name_parts[0] if name_parts else therapist_name
        last_name = name_parts[1] if len(name_parts) > 1 else ''
        
        # Create user account
        default_password = f"{therapist_code}@{employee_code}"
        user = CustomUser.objects.create_user(
            username=username,
            email=email,
            password=default_password,
            first_name=first_name,
            last_name=last_name,
            role='therapist'
        )
        
        # Create therapist profile
        from authentication.models import TherapistProfile
        therapist_profile = TherapistProfile.objects.create(
            user=user,
            therapist_code=therapist_code,
            employee_code=employee_code,
            therapist_grade=therapist_grade,
            is_bathing_therapist=is_bathing_therapist
        )
        
        # Link user and profile to the therapist master instance
        instance = form.save(commit=False)
        instance.user = user
        instance.therapist_profile = therapist_profile
        instance.save()
        
        messages.success(self.request, f'Therapist user account created successfully. Username: {username}, Default password: {default_password}')
        return super().form_valid(form)

class TherapistMasterUpdateView(UpdateView):
    model = TherapistMaster
    fields = ['therapist_code', 'therapist_name', 'therapist_grade', 'employee_code', 'is_bathing_therapist', 'is_active']
    template_name = 'masters/therapist_master_form.html'
    success_url = reverse_lazy('therapist_master_manage')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Add leave management context
        context['therapist_leaves'] = [
            (0, 'Monday'), (1, 'Tuesday'), (2, 'Wednesday'), (3, 'Thursday'),
            (4, 'Friday'), (5, 'Saturday'), (6, 'Sunday')
        ]
        
        # Get existing leave days for this therapist
        existing_leaves = TherapistLeaveMaster.objects.filter(
            therapist=self.object, is_active=True
        ).values_list('leave_day', flat=True)
        context['existing_leaves'] = list(existing_leaves)
        
        return context
    
    def form_valid(self, form):
        # Save the therapist first
        response = super().form_valid(form)
        
        # Handle leave days
        if 'leave_days' in self.request.POST:
            selected_days = self.request.POST.getlist('leave_days')
            
            # Remove existing leave records for this therapist
            TherapistLeaveMaster.objects.filter(therapist=self.object).delete()
            
            # Create new leave records for selected days
            for day in selected_days:
                TherapistLeaveMaster.objects.create(
                    therapist=self.object,
                    leave_day=int(day),
                    is_active=True
                )
        else:
            # If no days selected, remove all leave records
            TherapistLeaveMaster.objects.filter(therapist=self.object).delete()
        
        messages.success(self.request, 'Therapist and leave schedule updated successfully.')
        return response

class TherapistMasterDeleteView(DeleteView):
    model = TherapistMaster
    success_url = reverse_lazy('therapist_master_manage')
    
    def delete(self, request, *args, **kwargs):
        messages.success(request, 'Therapist deleted successfully.')
        return super().delete(request, *args, **kwargs)

# Therapist Management API endpoints
@login_required
@super_admin_required
@require_http_methods(["POST"])
@csrf_exempt
def create_therapist(request):
    """API endpoint to create therapist (Super Admin only) - Creates user account and profile"""
    try:
        data = json.loads(request.body)
        
        therapist_code = data['therapist_code']
        therapist_name = data['therapist_name']
        therapist_grade = data.get('therapist_grade', 'Junior')
        employee_code = data['employee_code']
        is_bathing_therapist = data.get('is_bathing_therapist', True)
        is_active = data.get('is_active', True)
        
        # Check if therapist already exists
        if TherapistMaster.objects.filter(therapist_code=therapist_code).exists():
            return JsonResponse({'error': f'Therapist with code "{therapist_code}" already exists'}, status=400)
        
        # Generate username from therapist name or code
        username = data.get('username') or therapist_code.lower().replace(' ', '_')
        email = data.get('email') or f"{username}@avcri.local"
        password = data.get('password') or f"{therapist_code}@{employee_code}"  # Default password
        
        # Create user account
        from authentication.models import CustomUser, TherapistProfile
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        # Check if username already exists
        if User.objects.filter(username=username).exists():
            username = f"{username}_{therapist_code}"  # Append code if duplicate
        
        # Split name into first and last name
        name_parts = therapist_name.split(maxsplit=1)
        first_name = name_parts[0] if name_parts else therapist_name
        last_name = name_parts[1] if len(name_parts) > 1 else ''
        
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            role='therapist',
            mobile=data.get('mobile', ''),
            gender=data.get('gender', 'male')
        )
        
        # Create therapist profile
        therapist_profile = TherapistProfile.objects.create(
            user=user,
            therapist_code=therapist_code,
            employee_code=employee_code,
            therapist_grade=therapist_grade,
            is_bathing_therapist=is_bathing_therapist,
            department=data.get('department', ''),
            specialization=data.get('specialization', 'General Therapy')
        )
        
        # Create therapist master record
        therapist = TherapistMaster.objects.create(
            user=user,
            therapist_profile=therapist_profile,
            therapist_code=therapist_code,
            therapist_name=therapist_name,
            therapist_grade=therapist_grade,
            employee_code=employee_code,
            is_bathing_therapist=is_bathing_therapist,
            is_active=is_active
        )
        
        return JsonResponse({
            'success': True, 
            'id': therapist.id,
            'user_id': user.id,
            'username': username,
            'message': f'Therapist user account created. Default password: {password}'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@super_admin_required
@require_http_methods(["POST"])
@csrf_exempt
def create_therapist_leave(request):
    """API endpoint to create therapist leave (Super Admin only)"""
    try:
        data = json.loads(request.body)
        
        therapist = get_object_or_404(TherapistMaster, therapist_code=data['therapist_code'])
        
        leave = TherapistLeaveMaster.objects.create(
            therapist=therapist,
            leave_day=data['leave_day'],
            is_active=data.get('is_active', True)
        )
        
        return JsonResponse({'success': True, 'id': leave.id})
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@super_admin_required
@require_http_methods(["PUT"])
@csrf_exempt
def update_therapist(request, therapist_id):
    """API endpoint to update therapist (Super Admin only)"""
    try:
        data = json.loads(request.body)
        therapist = get_object_or_404(TherapistMaster, id=therapist_id)
        
        therapist.therapist_name = data.get('therapist_name', therapist.therapist_name)
        therapist.therapist_grade = data.get('therapist_grade', therapist.therapist_grade)
        therapist.employee_code = data.get('employee_code', therapist.employee_code)
        therapist.is_bathing_therapist = data.get('is_bathing_therapist', therapist.is_bathing_therapist)
        therapist.is_active = data.get('is_active', therapist.is_active)
        therapist.save()
        
        return JsonResponse({'success': True})
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@super_admin_required
@require_http_methods(["DELETE"])
@csrf_exempt
def delete_therapist(request, therapist_id):
    """API endpoint to delete therapist (Super Admin only)"""
    try:
        therapist = get_object_or_404(TherapistMaster, id=therapist_id)
        therapist.delete()
        return JsonResponse({'success': True})
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@super_admin_required
@require_http_methods(["DELETE"])
@csrf_exempt
def delete_therapist_leave(request, leave_id):
    """API endpoint to delete therapist leave (Super Admin only)"""
    try:
        leave = get_object_or_404(TherapistLeaveMaster, id=leave_id)
        leave.delete()
        return JsonResponse({'success': True})
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)