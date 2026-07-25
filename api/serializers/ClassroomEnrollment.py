from rest_framework import serializers
from api.models import ClassroomEnrollment

class ClassroomEnrollmentSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    student_number = serializers.SerializerMethodField()
    student_email = serializers.SerializerMethodField()
    subject_code = serializers.SerializerMethodField()
    subject_name = serializers.SerializerMethodField()
    classroom_code = serializers.SerializerMethodField()

    def get_student_name(self, obj):
        if not obj.student:
            return ""
        return f"{obj.student.firstname} {obj.student.lastname}".strip()

    def get_student_number(self, obj):
        return getattr(obj.student, "student_number", "") or ""

    def get_student_email(self, obj):
        return getattr(obj.student, "email", "") or ""

    def get_subject_code(self, obj):
        return getattr(obj.classroom, "subject_code", "") or ""

    def get_subject_name(self, obj):
        return getattr(obj.classroom, "module_name", "") or ""

    def get_classroom_code(self, obj):
        return getattr(obj.classroom, "classroom_code", "") or ""

    class Meta:
        model = ClassroomEnrollment
        fields = [
            "id",
            "student",
            "classroom",
            "approved",
            "requested_at",
            "approved_at",
            "student_name",
            "student_number",
            "student_email",
            "subject_code",
            "subject_name",
            "classroom_code",
        ]
        read_only_fields = ["id", "approved", "requested_at", "approved_at"]