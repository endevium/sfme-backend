from django.db import models
from django.conf import settings
from django.contrib.auth.models import BaseUserManager
from django.contrib.auth.hashers import make_password, check_password
from django.utils import timezone

class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(email, password, **extra_fields)

class PersonBase(models.Model):
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=128)

    firstname = models.CharField(max_length=100)
    middlename = models.CharField(max_length=100, blank=True, null=True)
    lastname = models.CharField(max_length=100)
    contact_number = models.CharField(max_length=15, blank=True, null=True)
    profile_picture = models.TextField(blank=True, null=True)
    birthdate = models.DateField(blank=True, null=True)
    password_changed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        abstract = True

    def _pepper(self, raw_password: str) -> str:
        pepper = getattr(settings, "PASSWORD_PEPPER", "") or ""
        return f"{raw_password}{pepper}"

    def set_password(self, raw_password: str) -> None:
        self.password = make_password(self._pepper(raw_password))
        self.password_changed_at = timezone.now()

    def check_password(self, raw_password: str) -> bool:
        return check_password(self._pepper(raw_password), self.password)

    def __str__(self):
        return f"{self.firstname} {self.lastname}"
