from rest_framework import serializers
from api.models import Module
from api.models.ClassroomEnrollment import ClassroomEnrollment

class ModuleSerializer(serializers.ModelSerializer):
    student_count = serializers.SerializerMethodField()

    class Meta:
        model = Module
        fields = [
            "id",
            "subject_code",
            "module_name",
            "year_level",
            "department",
            "semester",
            "academic_year",
            "department_head",
            "student_count",
        ]
        read_only_fields = ["id", "department"]

    def get_student_count(self, obj):
        return ClassroomEnrollment.objects.filter(
            classroom__subject_code=obj.subject_code,
            approved=True,
        ).values("student").distinct().count()