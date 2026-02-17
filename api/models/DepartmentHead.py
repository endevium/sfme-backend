from django.db import models
from .base import PersonBase

class DepartmentHead(PersonBase):
    department = models.CharField(max_length=100, blank=True, null=True)
    status = models.BooleanField(default=True)

    class Meta:
        db_table = "department_heads"
        managed = False

    def __str__(self):
        return f"{self.firstname} {self.lastname} - {self.department}"