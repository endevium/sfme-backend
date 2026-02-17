from django.db import models
from .base import PersonBase

class Student(PersonBase):
    student_number = models.CharField(max_length=20, unique=True, blank=True, null=True)
    department = models.CharField(max_length=100, blank=True, null=True)
    program = models.CharField(max_length=100, blank=True, null=True)
    year_level = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        choices=[(1, "1st Year"), (2, "2nd Year"), (3, "3rd Year"), (4, "4th Year"), (5, "5th Year")],
    )
    # Store multiple enrolled subjects as JSON (list of strings)
    enrolled_subjects = models.JSONField(default=list, blank=True, null=True)
    # Block / section identifier
    block_section = models.CharField(max_length=50, blank=True, null=True)
    must_change_password = models.BooleanField(default=True, db_column="must_change_password")

    class Meta:
        db_table = "students"
        managed = False

    def __str__(self):
        return f"{self.firstname} {self.lastname} ({self.student_number})"