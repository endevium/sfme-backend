from django.core.exceptions import ValidationError
from django.db import models

class Module(models.Model):
    id = models.BigAutoField(primary_key=True)
    department_head = models.ForeignKey(
        "DepartmentHead",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="modules",
    )
    subject_code = models.CharField(max_length=20, unique=True)
    module_name = models.CharField(max_length=150)
    year_level = models.CharField(max_length=20, blank=True, null=True)
    department = models.CharField(max_length=50)
    semester = models.CharField(max_length=20)
    academic_year = models.CharField(max_length=20)

    class Meta:
        db_table = 'modules'
    
    def __str__(self):
        return f"{self.subject_code} – {self.module_name}"

    def clean(self):
        if self.department_head and self.department != self.department_head.department:
            raise ValidationError(
                "Module department must match department head's department."
            )

    def save(self, *args, **kwargs):
        if self.department_head:
            self.department = self.department_head.department
        super().save(*args, **kwargs)