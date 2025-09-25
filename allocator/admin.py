from django.contrib import admin
from .models import AllocationRun, Assignment

class AssignmentInline(admin.TabularInline):
    model = Assignment
    readonly_fields = ("pat_reg_no", "therapy_code", "therapist_code", "cleaner_code", "slot_label", "room_code", "difficulty", "reason", "created_at")
    extra = 0

@admin.register(AllocationRun)
class AllocationRunAdmin(admin.ModelAdmin):
    list_display = ("id", "run_date", "status", "created_at")
    inlines = [AssignmentInline]

@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ("pat_reg_no", "therapy_code", "therapist_code", "cleaner_code", "slot_label", "room_code", "difficulty", "created_at")
    list_filter = ("difficulty", "room_code")
    search_fields = ("pat_reg_no", "therapist_code", "therapy_code")
