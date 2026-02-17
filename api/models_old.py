from django.db import models
from django.contrib.auth.models import BaseUserManager
from django.contrib.auth.hashers import make_password, check_password

# User manager
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

    class Meta:
        abstract = True

    def set_password(self, raw_password: str) -> None:
        self.password = make_password(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password(raw_password, self.password)

    def __str__(self):
        return f"{self.firstname} {self.lastname}"

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


class Faculty(PersonBase):
    department = models.CharField(max_length=100, blank=True, null=True)
    status = models.BooleanField(default=True)
    must_change_password = models.BooleanField(default=True, db_column="must_change_password")

    class Meta:
        db_table = "faculty"
        managed = False

class DepartmentHead(PersonBase):
    department = models.CharField(max_length=100, blank=True, null=True)
    status = models.BooleanField(default=True)

    class Meta:
        db_table = "department_heads"
        managed = False

    def __str__(self):
        return f"{self.firstname} {self.lastname} - {self.department}"

class EvaluationForm(models.Model):
    title = models.CharField(max_length=200)
    form_type = models.CharField(max_length=50, choices=[('Module', 'Module'), ('Instructor', 'Instructor')])
    description = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=[('Active', 'Active'), ('Draft', 'Draft')], default='Draft')
    questions = models.JSONField(default=list)  # List of question objects
    # Counters for quick display (kept in sync by application logic)
    questions_count = models.PositiveIntegerField(default=0)
    usage_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "evaluation_forms"
        managed = False

    def __str__(self):
        return self.title


class ModuleEvaluationForm(models.Model):
    subject_code = models.CharField(max_length=200)
    subject_description = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=[('Active', 'Active'), ('Draft', 'Draft')], default='Draft')
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "module_evaluation_forms"
        managed = True

    def __str__(self):
        return self.subject_code


class InstructorEvaluationForm(models.Model):
    instructor_name = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=[('Active', 'Active'), ('Draft', 'Draft')], default='Draft')
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "instructor_evaluation_forms"
        managed = True

    def __str__(self):
        return self.instructor_name

class AuditLog(models.Model):
    user = models.CharField(max_length=100)  # User who performed the action
    role = models.CharField(max_length=50)  # Role like 'Depthead', 'Faculty', etc.
    action = models.CharField(max_length=200)  # Action performed
    category = models.CharField(max_length=50)  # Category like 'USER MANAGEMENT', 'FORM MANAGEMENT'
    status = models.CharField(max_length=20, default='Success')  # Status like 'Success', 'Failed'
    message = models.TextField()  # Detailed message
    ip = models.CharField(max_length=45, blank=True, null=True)  # IP address
    timestamp = models.DateTimeField(auto_now_add=True)  # When it happened

    class Meta:
        db_table = "audit_logs"
        managed = True
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.user} - {self.action} - {self.timestamp}"