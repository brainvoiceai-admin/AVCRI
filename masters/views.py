from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.views import View
from django import forms # Import forms module
from .models import Procured

# 1. Define the ModelForm within the views.py file
class ProcuredForm(forms.ModelForm):
    class Meta:
        model = Procured
        fields = ['name', 'is_active']
        
        # Optional: Add Bootstrap classes for better styling if not using crispy-forms
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class ProcuredManagementView(View):
    """Handles listing, creating, and updating Procured sources on a single page."""
    
    def get(self, request, pk=None):
        # Read: Get all sources
        sources = Procured.objects.all().order_by('name')
        
        # Determine if we are Creating or Updating
        if pk:
            # Update: Load existing instance
            instance = get_object_or_404(Procured, pk=pk)
            form = ProcuredForm(instance=instance)
            action_url = reverse_lazy('procured_manage_update', kwargs={'pk': pk})
        else:
            # Create: Empty form
            form = ProcuredForm()
            action_url = reverse_lazy('procured_manage')
            
        context = {
            'procured_sources': sources,
            'form': form,
            'action_url': action_url,
            'editing_pk': pk
        }
        return render(request, 'masters/procured_manage.html', context)

    def post(self, request, pk=None):
        # Determine if we are Creating or Updating
        if pk:
            # Update Logic
            instance = get_object_or_404(Procured, pk=pk)
            form = ProcuredForm(request.POST, instance=instance)
        else:
            # Create Logic
            form = ProcuredForm(request.POST)

        if form.is_valid():
            form.save()
            # Redirect to the base list URL on success (removes the ID from the URL)
            return redirect('procured_manage')
        
        # If form is NOT valid, re-render the GET view with errors
        sources = Procured.objects.all().order_by('name')
        context = {
            'procured_sources': sources,
            'form': form,
            'action_url': reverse_lazy('procured_manage_update', kwargs={'pk': pk}) if pk else reverse_lazy('procured_manage'),
            'editing_pk': pk
        }
        return render(request, 'masters/procured_manage.html', context)


class ProcuredDeleteView(View):
    """Handles deletion of a Procured source via POST request."""
    def post(self, request, pk):
        source = get_object_or_404(Procured, pk=pk)
        source.delete()
        return redirect('procured_manage')





#Oil class master

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.views import View
from .models import OilClass # Import the new model

# Note: Since you opted out of forms.py, the ProcuredForm 
# you defined earlier would be irrelevant here. 
# We'll stick to the manual data handling for OilClass.

class OilClassManagementView(View):
    """Handles listing, creating, and simple enabling/disabling of Oil Classes."""
    
    def get(self, request, pk=None):
        sources = OilClass.objects.all().order_by('name')
        
        # We don't need to load instance data for the simplified view, 
        # but we keep the variables to handle potential POST failures cleanly.
        instance_data = None 
        action_url = reverse_lazy('oilclass_manage')
        
        if pk:
            instance = get_object_or_404(OilClass, pk=pk)
            instance_data = {'name': instance.name, 'is_active': instance.is_active}
            action_url = reverse_lazy('oilclass_manage_update', kwargs={'pk': pk})
        
        context = {
            'oil_classes': sources,
            'editing_data': instance_data,
            'action_url': action_url,
            'editing_pk': pk
        }
        return render(request, 'masters/oilclass_manage.html', context)

    def post(self, request, pk=None):
        # Manual Data Extraction and Validation
        name = request.POST.get('name', '').strip()
        is_active = request.POST.get('is_active') == 'on'
        
        errors = {}
        if not name:
            errors['name'] = "Oil Class name cannot be empty."
        
        if not errors:
            try:
                if pk:
                    # Update (Enable/Disable action)
                    source = get_object_or_404(OilClass, pk=pk)
                    source.name = name # Must update the name field from the hidden input
                    source.is_active = is_active
                    source.save()
                else:
                    # Create (Add action)
                    OilClass.objects.create(name=name, is_active=is_active)
                
                return redirect('oilclass_manage')
            except Exception as e:
                # Handle database errors, particularly IntegrityError for unique constraint
                errors['general'] = f"A database error occurred: {e}. Check if the name already exists."

        # If validation or database save fails, re-render with errors
        sources = OilClass.objects.all().order_by('name')
        context = {
            'oil_classes': sources,
            'editing_data': {'name': name, 'is_active': is_active},
            'action_url': reverse_lazy('oilclass_manage_update', kwargs={'pk': pk}) if pk else reverse_lazy('oilclass_manage'),
            'editing_pk': pk,
            'errors': errors
        }
        return render(request, 'masters/oilclass_manage.html', context)


class OilClassDeleteView(View):
    """Handles deletion of an Oil Class via POST request."""
    def post(self, request, pk):
        source = get_object_or_404(OilClass, pk=pk)
        source.delete()
        return redirect('oilclass_manage')
    

#Usage Master
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.views import View
# ... existing Procured and OilClass imports ...
from .models import UsageType # Import the new model

class UsageTypeManagementView(View):
    """Handles listing, creating, and simple enabling/disabling of Usage Types."""
    
    def get(self, request, pk=None):
        sources = UsageType.objects.all().order_by('name')
        
        instance_data = None 
        action_url = reverse_lazy('usagetype_manage')
        
        if pk:
            instance = get_object_or_404(UsageType, pk=pk)
            instance_data = {'name': instance.name, 'is_active': instance.is_active}
            action_url = reverse_lazy('usagetype_manage_update', kwargs={'pk': pk})
        
        context = {
            'usage_types': sources,
            'editing_data': instance_data,
            'action_url': action_url,
            'editing_pk': pk
        }
        return render(request, 'masters/usagetype_manage.html', context)

    def post(self, request, pk=None):
        # Manual Data Extraction and Validation
        name = request.POST.get('name', '').strip()
        is_active = request.POST.get('is_active') == 'on'
        
        errors = {}
        if not name:
            errors['name'] = "Usage Type name cannot be empty."
        
        if not errors:
            try:
                if pk:
                    # Update (Enable/Disable action)
                    source = get_object_or_404(UsageType, pk=pk)
                    source.name = name
                    source.is_active = is_active
                    source.save()
                else:
                    # Create (Add action)
                    UsageType.objects.create(name=name, is_active=is_active)
                
                return redirect('usagetype_manage')
            except Exception as e:
                errors['general'] = f"A database error occurred: {e}. Check if the name already exists."

        # If validation or database save fails, re-render with errors
        sources = UsageType.objects.all().order_by('name')
        context = {
            'usage_types': sources,
            'editing_data': {'name': name, 'is_active': is_active},
            'action_url': reverse_lazy('usagetype_manage_update', kwargs={'pk': pk}) if pk else reverse_lazy('usagetype_manage'),
            'editing_pk': pk,
            'errors': errors
        }
        return render(request, 'masters/usagetype_manage.html', context)


class UsageTypeDeleteView(View):
    """Handles deletion of a Usage Type via POST request."""
    def post(self, request, pk):
        source = get_object_or_404(UsageType, pk=pk)
        source.delete()
        return redirect('usagetype_manage')
    


#Prescription Time Master
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.views import View
# ... existing Procured, OilClass, and UsageType imports ...
from .models import PrescriptionTime # Import the new model

class PrescriptionTimeManagementView(View):
    """Handles listing, creating, and simple enabling/disabling of Prescription Time Slots."""
    
    def get(self, request, pk=None):
        sources = PrescriptionTime.objects.all().order_by('name')
        
        instance_data = None 
        action_url = reverse_lazy('prestime_manage')
        
        if pk:
            instance = get_object_or_404(PrescriptionTime, pk=pk)
            instance_data = {'name': instance.name, 'is_active': instance.is_active}
            action_url = reverse_lazy('prestime_manage_update', kwargs={'pk': pk})
        
        context = {
            'prescription_times': sources,
            'editing_data': instance_data,
            'action_url': action_url,
            'editing_pk': pk
        }
        return render(request, 'masters/prestime_manage.html', context)

    def post(self, request, pk=None):
        # Manual Data Extraction and Validation
        name = request.POST.get('name', '').strip()
        is_active = request.POST.get('is_active') == 'on'
        
        errors = {}
        if not name:
            errors['name'] = "Time Slot name cannot be empty."
        
        if not errors:
            try:
                if pk:
                    # Update (Enable/Disable action)
                    source = get_object_or_404(PrescriptionTime, pk=pk)
                    source.name = name
                    source.is_active = is_active
                    source.save()
                else:
                    # Create (Add action)
                    PrescriptionTime.objects.create(name=name, is_active=is_active)
                
                return redirect('prestime_manage')
            except Exception as e:
                errors['general'] = f"A database error occurred: {e}. Check if the name already exists."

        # If validation or database save fails, re-render with errors
        sources = PrescriptionTime.objects.all().order_by('name')
        context = {
            'prescription_times': sources,
            'editing_data': {'name': name, 'is_active': is_active},
            'action_url': reverse_lazy('prestime_manage_update', kwargs={'pk': pk}) if pk else reverse_lazy('prestime_manage'),
            'editing_pk': pk,
            'errors': errors
        }
        return render(request, 'masters/prestime_manage.html', context)


class PrescriptionTimeDeleteView(View):
    """Handles deletion of a Prescription Time Slot via POST request."""
    def post(self, request, pk):
        source = get_object_or_404(PrescriptionTime, pk=pk)
        source.delete()
        return redirect('prestime_manage')
    

#Ext/Int Master
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.views import View
from .models import PrescriptionScope # Import the new model

class PrescriptionScopeManagementView(View):
    """Handles listing, creating, and simple enabling/disabling of Prescription Scopes."""
    
    def get(self, request, pk=None):
        sources = PrescriptionScope.objects.all().order_by('name')
        
        instance_data = None 
        action_url = reverse_lazy('prescope_manage')
        
        if pk:
            instance = get_object_or_404(PrescriptionScope, pk=pk)
            instance_data = {'name': instance.name, 'is_active': instance.is_active}
            action_url = reverse_lazy('prescope_manage_update', kwargs={'pk': pk})
        
        context = {
            'prescription_scopes': sources,
            'editing_data': instance_data,
            'action_url': action_url,
            'editing_pk': pk
        }
        return render(request, 'masters/prescope_manage.html', context)

    def post(self, request, pk=None):
        # Manual Data Extraction and Validation
        name = request.POST.get('name', '').strip()
        is_active = request.POST.get('is_active') == 'on'
        
        errors = {}
        if not name:
            errors['name'] = "Prescription Scope name cannot be empty."
        
        if not errors:
            try:
                if pk:
                    # Update (Enable/Disable action)
                    source = get_object_or_404(PrescriptionScope, pk=pk)
                    source.name = name
                    source.is_active = is_active
                    source.save()
                else:
                    # Create (Add action)
                    PrescriptionScope.objects.create(name=name, is_active=is_active)
                
                return redirect('prescope_manage')
            except Exception as e:
                errors['general'] = f"A database error occurred: {e}. Check if the name already exists."

        # If validation or database save fails, re-render with errors
        sources = PrescriptionScope.objects.all().order_by('name')
        context = {
            'prescription_scopes': sources,
            'editing_data': {'name': name, 'is_active': is_active},
            'action_url': reverse_lazy('prescope_manage_update', kwargs={'pk': pk}) if pk else reverse_lazy('prescope_manage'),
            'editing_pk': pk,
            'errors': errors
        }
        return render(request, 'masters/prescope_manage.html', context)


class PrescriptionScopeDeleteView(View):
    """Handles deletion of a Prescription Scope via POST request."""
    def post(self, request, pk):
        source = get_object_or_404(PrescriptionScope, pk=pk)
        source.delete()
        return redirect('prescope_manage')
    

#Unit No 
# inventory/views.py

from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import (
    ListView, CreateView, UpdateView, DeleteView
)
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from .models import UnitNo

# --- Set the single template name ---
MASTER_TEMPLATE = 'masters/unitno_master.html'
SUCCESS_URL = reverse_lazy('unit_list')

# --- CRUD Operations using Class-Based Views (CBV) ---

class UnitNoListView(LoginRequiredMixin, ListView):
    """Lists all UnitNo objects."""
    model = UnitNo
    context_object_name = 'units'
    template_name = MASTER_TEMPLATE # <--- Use the single template

class UnitNoCreateView(LoginRequiredMixin, CreateView):
    """Handles adding a new UnitNo."""
    model = UnitNo
    fields = ['unit_name', 'is_active']
    template_name = MASTER_TEMPLATE # <--- Use the single template
    success_url = SUCCESS_URL

    def get_context_data(self, **kwargs):
        # Indicate to the template that we are in 'create' mode
        context = super().get_context_data(**kwargs)
        context['mode'] = 'create'
        return context

class UnitNoUpdateView(LoginRequiredMixin, UpdateView):
    """Handles updating an existing UnitNo."""
    model = UnitNo
    fields = ['unit_name', 'is_active']
    template_name = MASTER_TEMPLATE # <--- Use the single template
    success_url = SUCCESS_URL

    def get_context_data(self, **kwargs):
        # Indicate to the template that we are in 'update' mode
        context = super().get_context_data(**kwargs)
        context['mode'] = 'update'
        return context

class UnitNoDeleteView(LoginRequiredMixin, DeleteView):
    """Handles deleting an existing UnitNo. (This must remain separate for security)"""
    model = UnitNo
    context_object_name = 'unit'
    template_name = 'inventory/unitno_confirm_delete.html' # <--- Separate delete confirmation is crucial
    success_url = SUCCESS_URL


# --- Enable/Disable Actions (Remain the same) ---

@login_required
def unit_no_enable(request, pk):
    unit = get_object_or_404(UnitNo, pk=pk)
    unit.is_active = True
    unit.save()
    return redirect(SUCCESS_URL)

@login_required
def unit_no_disable(request, pk):
    unit = get_object_or_404(UnitNo, pk=pk)
    unit.is_active = False
    unit.save()
    return redirect(SUCCESS_URL)