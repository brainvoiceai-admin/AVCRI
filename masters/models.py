from django.db import models
#Procured master
class Procured(models.Model):
    """Master list of procurement sources (e.g., IP Pharmacy, Kashaya Room)."""
    
    name = models.CharField(max_length=100, unique=True, verbose_name="Source Name")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated")

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Procurement Source"
        verbose_name_plural = "Procurement Sources"
        ordering = ["name"]





#oil class master
class OilClass(models.Model):
    """Master list of oil categories/classes. Examples: Sesame Oil (Tila Taila), Coconut Oil (Narikela Taila)."""
    name = models.CharField(max_length=100, unique=True, verbose_name="Oil Class Name")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Oil Class"
        verbose_name_plural = "Oil Classes"
        ordering = ["name"]

#usage master
class UsageType(models.Model):
    """Master list of usage types for inventory and resources. Examples: Internal (IP Use), Dispensed (OP Use), Wastage/Damage."""
    name = models.CharField(max_length=100, unique=True, verbose_name="Usage Type Name")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Usage Type"
        verbose_name_plural = "Usage Types"
        ordering = ["name"]


#Prescription time master
class PrescriptionTime(models.Model):
    """Master list of standardized time slots for prescriptions or dosing schedules. Examples: 8 AM, 12 PM, 4 PM."""
    name = models.CharField(max_length=20, unique=True, verbose_name="Time Slot")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Prescription Time Slot"
        verbose_name_plural = "Prescription Time Slots"
        ordering = ["name"]


#Ext/Int Master
class PrescriptionScope(models.Model):
    """Master list for classifying prescription scope (e.g., External/Internal). Clarifies whether a prescription is for an existing IP patient or OP/external use."""
    name = models.CharField(max_length=50, unique=True, verbose_name="Scope Name (Ext/Int)")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Prescription Scope"
        verbose_name_plural = "Prescription Scopes"
        ordering = ["name"]

class UnitNo(models.Model):
    """
    Master model for storing unit names (e.g., ml, cm) and their status.
    """
    unit_name = models.CharField(max_length=50,unique=True,verbose_name="Unit Name",help_text="e.g., ml, cm, kg")
    is_active = models.BooleanField(default=True,verbose_name="Is Active",help_text="Designates whether the unit can be used.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Unit Number"
        verbose_name_plural = "Unit Numbers"
        ordering = ['unit_name']

    def __str__(self):
        return self.unit_name