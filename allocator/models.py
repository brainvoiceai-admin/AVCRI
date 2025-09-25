from django.db import models


class AllocationRun(models.Model):
    run_date = models.DateField()
    status = models.CharField(max_length=20, default="draft")
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Run {self.id} on {self.run_date}"


class Assignment(models.Model):
    allocation = models.ForeignKey(AllocationRun, related_name="assignments", on_delete=models.CASCADE)

    pat_reg_no = models.CharField(max_length=50, blank=True, null=True)
    therapy_code = models.CharField(max_length=50, blank=True, null=True)
    therapist_code = models.CharField(max_length=400, blank=True, null=True)  # comma-separated
    cleaner_code = models.CharField(max_length=100, blank=True, null=True)

    slot_no = models.CharField(max_length=50, blank=True, null=True)   # string because some DBs use text keys
    slot_label = models.CharField(max_length=100, blank=True, null=True)
    room_code = models.CharField(max_length=100, blank=True, null=True)

    reason = models.TextField(blank=True, null=True)
    difficulty = models.CharField(max_length=10, blank=True, null=True)  # Easy / Medium / Hard

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"A:{self.id} p:{self.pat_reg_no} thr:{self.therapist_code} room:{self.room_code}"
