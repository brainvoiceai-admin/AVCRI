from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.db import models as db_models
from django import forms
from authentication.decorators import super_admin_required, module_access_required
from .models import (
    Procured, OilClass, UsageType, PrescriptionUsage, PrescriptionTime, 
    PrescriptionScope, UnitNo, TherapyMaster, ItemMaster, SlotMaster,
    TherapistGrade, TherapistMaster, TherapistLeaveMaster, NurseTreatmentMaster,
    NurseMaster
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
                'slot_number', 'slot_name', 'slot_time'
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
            from datetime import datetime
            slot_time_str = data.get('slot_time') or data.get('start_time', '09:00')
            # Convert string to time if needed
            if isinstance(slot_time_str, str):
                try:
                    slot_time = datetime.strptime(slot_time_str, '%H:%M').time()
                except:
                    slot_time = datetime.strptime(slot_time_str, '%H:%M:%S').time()
            else:
                slot_time = slot_time_str
            item = SlotMaster.objects.create(
                slot_number=data['slot_number'],
                slot_time=slot_time,
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
            slot_time = data.get('slot_time') or data.get('start_time')
            if slot_time:
                from datetime import datetime
                if isinstance(slot_time, str):
                    try:
                        item.slot_time = datetime.strptime(slot_time, '%H:%M').time()
                    except:
                        item.slot_time = datetime.strptime(slot_time, '%H:%M:%S').time()
                else:
                    item.slot_time = slot_time
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
        """Handle POST requests for creating new procurement sources"""
        name = request.POST.get('name')
        is_active = request.POST.get('is_active') == 'on'
        
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

class ProcuredUpdateView(UpdateView):
    model = Procured
    fields = ['name', 'is_active']
    template_name = 'masters/procured_form.html'
    success_url = reverse_lazy('procured_manage')
    
    def form_valid(self, form):
        messages.success(self.request, 'Procurement source updated successfully.')
        return super().form_valid(form)

@login_required
@super_admin_required
def procured_delete(request, pk):
    """Delete a procurement source - function-based view to handle GET requests properly"""
    procured = get_object_or_404(Procured, pk=pk)
    procured_name = procured.name
    procured.delete()
    messages.success(request, f'Procurement source "{procured_name}" deleted successfully.')
    return redirect('procured_manage')

@login_required
@super_admin_required
def procured_enable(request, pk):
    """Enable a procurement source"""
    procured = get_object_or_404(Procured, pk=pk)
    procured.is_active = True
    procured.save()
    messages.success(request, f'Procurement source "{procured.name}" enabled successfully.')
    return redirect('procured_manage')

@login_required
@super_admin_required
def procured_disable(request, pk):
    """Disable a procurement source"""
    procured = get_object_or_404(Procured, pk=pk)
    procured.is_active = False
    procured.save()
    messages.success(request, f'Procurement source "{procured.name}" disabled successfully.')
    return redirect('procured_manage')

class OilClassManagementView(ListView):
    model = OilClass
    template_name = 'masters/oilclass_manage.html'
    context_object_name = 'oilclass_list'
    paginate_by = 20

    def get_queryset(self):
        return OilClass.objects.all().order_by('name')
    
    def post(self, request, *args, **kwargs):
        """Handle POST requests for creating new oil classes"""
        name = request.POST.get('name')
        is_active = request.POST.get('is_active') == 'on'
        
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

class OilClassUpdateView(UpdateView):
    model = OilClass
    fields = ['name', 'is_active']
    template_name = 'masters/oilclass_form.html'
    success_url = reverse_lazy('oilclass_manage')
    
    def form_valid(self, form):
        messages.success(self.request, 'Oil class updated successfully.')
        return super().form_valid(form)

@login_required
@super_admin_required
def oil_class_delete(request, pk):
    """Delete an oil class - function-based view to handle GET requests properly"""
    oil_class = get_object_or_404(OilClass, pk=pk)
    oil_class_name = oil_class.name
    oil_class.delete()
    messages.success(request, f'Oil class "{oil_class_name}" deleted successfully.')
    return redirect('oilclass_manage')

@login_required
@super_admin_required
def oil_class_enable(request, pk):
    """Enable an oil class"""
    oil_class = get_object_or_404(OilClass, pk=pk)
    oil_class.is_active = True
    oil_class.save()
    messages.success(request, f'Oil class "{oil_class.name}" enabled successfully.')
    return redirect('oilclass_manage')

@login_required
@super_admin_required
def oil_class_disable(request, pk):
    """Disable an oil class"""
    oil_class = get_object_or_404(OilClass, pk=pk)
    oil_class.is_active = False
    oil_class.save()
    messages.success(request, f'Oil class "{oil_class.name}" disabled successfully.')
    return redirect('oilclass_manage')

class UsageTypeManagementView(ListView):
    model = UsageType
    template_name = 'masters/usagetype_manage.html'
    context_object_name = 'usagetype_list'
    paginate_by = 20

    def get_queryset(self):
        return UsageType.objects.all().order_by('name')
    
    def post(self, request, *args, **kwargs):
        """Handle POST requests for creating new usage types"""
        name = request.POST.get('name')
        is_active = request.POST.get('is_active') == 'on'
        
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

class UsageTypeUpdateView(UpdateView):
    model = UsageType
    fields = ['name', 'is_active']
    template_name = 'masters/usagetype_form.html'
    success_url = reverse_lazy('usagetype_manage')
    
    def form_valid(self, form):
        messages.success(self.request, 'Usage type updated successfully.')
        return super().form_valid(form)

@login_required
@super_admin_required
def usage_type_delete(request, pk):
    """Delete a usage type - function-based view to handle GET requests properly"""
    usage_type = get_object_or_404(UsageType, pk=pk)
    usage_type_name = usage_type.name
    usage_type.delete()
    messages.success(request, f'Usage type "{usage_type_name}" deleted successfully.')
    return redirect('usagetype_manage')

@login_required
@super_admin_required
def usage_type_enable(request, pk):
    """Enable a usage type"""
    usage_type = get_object_or_404(UsageType, pk=pk)
    usage_type.is_active = True
    usage_type.save()
    messages.success(request, f'Usage type "{usage_type.name}" enabled successfully.')
    return redirect('usagetype_manage')

@login_required
@super_admin_required
def usage_type_disable(request, pk):
    """Disable a usage type"""
    usage_type = get_object_or_404(UsageType, pk=pk)
    usage_type.is_active = False
    usage_type.save()
    messages.success(request, f'Usage type "{usage_type.name}" disabled successfully.')
    return redirect('usagetype_manage')

# Prescription Usage Management Views
@method_decorator(module_access_required('prescription_usage_manage'), name='dispatch')
class PrescriptionUsageManagementView(ListView):
    model = PrescriptionUsage
    template_name = 'masters/prescriptionusage_manage.html'
    context_object_name = 'prescriptionusage_list'
    paginate_by = 20

    def get_queryset(self):
        return PrescriptionUsage.objects.all().order_by('name')
    
    def post(self, request, *args, **kwargs):
        """Handle POST requests for creating new prescription usages"""
        name = request.POST.get('name')
        is_active = request.POST.get('is_active') == 'on'
        
        # Create new record
        if name:
            try:
                PrescriptionUsage.objects.create(
                    name=name,
                    is_active=is_active
                )
                messages.success(request, f'Prescription usage "{name}" created successfully.')
            except Exception as e:
                messages.error(request, f'Error creating prescription usage: {str(e)}')
        else:
            messages.error(request, 'Name is required.')
        
        return redirect('prescriptionusage_manage')

@method_decorator(module_access_required('prescription_usage_manage'), name='dispatch')
class PrescriptionUsageUpdateView(UpdateView):
    model = PrescriptionUsage
    fields = ['name', 'is_active']
    template_name = 'masters/prescriptionusage_form.html'
    success_url = reverse_lazy('prescriptionusage_manage')
    
    def form_valid(self, form):
        messages.success(self.request, 'Prescription usage updated successfully.')
        return super().form_valid(form)

@login_required
@module_access_required('prescription_usage_manage')
def prescription_usage_delete(request, pk):
    """Delete a prescription usage - function-based view to handle GET requests properly"""
    prescription_usage = get_object_or_404(PrescriptionUsage, pk=pk)
    prescription_usage_name = prescription_usage.name
    prescription_usage.delete()
    messages.success(request, f'Prescription usage "{prescription_usage_name}" deleted successfully.')
    return redirect('prescriptionusage_manage')

@login_required
@module_access_required('prescription_usage_manage')
def prescription_usage_enable(request, pk):
    """Enable a prescription usage"""
    prescription_usage = get_object_or_404(PrescriptionUsage, pk=pk)
    prescription_usage.is_active = True
    prescription_usage.save()
    messages.success(request, f'Prescription usage "{prescription_usage.name}" enabled successfully.')
    return redirect('prescriptionusage_manage')

@login_required
@module_access_required('prescription_usage_manage')
def prescription_usage_disable(request, pk):
    """Disable a prescription usage"""
    prescription_usage = get_object_or_404(PrescriptionUsage, pk=pk)
    prescription_usage.is_active = False
    prescription_usage.save()
    messages.success(request, f'Prescription usage "{prescription_usage.name}" disabled successfully.')
    return redirect('prescriptionusage_manage')

# Nurse Treatment Master Management Views
@method_decorator(super_admin_required, name='dispatch')
class NurseTreatmentMasterManagementView(ListView):
    model = NurseTreatmentMaster
    template_name = 'masters/nursetreatment_manage.html'
    context_object_name = 'nursetreatment_list'
    paginate_by = 20

    def get_queryset(self):
        return NurseTreatmentMaster.objects.all().order_by('treatment_code')
    
    def post(self, request, *args, **kwargs):
        """Handle POST requests for creating new nurse treatments"""
        treatment_code = request.POST.get('treatment_code')
        name = request.POST.get('name')
        number_of_nurse_required = request.POST.get('number_of_nurse_required', 1)
        is_active = request.POST.get('is_active') == 'on'
        
        # Create new record
        if treatment_code and name:
            try:
                NurseTreatmentMaster.objects.create(
                    treatment_code=treatment_code,
                    name=name,
                    number_of_nurse_required=int(number_of_nurse_required) if number_of_nurse_required else 1,
                    is_active=is_active
                )
                messages.success(request, f'Nurse treatment "{treatment_code} - {name}" created successfully.')
            except Exception as e:
                messages.error(request, f'Error creating nurse treatment: {str(e)}')
        else:
            messages.error(request, 'Treatment code and name are required.')
        
        return redirect('nursetreatment_manage')

@method_decorator(super_admin_required, name='dispatch')
class NurseTreatmentMasterUpdateView(UpdateView):
    model = NurseTreatmentMaster
    fields = ['treatment_code', 'name', 'number_of_nurse_required', 'is_active']
    template_name = 'masters/nursetreatment_form.html'
    success_url = reverse_lazy('nursetreatment_manage')
    
    def form_valid(self, form):
        messages.success(self.request, 'Nurse treatment updated successfully.')
        return super().form_valid(form)

@login_required
@super_admin_required
def nurse_treatment_delete(request, pk):
    """Delete a nurse treatment - function-based view to handle GET requests properly"""
    treatment = get_object_or_404(NurseTreatmentMaster, pk=pk)
    treatment_name = f"{treatment.treatment_code} - {treatment.name}"
    treatment.delete()
    messages.success(request, f'Nurse treatment "{treatment_name}" deleted successfully.')
    return redirect('nursetreatment_manage')

@login_required
@super_admin_required
def nurse_treatment_enable(request, pk):
    """Enable a nurse treatment"""
    treatment = get_object_or_404(NurseTreatmentMaster, pk=pk)
    treatment.is_active = True
    treatment.save()
    messages.success(request, f'Nurse treatment "{treatment.treatment_code} - {treatment.name}" enabled successfully.')
    return redirect('nursetreatment_manage')

@login_required
@super_admin_required
def nurse_treatment_disable(request, pk):
    """Disable a nurse treatment"""
    treatment = get_object_or_404(NurseTreatmentMaster, pk=pk)
    treatment.is_active = False
    treatment.save()
    messages.success(request, f'Nurse treatment "{treatment.treatment_code} - {treatment.name}" disabled successfully.')
    return redirect('nursetreatment_manage')

# Nurse Master Management Views
@method_decorator(super_admin_required, name='dispatch')
class NurseMasterManagementView(ListView):
    model = NurseMaster
    template_name = 'masters/nursemaster_manage.html'
    context_object_name = 'nursemaster_list'
    paginate_by = 20

    def get_queryset(self):
        return NurseMaster.objects.all().order_by('nurse_code')
    
    def post(self, request, *args, **kwargs):
        """Handle POST requests for creating new nurses"""
        nurse_code = request.POST.get('nurse_code')
        nurse_name = request.POST.get('nurse_name')
        designation = request.POST.get('designation', '')
        is_active = request.POST.get('is_active') == 'on'
        
        # Create new record
        if nurse_code and nurse_name:
            try:
                NurseMaster.objects.create(
                    nurse_code=nurse_code,
                    nurse_name=nurse_name,
                    designation=designation,
                    is_active=is_active
                )
                messages.success(request, f'Nurse "{nurse_code} - {nurse_name}" created successfully.')
            except Exception as e:
                messages.error(request, f'Error creating nurse: {str(e)}')
        else:
            messages.error(request, 'Nurse code and name are required.')
        
        return redirect('nursemaster_manage')

@method_decorator(super_admin_required, name='dispatch')
class NurseMasterUpdateView(UpdateView):
    model = NurseMaster
    fields = ['nurse_code', 'nurse_name', 'designation', 'is_active']
    template_name = 'masters/nursemaster_form.html'
    success_url = reverse_lazy('nursemaster_manage')
    
    def form_valid(self, form):
        messages.success(self.request, 'Nurse updated successfully.')
        return super().form_valid(form)

@login_required
@super_admin_required
def nurse_master_delete(request, pk):
    """Delete a nurse - function-based view to handle GET requests properly"""
    nurse = get_object_or_404(NurseMaster, pk=pk)
    nurse_name = f"{nurse.nurse_code} - {nurse.nurse_name}"
    nurse.delete()
    messages.success(request, f'Nurse "{nurse_name}" deleted successfully.')
    return redirect('nursemaster_manage')

@login_required
@super_admin_required
def nurse_master_enable(request, pk):
    """Enable a nurse"""
    nurse = get_object_or_404(NurseMaster, pk=pk)
    nurse.is_active = True
    nurse.save()
    messages.success(request, f'Nurse "{nurse.nurse_code} - {nurse.nurse_name}" enabled successfully.')
    return redirect('nursemaster_manage')

@login_required
@super_admin_required
def nurse_master_disable(request, pk):
    """Disable a nurse"""
    nurse = get_object_or_404(NurseMaster, pk=pk)
    nurse.is_active = False
    nurse.save()
    messages.success(request, f'Nurse "{nurse.nurse_code} - {nurse.nurse_name}" disabled successfully.')
    return redirect('nursemaster_manage')

class PrescriptionTimeManagementView(ListView):
    model = PrescriptionTime
    template_name = 'masters/prestime_manage.html'
    context_object_name = 'prestime_list'
    paginate_by = 20

    def get_queryset(self):
        return PrescriptionTime.objects.all().order_by('name')
    
    def post(self, request, *args, **kwargs):
        """Handle POST requests for creating new prescription times"""
        name = request.POST.get('name')
        is_active = request.POST.get('is_active') == 'on'
        
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

class PrescriptionTimeUpdateView(UpdateView):
    model = PrescriptionTime
    fields = ['name', 'is_active']
    template_name = 'masters/prestime_form.html'
    success_url = reverse_lazy('prestime_manage')
    
    def form_valid(self, form):
        messages.success(self.request, 'Prescription time updated successfully.')
        return super().form_valid(form)

@login_required
@super_admin_required
def prescription_time_delete(request, pk):
    """Delete a prescription time - function-based view to handle GET requests properly"""
    time = get_object_or_404(PrescriptionTime, pk=pk)
    time_name = time.name
    time.delete()
    messages.success(request, f'Prescription time "{time_name}" deleted successfully.')
    return redirect('prestime_manage')

@login_required
@super_admin_required
def prescription_time_enable(request, pk):
    """Enable a prescription time"""
    time = get_object_or_404(PrescriptionTime, pk=pk)
    time.is_active = True
    time.save()
    messages.success(request, f'Prescription time "{time.name}" enabled successfully.')
    return redirect('prestime_manage')

@login_required
@super_admin_required
def prescription_time_disable(request, pk):
    """Disable a prescription time"""
    time = get_object_or_404(PrescriptionTime, pk=pk)
    time.is_active = False
    time.save()
    messages.success(request, f'Prescription time "{time.name}" disabled successfully.')
    return redirect('prestime_manage')

class PrescriptionScopeManagementView(ListView):
    model = PrescriptionScope
    template_name = 'masters/prescope_manage.html'
    context_object_name = 'prescope_list'
    paginate_by = 20

    def get_queryset(self):
        return PrescriptionScope.objects.all().order_by('name')
    
    def post(self, request, *args, **kwargs):
        """Handle POST requests for creating new prescription scopes"""
        name = request.POST.get('name')
        is_active = request.POST.get('is_active') == 'on'
        
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

class PrescriptionScopeUpdateView(UpdateView):
    model = PrescriptionScope
    fields = ['name', 'is_active']
    template_name = 'masters/prescope_form.html'
    success_url = reverse_lazy('prescope_manage')
    
    def form_valid(self, form):
        messages.success(self.request, 'Prescription scope updated successfully.')
        return super().form_valid(form)

@login_required
@super_admin_required
def prescription_scope_delete(request, pk):
    """Delete a prescription scope - function-based view to handle GET requests properly"""
    scope = get_object_or_404(PrescriptionScope, pk=pk)
    scope_name = scope.name
    scope.delete()
    messages.success(request, f'Prescription scope "{scope_name}" deleted successfully.')
    return redirect('prescope_manage')

@login_required
@super_admin_required
def prescription_scope_enable(request, pk):
    """Enable a prescription scope"""
    scope = get_object_or_404(PrescriptionScope, pk=pk)
    scope.is_active = True
    scope.save()
    messages.success(request, f'Prescription scope "{scope.name}" enabled successfully.')
    return redirect('prescope_manage')

@login_required
@super_admin_required
def prescription_scope_disable(request, pk):
    """Disable a prescription scope"""
    scope = get_object_or_404(PrescriptionScope, pk=pk)
    scope.is_active = False
    scope.save()
    messages.success(request, f'Prescription scope "{scope.name}" disabled successfully.')
    return redirect('prescope_manage')

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

@login_required
@super_admin_required
def unit_no_delete(request, pk):
    """Delete a unit - function-based view to handle GET requests properly"""
    unit = get_object_or_404(UnitNo, pk=pk)
    unit_name = unit.unit_name
    unit.delete()
    messages.success(request, f'Unit "{unit_name}" deleted successfully.')
    return redirect('unit_list')

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
        queryset = TherapyMaster.objects.all()
        
        # Search filter (server-side)
        search = self.request.GET.get('search', '')
        if search:
            queryset = queryset.filter(
                db_models.Q(therapy_code__icontains=search) |
                db_models.Q(therapy_name__icontains=search) |
                db_models.Q(therapy_group__icontains=search)
            )
        
        # Status filter (server-side)
        status = self.request.GET.get('status', '')
        if status == 'active':
            queryset = queryset.filter(is_active=True)
        elif status == 'inactive':
            queryset = queryset.filter(is_active=False)
        
        # Category filter (server-side)
        category = self.request.GET.get('category', '')
        if category:
            queryset = queryset.filter(therapy_category=category)
        
        return queryset.order_by('therapy_name')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search'] = self.request.GET.get('search', '')
        context['status_filter'] = self.request.GET.get('status', '')
        context['category_filter'] = self.request.GET.get('category', '')
        return context

class TherapyMasterCreateView(CreateView):
    model = TherapyMaster
    fields = ['therapy_name', 'therapy_group', 'therapy_category', 'therapy_duration', 'bathing_required', 'treatment_room_required', 'cost_of_therapy', 'no_of_super_senior_therapist', 'no_of_senior_therapist', 'no_of_junior_therapist', 'no_of_trainee_therapist', 'is_active']
    template_name = 'masters/therapy_master_form.html'
    success_url = reverse_lazy('therapy_master_manage')
    
    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # Make therapy_code read-only/hidden since it's auto-generated
        if 'therapy_code' in form.fields:
            form.fields['therapy_code'].widget.attrs['readonly'] = True
        # Update therapy_category to use dropdown with Medium, Hard, Easy
        if 'therapy_category' in form.fields:
            form.fields['therapy_category'].widget = forms.Select(choices=[
                ('', 'Select Category'),
                ('Medium', 'Medium'),
                ('Hard', 'Hard'),
                ('Easy', 'Easy'),
            ])
        return form
    
    def form_valid(self, form):
        # Auto-generate unique therapy code by incrementing from highest existing code
        # Get all existing therapy codes that start with THEB
        existing_codes = TherapyMaster.objects.filter(
            therapy_code__startswith='THEB'
        ).values_list('therapy_code', flat=True)
        
        # Extract numbers from existing codes and find the highest
        max_number = 0
        for code in existing_codes:
            try:
                # Extract number part after 'THEB'
                number_part = int(code.replace('THEB', ''))
                if number_part > max_number:
                    max_number = number_part
            except (ValueError, AttributeError):
                continue
        
        # Increment by 1
        next_number = max_number + 1
        
        # Ensure it doesn't exceed 999
        if next_number > 999:
            raise ValueError("Maximum therapy code limit reached (THEB999)")
        
        # Generate new code
        therapy_code = f"THEB{next_number:03d}"
        
        # Calculate total number of therapists
        instance = form.save(commit=False)
        instance.therapy_code = therapy_code
        instance.total_no_of_therapist = (
            instance.no_of_super_senior_therapist +
            instance.no_of_senior_therapist +
            instance.no_of_junior_therapist +
            instance.no_of_trainee_therapist
        )
        instance.save()
        
        messages.success(self.request, f'Therapy "{instance.therapy_name}" ({therapy_code}) created successfully.')
        return redirect(self.success_url)

class TherapyMasterUpdateView(UpdateView):
    model = TherapyMaster
    fields = ['therapy_name', 'therapy_group', 'therapy_category', 'therapy_duration', 'bathing_required', 'treatment_room_required', 'cost_of_therapy', 'no_of_super_senior_therapist', 'no_of_senior_therapist', 'no_of_junior_therapist', 'no_of_trainee_therapist', 'is_active']
    template_name = 'masters/therapy_master_form.html'
    success_url = reverse_lazy('therapy_master_manage')
    
    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # Make therapy_code read-only since it shouldn't be changed
        if 'therapy_code' in form.fields:
            form.fields['therapy_code'].widget.attrs['readonly'] = True
        # Update therapy_category to use dropdown with Medium, Hard, Easy
        if 'therapy_category' in form.fields:
            form.fields['therapy_category'].widget = forms.Select(choices=[
                ('', 'Select Category'),
                ('Medium', 'Medium'),
                ('Hard', 'Hard'),
                ('Easy', 'Easy'),
            ])
        return form
    
    def form_valid(self, form):
        # Auto-calculate total number of therapists
        instance = form.save(commit=False)
        instance.total_no_of_therapist = (
            instance.no_of_super_senior_therapist +
            instance.no_of_senior_therapist +
            instance.no_of_junior_therapist +
            instance.no_of_trainee_therapist
        )
        instance.save()
        
        messages.success(self.request, f'Therapy "{instance.therapy_name}" updated successfully.')
        return redirect(self.success_url)

@login_required
@super_admin_required
def therapy_master_delete(request, pk):
    """Delete a therapy - function-based view to handle GET requests properly"""
    therapy = get_object_or_404(TherapyMaster, pk=pk)
    therapy_name = therapy.therapy_name
    therapy.delete()
    messages.success(request, f'Therapy "{therapy_name}" deleted successfully.')
    return redirect('therapy_master_manage')

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
    fields = ['slot_number', 'slot_name', 'slot_time', 'is_active']
    template_name = 'masters/slot_master_form.html'
    success_url = reverse_lazy('slot_master_manage')
    
    def form_valid(self, form):
        messages.success(self.request, 'Slot created successfully.')
        return super().form_valid(form)

class SlotMasterUpdateView(UpdateView):
    model = SlotMaster
    fields = ['slot_number', 'slot_name', 'slot_time', 'is_active']
    template_name = 'masters/slot_master_form.html'
    success_url = reverse_lazy('slot_master_manage')
    
    def form_valid(self, form):
        messages.success(self.request, 'Slot updated successfully.')
        return super().form_valid(form)

@login_required
@super_admin_required
def slot_master_delete(request, pk):
    """Delete a slot - function-based view to handle GET requests properly"""
    slot = get_object_or_404(SlotMaster, pk=pk)
    slot_number = slot.slot_number
    slot.delete()
    messages.success(request, f'Slot {slot_number} deleted successfully.')
    return redirect('slot_master_manage')

# Therapist Master CRUD Views
class TherapistMasterManagementView(ListView):
    model = TherapistMaster
    template_name = 'masters/therapist_master_manage.html'
    context_object_name = 'therapist_list'
    paginate_by = 20

    def get_queryset(self):
        queryset = TherapistMaster.objects.prefetch_related('leaves', 'therapist_grade').all()
        
        # Search filter
        search = self.request.GET.get('search', '')
        if search:
            queryset = queryset.filter(
                db_models.Q(therapist_code__icontains=search) |
                db_models.Q(therapist_name__icontains=search) |
                db_models.Q(employee_code__icontains=search)
            )
        
        # Status filter
        status = self.request.GET.get('status', '')
        if status == 'active':
            queryset = queryset.filter(is_active=True)
        elif status == 'inactive':
            queryset = queryset.filter(is_active=False)
        
        # Grade filter
        grade = self.request.GET.get('grade', '')
        if grade:
            queryset = queryset.filter(therapist_grade__id=grade)
        
        return queryset.order_by('therapist_name')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['grades'] = TherapistGrade.objects.filter(is_active=True).order_by('display_order', 'name')
        context['search'] = self.request.GET.get('search', '')
        context['status_filter'] = self.request.GET.get('status', '')
        context['grade_filter'] = self.request.GET.get('grade', '')
        return context

class TherapistMasterCreateView(CreateView):
    model = TherapistMaster
    fields = ['therapist_name', 'therapist_grade', 'employee_code', 'therapist_gender', 'is_bathing_therapist', 'is_active']
    template_name = 'masters/therapist_master_form.html'
    success_url = reverse_lazy('therapist_master_manage')
    
    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # Make therapist_code read-only/hidden since it's auto-generated
        if 'therapist_code' in form.fields:
            form.fields['therapist_code'].widget.attrs['readonly'] = True
        # Update grade field to use TherapistGrade queryset
        if 'therapist_grade' in form.fields:
            form.fields['therapist_grade'].queryset = TherapistGrade.objects.filter(is_active=True).order_by('display_order', 'name')
        # Customize gender field to use Select widget
        if 'therapist_gender' in form.fields:
            form.fields['therapist_gender'].widget = forms.Select(choices=[('', 'Select Gender'), ('Male', 'Male'), ('Female', 'Female')])
            form.fields['therapist_gender'].widget.attrs['class'] = 'form-select'
            form.fields['therapist_gender'].initial = 'Male'
        return form
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['grades'] = TherapistGrade.objects.filter(is_active=True).order_by('display_order', 'name')
        return context
    
    def form_valid(self, form):
        """Create user account and profile when creating therapist master"""
        # Auto-generate unique therapist code by incrementing from highest existing code
        # Get all existing therapist codes that start with THP
        existing_codes = TherapistMaster.objects.filter(
            therapist_code__startswith='THP'
        ).values_list('therapist_code', flat=True)
        
        # Extract numbers from existing codes and find the highest
        max_number = 0
        for code in existing_codes:
            try:
                # Extract number part after 'THP'
                number_part = int(code.replace('THP', ''))
                if number_part > max_number:
                    max_number = number_part
            except (ValueError, AttributeError):
                continue
        
        # Increment by 1
        next_number = max_number + 1
        
        # Ensure it doesn't exceed 9999
        if next_number > 9999:
            raise ValueError("Maximum therapist code limit reached (THP9999)")
        
        # Generate new code
        therapist_code = f"THP{next_number:04d}"
        
        # Set the auto-generated code
        instance = form.save(commit=False)
        instance.therapist_code = therapist_code
        
        therapist_name = form.cleaned_data['therapist_name']
        therapist_grade = form.cleaned_data.get('therapist_grade')
        employee_code = form.cleaned_data['employee_code']
        is_bathing_therapist = form.cleaned_data.get('is_bathing_therapist', True)
        
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
        # Get grade name for profile (if grade is a ForeignKey)
        grade_name = therapist_grade.name if therapist_grade else 'Junior'
        therapist_profile = TherapistProfile.objects.create(
            user=user,
            therapist_code=therapist_code,
            employee_code=employee_code,
            therapist_grade=grade_name,
            is_bathing_therapist=is_bathing_therapist
        )
        
        # Link user and profile to the therapist master instance
        instance.user = user
        instance.therapist_profile = therapist_profile
        instance.save()
        
        messages.success(self.request, f'Therapist "{therapist_name}" ({therapist_code}) created successfully. Username: {username}, Default password: {default_password}')
        return redirect(self.success_url)

class TherapistMasterUpdateView(UpdateView):
    model = TherapistMaster
    fields = ['therapist_name', 'therapist_grade', 'employee_code', 'therapist_gender', 'is_bathing_therapist', 'is_active']
    template_name = 'masters/therapist_master_form.html'
    success_url = reverse_lazy('therapist_master_manage')
    
    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # Make therapist_code read-only since it shouldn't be changed
        if 'therapist_code' in form.fields:
            form.fields['therapist_code'].widget.attrs['readonly'] = True
        # Update grade field to use TherapistGrade queryset
        if 'therapist_grade' in form.fields:
            form.fields['therapist_grade'].queryset = TherapistGrade.objects.filter(is_active=True).order_by('display_order', 'name')
        # Customize gender field to use Select widget
        if 'therapist_gender' in form.fields:
            form.fields['therapist_gender'].widget = forms.Select(choices=[('', 'Select Gender'), ('Male', 'Male'), ('Female', 'Female')])
            form.fields['therapist_gender'].widget.attrs['class'] = 'form-select'
        return form
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['grades'] = TherapistGrade.objects.filter(is_active=True).order_by('display_order', 'name')
        
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

@login_required
@super_admin_required
def therapist_master_delete(request, pk):
    """Delete a therapist - function-based view to handle GET requests properly"""
    therapist = get_object_or_404(TherapistMaster, pk=pk)
    therapist_name = therapist.therapist_name
    therapist_code = therapist.therapist_code
    therapist.delete()
    messages.success(request, f'Therapist "{therapist_name}" ({therapist_code}) deleted successfully.')
    return redirect('therapist_master_manage')

# Therapist Grade CRUD Views
class TherapistGradeManagementView(ListView):
    model = TherapistGrade
    template_name = 'masters/therapistgrade_manage.html'
    context_object_name = 'grade_list'
    paginate_by = 20

    def get_queryset(self):
        return TherapistGrade.objects.all().order_by('display_order', 'name')

class TherapistGradeCreateView(CreateView):
    model = TherapistGrade
    fields = ['name', 'display_order', 'is_active']
    template_name = 'masters/therapistgrade_form.html'
    success_url = reverse_lazy('therapistgrade_manage')
    
    def form_valid(self, form):
        messages.success(self.request, 'Therapist grade created successfully.')
        return super().form_valid(form)

class TherapistGradeUpdateView(UpdateView):
    model = TherapistGrade
    fields = ['name', 'display_order', 'is_active']
    template_name = 'masters/therapistgrade_form.html'
    success_url = reverse_lazy('therapistgrade_manage')
    
    def form_valid(self, form):
        messages.success(self.request, 'Therapist grade updated successfully.')
        return super().form_valid(form)

@login_required
@super_admin_required
def therapist_grade_delete(request, pk):
    """Delete a therapist grade - function-based view"""
    grade = get_object_or_404(TherapistGrade, pk=pk)
    grade_name = grade.name
    # Check if any therapists are using this grade
    if TherapistMaster.objects.filter(therapist_grade=grade).exists():
        messages.error(request, f'Cannot delete grade "{grade_name}" because it is assigned to one or more therapists.')
        return redirect('therapistgrade_manage')
    grade.delete()
    messages.success(request, f'Therapist grade "{grade_name}" deleted successfully.')
    return redirect('therapistgrade_manage')

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