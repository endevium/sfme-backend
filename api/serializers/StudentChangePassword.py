from rest_framework import serializers
from ..models.Student import Student
from ..password_rules import validate_strong_password
import re
import logging

logger = logging.getLogger(__name__)

class StudentChangePasswordSerializer(serializers.Serializer):
    student_number = serializers.CharField()
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        student_number = attrs.get('student_number')
        old_password = attrs.get('old_password')
        new_password = attrs.get('new_password')

        if not student_number:
            raise serializers.ValidationError("Invalid credentials")

        candidate = str(student_number).strip()
        student = None

        # Try exact match first
        try:
            student = Student.objects.get(student_number=candidate)
        except Student.DoesNotExist:
            student = None

        # Try case-insensitive match
        if not student:
            student = Student.objects.filter(student_number__iexact=candidate).first()

        # Try stripping non-digits (handles inputs like 00-0000-000)
        if not student:
            digits = re.sub(r"\D", "", candidate)
            if digits:
                student = Student.objects.filter(student_number=digits).first()

        if not student:
            logger.warning("StudentChangePassword: student not found for input '%s'", candidate)
            raise serializers.ValidationError("Student not found or invalid identifier")

        if not student.check_password(old_password):
            logger.warning("StudentChangePassword: incorrect old password for student %s (id=%s)", getattr(student, 'student_number', None), getattr(student, 'id', None))
            raise serializers.ValidationError("Old password is incorrect")

        validate_strong_password(new_password, user=student)

        if old_password == new_password:
            raise serializers.ValidationError("New password must be different from the old password.")

        attrs['user'] = student
        return attrs
