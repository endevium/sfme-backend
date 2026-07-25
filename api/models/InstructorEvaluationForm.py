from django.db import models
from .Classroom import Classroom

class InstructorEvaluationForm(models.Model):
    instructor_name = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=[('Active', 'Active'), ('Draft', 'Draft')], default='Draft')
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    classroom = models.ForeignKey(
        Classroom,
        on_delete=models.CASCADE,
        related_name="instructor_evaluation_forms",
        null=True,        
        blank=True,
    )

    class Meta:
        db_table = "instructor_evaluation_forms"
        managed = True

    def clean(self):
        if self.classroom:
            name = f"{self.classroom.faculty.firstname} {self.classroom.faculty.lastname}"
            if self.instructor_name != name:
                self.instructor_name = name

    def save(self, *args, **kwargs):
        if self.classroom:
            self.instructor_name = f"{self.classroom.faculty.firstname} {self.classroom.faculty.lastname}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.instructor_name} ({self.classroom.classroom_code})"