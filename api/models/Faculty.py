from django.db import models
from .base import PersonBase

class Faculty(PersonBase):
    STATUS_ACTIVE = "active"
    STATUS_ARCHIVED = "archived"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_ARCHIVED, "Archived"),
    ]

    department = models.CharField(max_length=100, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    must_change_password = models.BooleanField(default=True, db_column="must_change_password")

    class Meta:
        db_table = "faculty"
        managed = False