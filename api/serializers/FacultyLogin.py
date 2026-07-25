from rest_framework import serializers
from ..models.Faculty import Faculty
from ..utils import is_password_expired

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

        if getattr(user, 'status', Faculty.STATUS_ACTIVE) == Faculty.STATUS_ARCHIVED:
            raise serializers.ValidationError("This faculty account is archived")
        
        if user and is_password_expired(user):
            user.must_change_password = True
            user.save(update_fields=["must_change_password"])

        attrs['user'] = user
        return attrs
