from django.db import models
from .Student import Student
from .Classroom import Classroom

class ClassroomEnrollment(models.Model):
    id = models.BigAutoField(primary_key=True)
    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name="enrollments"
    )
    classroom = models.ForeignKey(
        Classroom,
        on_delete=models.CASCADE,
        related_name="enrollments"
    )
    approved = models.BooleanField(default=False)
    requested_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "enrollments"
        unique_together = ("student", "classroom")

    def __str__(self):
        status = "approved" if self.approved else "pending"
        return f"{self.student} → {self.classroom} ({status})"