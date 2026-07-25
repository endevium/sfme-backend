from django.db import models
from .Classroom import Classroom

class ModuleEvaluationForm(models.Model):
    subject_code = models.CharField(max_length=200)
    subject_description = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=[('Active', 'Active'), ('Draft', 'Draft')], default='Draft')
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    classroom = models.ForeignKey(
        Classroom,
        on_delete=models.CASCADE,
        related_name="module_evaluation_forms",
        null=True,        
        blank=True,
    )
    
    class Meta:
        db_table = "module_evaluation_forms"
        managed = True

    def clean(self):
        if self.classroom and self.subject_code != self.classroom.subject_code:
            self.subject_code = self.classroom.subject_code

    def save(self, *args, **kwargs):
        if self.classroom:
            self.subject_code = self.classroom.subject_code
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.subject_code} ({self.classroom.classroom_code})"
