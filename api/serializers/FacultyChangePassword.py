from rest_framework import serializers
from ..models.Faculty import Faculty
from ..password_rules import validate_strong_password

class FacultyChangePasswordSerializer(serializers.Serializer):
    email = serializers.CharField()
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email = attrs.get('email')
        old_password = attrs.get('old_password')
        new_password = attrs.get('new_password')

        try:
            faculty = Faculty.objects.get(email=email)
        except Faculty.DoesNotExist:
            raise serializers.ValidationError("Invalid credentials")

        if not faculty.check_password(old_password):
            raise serializers.ValidationError("Invalid credentials")

        validate_strong_password(new_password, user=faculty)

        if old_password == new_password:
            raise serializers.ValidationError("New password must be different from the old password.")
        
        attrs['user'] = faculty
        return attrs
