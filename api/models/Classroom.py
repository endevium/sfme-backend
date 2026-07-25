from django.core.exceptions import ValidationError
from django.db import models
from .Faculty import Faculty
from .Module import Module
from .Block import Block

class Classroom(models.Model):
    id = models.BigAutoField(primary_key=True)
    faculty = models.ForeignKey(
        Faculty,
        related_name="classrooms",
        on_delete=models.CASCADE
    )
    block = models.CharField(max_length=50)
    subject_code = models.CharField(max_length=20)
    module_name = models.CharField(max_length=150)
    program = models.CharField(max_length=50)
    year_level = models.PositiveSmallIntegerField(
        choices=[(1, "1st Year"),
                 (2, "2nd Year"),
                 (3, "3rd Year"),
                 (4, "4th Year"),
                 (5, "5th Year")],
        default=1
    )
    semester = models.CharField(max_length=10)
    classroom_code = models.CharField(max_length=12, unique=True, editable=False)
    schedule = models.CharField(max_length=100, blank=True, null=True)
    room = models.CharField(max_length=50, blank=True, null=True)

    class Meta:
        db_table = "classrooms"

    def clean(self):
        if not Module.objects.filter(
            subject_code=self.subject_code,
            department=self.faculty.department
        ).exists():
            raise ValidationError(
                "Subject code does not exist or is not in your department."
            )

        if not self.block:
            raise ValidationError("Block/section is required.")

        if not Block.objects.filter(
                 block_name=self.block,
                 department=self.faculty.department
         ).exists():
             raise ValidationError("Block/section invalid or not in your department.")

    def save(self, *args, **kwargs):
        if not self.classroom_code:
            # generate an 8‑character code on first save
            import uuid
            self.classroom_code = uuid.uuid4().hex[:8].upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.subject_code} – {self.classroom_code}"