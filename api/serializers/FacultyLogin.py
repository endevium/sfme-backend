from rest_framework import serializers
from ..models.Faculty import Faculty

class FacultyLoginSerializer(serializers.Serializer):
    email = serializers.CharField()  
    password = serializers.CharField(write_only=True)
    role = serializers.CharField(required=False)

    def validate(self, attrs):
        email = attrs.get('email')
        password = attrs.get('password')

        user = None

        try:
            faculty = Faculty.objects.get(email=email)
            if faculty.check_password(password):
                user = faculty
        except Faculty.DoesNotExist:
            pass

        if not user:
            raise serializers.ValidationError("Invalid credentials")

        attrs['user'] = user
        return attrs
