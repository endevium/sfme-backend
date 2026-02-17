from rest_framework import serializers
from ..models.Student import Student

class StudentLoginSerializer(serializers.Serializer):
    student_number = serializers.CharField()  
    password = serializers.CharField(write_only=True)
    role = serializers.CharField(required=False)

    def validate(self, attrs):
        student_number = attrs.get('student_number')
        password = attrs.get('password')

        user = None

        try:
            student = Student.objects.get(student_number=student_number)
            if student.check_password(password):
                user = student
        except Student.DoesNotExist:
            pass

        if not user:
            raise serializers.ValidationError("Invalid credentials")

        attrs['user'] = user
        return attrs
