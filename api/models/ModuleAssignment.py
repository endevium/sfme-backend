from django.db import models
from .Module import Module
from .Faculty import Faculty

class ModuleAssignment(models.Model):
    id = models.BigAutoField(primary_key=True)
    module = models.ForeignKey(Module, on_delete=models.CASCADE, db_column='module_id')
    faculty = models.ForeignKey(Faculty, on_delete=models.CASCADE, db_column='faculty_id')

    class Meta:
        db_table = 'module_assignments'
        unique_together = (('module', 'faculty'),)
        managed = False

    def __str__(self):
        return f"{self.module} -> {self.faculty}"
