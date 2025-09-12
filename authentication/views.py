from django.shortcuts import render

# Create your views here.

from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login
from django.contrib import messages

from django.shortcuts import redirect, render
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages


from django.contrib.auth import logout

def logout_view(request):
    logout(request)  # clears the session
    return redirect('login')  # redirect to login page (or home page)






def login_view(request):
    # Prevent logged-in users from going back to login page
    # if request.user.is_authenticated:
    #     return redirect_user_dashboard(request.user)

    if request.method == "POST":
        username = request.POST.get("username")   # stored as username
        password = request.POST.get("password")

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            return redirect_user_dashboard(user)  # 🔑 role based redirect
        else:
            messages.error(request, "Invalid username or password")
            return redirect("login")

    return render(request, "login.html")


def redirect_user_dashboard(user):
    """
    Redirect users to their dashboard depending on their role
    """
    if user.role == "therapist":
        return redirect("therapistdash")
    elif user.role == "therapist_admin":
        return redirect("therapistadmindash")
    elif user.role == "doctor_admin":
        return redirect("doctordash")
     
    elif user.role == "gm_hr":
        return redirect("gmdash")
    elif user.role == "super_admin":
        return redirect("superadmindash")
    elif user.role == "Patient":
        return redirect("patientdash")
     
    elif user.role == "Tenants":
        return redirect("Tenantsdash")
    elif user.role == "Doctor Helpdesk":
        return redirect("Helpdeskadmindash")
    else:
        # default dashboard if role not set
         return redirect("admindash")




from django.shortcuts import render
from django.contrib.auth.decorators import login_required


@login_required
def therapist_dashboard(request):
    return render(request, "dashboards/therapist/therapist_dashboard.html")

@login_required
def view_patient_details(request):
    return render(request, "dashboards/therapist/view_patient_details.html")


@login_required
def therapist_feedback_form(request):
    return render(request, "dashboards/therapist/therapist_feedback_form.html")




@login_required
def scheduling_dashboard(request):
    return render(request, "dashboards/sheduling_team/scheduling_dashboard.html")


@login_required
def doctor_dashboard(request):
    return render(request, "dashboards/doctorsAndHelpDesk/doctor_dashboard.html")


@login_required
def gm_hr_dashboard(request):
    return render(request, "dashboards/gm_hr/gm_hr_dashboard.html")

@login_required
def Patient_feedback_review(request):
    return render(request, "dashboards/gm_hr/Patient_feedback_review.html")

@login_required
def nurse_dash(request):
    return render(request, "dashboards/Nurse/nurse_dash.html")


@login_required
def ip_pharmacy(request):
    return render(request, "dashboards/ip_pharmacy/ip_pharmacy.html")

@login_required
def prescription_dash(request):
    return render(request, "dashboards/ip_pharmacy/prescription_dash.html")

@login_required
def superadmin_dashboard(request):
    return render(request, "dashboards/superadmin/superadmin_dashboard.html")


@login_required
def Patient_dashboard(request):
    return render(request, "dashboards/patient/Patient_dashboard.html")


@login_required
def patient_profile(request):
    return render(request, "dashboards/patient/patient_profile.html")

@login_required
def Tenants_dashboard(request):
    return render(request, "dashboards/Tenants/Tenants_dashboard.html")

@login_required
def Helpdeskadmindash(request):
    return render(request, "dashboards/doctorsAndHelpDesk/Helpdeskadmindash.html")




@login_required
def medicin_prescription(request):
    return render(request, "dashboards/doctorsAndHelpDesk/medicin_prescription.html")

@login_required
def medicin_prescription_table(request):
    return render(request, "dashboards/doctorsAndHelpDesk/medicin_prescription_table.html")




@login_required
def Manage_user(request):
    return render(request, "dashboards/superadmin/Manage_user.html")

@login_required
def Audit_Log(request):
    return render(request, "dashboards/superadmin/Audit_Log.html")

@login_required
def Therapy_Report(request):
    return render(request, "dashboards/finance/report.html")

@login_required
def housekeepingdash(request):
    return render(request, "dashboards/Housekeeping Staff/housekeepingdash.html")