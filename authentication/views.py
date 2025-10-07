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
        return redirect("patient:patient_lookup")
     
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
         return redirect("patient:patient_lookup")




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


from django.utils import timezone
from datetime import timedelta
from django.contrib.auth.decorators import login_required
from MySql_Data_pull.models import Registration
from Patient.models import Repeated_Visitors

@login_required
def doctor_dashboard(request):
    patient = None
    error = None
    vip_status ="No"  # default

    one_week_ago = timezone.now() - timedelta(days=20)

    # All patients from last 7 days
    all_patients = Registration.objects.using('therapy_db') \
        .filter(pat_visit_date__gte=one_week_ago) \
        .order_by('-pat_visit_date')

    # Handle GET request (from dropdown onchange)
    reg_no = request.GET.get('pat_reg_no')
    if reg_no:
        patient = Registration.objects.using('therapy_db') \
            .filter(pat_reg_no=reg_no, pat_visit_date__gte=one_week_ago) \
            .first()

        if not patient:
            error = "Patient not found in last week's visits."
        else:
            # Fetch VIP status from Repeated_Visitors
            rv = Repeated_Visitors.objects.filter(register_number=reg_no).first()
            if rv:
                vip_status = "Yes" if rv.is_vip else "No"

    return render(request, "dashboards/doctorsAndHelpDesk/doctor_dashboard.html", {
        'patient': patient,
        'vip_status': vip_status,
        'error': error,
        'all_patients': all_patients
    })





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



from MySql_Data_pull.models import ItemMaster
@login_required
def medicin_prescription(request):

    items = ItemMaster.objects.using('therapy_db').all().order_by('item_name')
    rows = []

    if request.method == "POST":
        # Read how many rows were submitted
        row_count = int(request.POST.get("row_count", 1))
        for i in range(row_count):
            item_code = request.POST.get(f"item_code_{i}", "")
            dosage = request.POST.get(f"dosage_{i}", "")
            usage = request.POST.get(f"usage_{i}", "")
            internal_external = request.POST.get(f"internal_external_{i}", "")
            time = request.POST.get(f"time_{i}", "")
            procured_from = ""

            # Autofill Procured From from item_master
            if item_code:
                try:
                    item = ItemMaster.objects.using('therapy_db').get(item_code=item_code)
                    procured_from = item.item_procurred_from
                    item_name = item.item_name
                except ItemMaster.DoesNotExist:
                    item_name = ""
            else:
                item_name = ""

            rows.append({
                "item_code": item_code,
                "item_name": item_name,
                "dosage": dosage,
                "usage": usage,
                "internal_external": internal_external,
                "procured_from": procured_from,
                "time": time,
            })

    # If no POST, initialize one empty row
    if not rows:
        rows.append({
            "item_code": "",
            "item_name": "",
            "dosage": "",
            "usage": "",
            "internal_external": "",
            "procured_from": "",
            "time": "",
        })

    return render(request,"dashboards/doctorsAndHelpDesk/medicin_prescription.html", {
        "items": items,
        "rows": rows,
    })


   

  
   

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