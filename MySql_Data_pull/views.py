from django.shortcuts import render
from django.apps import apps

# All available table names and their corresponding models
TABLE_MODELS = {
    "TherapyDetails": "MySql_Data_pull.TherapyDetails",
    "TherapistDeployment": "MySql_Data_pull.TherapistDeployment",
    "Prescription": "MySql_Data_pull.Prescription",
    "Registration": "MySql_Data_pull.Registration",
    "RoomMaster": "MySql_Data_pull.RoomMaster",
    "TherapistDetails": "MySql_Data_pull.TherapistDetails",
    "TherapistMaster": "MySql_Data_pull.TherapistMaster",
    "TRMaster": "MySql_Data_pull.TRMaster",
}

def table_view(request):
    selected_table = request.GET.get("table_name")  # from dropdown
    data = []
    columns = []

    if selected_table in TABLE_MODELS:
        # Dynamically get the model
        app_label, model_name = TABLE_MODELS[selected_table].split(".")
        model = apps.get_model(app_label, model_name)

        # Fetch top 10 rows
        data = model.objects.using('therapy_db').all()[:10]
        if data:
            # Extract column names dynamically from model _meta
            columns = [field.name for field in model._meta.fields]

    context = {
        "tables": TABLE_MODELS.keys(),
        "selected_table": selected_table,
        "data": data,
        "columns": columns,
    }
    return render(request, "sql_data_test.html", context)
