from rest_framework import serializers
from ..models.DepartmentHead import DepartmentHead

class DepartmentHeadLoginSerializer(serializers.Serializer):
    email = serializers.CharField()  
    password = serializers.CharField(write_only=True)
    role = serializers.CharField(required=False)

    def validate(self, attrs):
        email = attrs.get('email')
        password = attrs.get('password')

        user = None

        try:
            head = DepartmentHead.objects.get(email=email)
            if head.check_password(password):
                user = head
        except DepartmentHead.DoesNotExist:
            pass

        if not user:
            raise serializers.ValidationError("Invalid credentials")

        attrs['user'] = user
        return attrs
