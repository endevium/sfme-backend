from django.db import models

class ModuleEvaluationForm(models.Model):
    subject_code = models.CharField(max_length=200)
    subject_description = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=[('Active', 'Active'), ('Draft', 'Draft')], default='Draft')
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "module_evaluation_forms"
        managed = False

    def __str__(self):
        return self.subject_code
