from django.db import models
from django.utils import timezone

class EmailOTP(models.Model):
    class Purpose(models.TextChoices):
        LOGIN = "login", "Login"
        RESET_PASSWORD = "reset_password", "Reset Password"

    class Role(models.TextChoices):
        STUDENT = "student", "Student"
        FACULTY = "faculty", "Faculty"
        DEPARTMENT_HEAD = "department_head", "Department Head"

    email = models.EmailField(db_index=True)
    otp = models.CharField(max_length=6)

    purpose = models.CharField(
        max_length=32,
        choices=Purpose.choices,
        default=Purpose.LOGIN,
        db_index=True,
    )

    role = models.CharField(
        max_length=32,
        choices=Role.choices,
        default=Role.STUDENT,
        db_index=True,
    )

    pending_token = models.CharField(max_length=64, unique=True, db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)

    is_used = models.BooleanField(default=False, db_index=True)

    class Meta:
        db_table = "email_otps"
        managed = True

    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at