from django.http import HttpResponse
from django.shortcuts import render
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login as auth_login
from django.contrib import messages
from django.contrib.auth.models import User
def home(request):
    return render(request,'home.html')




from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login
from django.contrib import messages




def admindash(request):
    return render(request,'knitting.html')




# views.py
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from .models import Therapy

def assign_page(request):
    therapies = Therapy.objects.all()
    return render(request, 'assign_manual.html', {'therapies': therapies})

def get_therapy_details(request, therapy_id):
    therapy = get_object_or_404(Therapy, id=therapy_id)
    return JsonResponse({
        'code': therapy.code,
        'group': therapy.group,
        'category': therapy.category,
        'duration': str(therapy.duration),
        'bathing_required': therapy.bathing_required,
        'treatment_room_required': therapy.treatment_room_required,
        'cost': float(therapy.cost),
        'super_senior_needed': therapy.super_senior_needed,
        'senior_needed': therapy.senior_needed,
        'junior_needed': therapy.junior_needed,
        'trainee_needed': therapy.trainee_needed,
        'total_therapist_needed': therapy.total_therapist_needed,
    })
