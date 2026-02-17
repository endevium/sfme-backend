from rest_framework import serializers
from ..models.Student import Student
from ..password_rules import validate_strong_password

class StudentChangePasswordSerializer(serializers.Serializer):
    student_number = serializers.CharField()
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        student_number = attrs.get('student_number')
        old_password = attrs.get('old_password')
        new_password = attrs.get('new_password')

        try:
            student = Student.objects.get(student_number=student_number)
        except Student.DoesNotExist:
            raise serializers.ValidationError("Invalid credentials")

        if not student.check_password(old_password):
            raise serializers.ValidationError("Invalid credentials")

        validate_strong_password(new_password, user=student)

        if old_password == new_password:
            raise serializers.ValidationError("New password must be different from the old password.")

        attrs['user'] = student
        return attrs
