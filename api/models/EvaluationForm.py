from django.db import models

class EvaluationForm(models.Model):
    title = models.CharField(max_length=200)
    form_type = models.CharField(max_length=50, choices=[('Module', 'Module'), ('Instructor', 'Instructor')])
    description = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=[('Active', 'Active'), ('Draft', 'Draft')], default='Draft')
    questions = models.JSONField(default=list)  # List of question objects
    # Counters for quick display (kept in sync by application logic)
    questions_count = models.PositiveIntegerField(default=0)
    usage_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "evaluation_forms"
        managed = False

    def __str__(self):
        return self.title
