from django.db import models

class InstructorEvaluationForm(models.Model):
    instructor_name = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=[('Active', 'Active'), ('Draft', 'Draft')], default='Draft')
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "instructor_evaluation_forms"
        managed = False

    def __str__(self):
        return self.instructor_name