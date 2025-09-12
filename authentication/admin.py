from django.contrib import admin

# Register your models here.
# app/admin.py
from django.contrib import admin
from .models import CustomUser
from django.contrib.auth.admin import UserAdmin

class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('Role Info', {'fields': ('role',)}),
    )

admin.site.register(CustomUser, CustomUserAdmin)
