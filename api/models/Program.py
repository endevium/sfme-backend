from django.db import models
from .DepartmentHead import DepartmentHead

class Program(models.Model):
    id = models.BigAutoField(primary_key=True)
    department_head = models.ForeignKey(
        DepartmentHead, null=True, blank=True, on_delete=models.SET_NULL, related_name="programs"
    )
    program_name = models.CharField(max_length=50)
    program_code = models.CharField(max_length=10, unique=True)
    department = models.CharField(max_length=50)
    
    class Meta:
        db_table = 'programs'
        managed = False
    
    def __str__(self):
        return f"{self.course_code} - {self.course_name}"