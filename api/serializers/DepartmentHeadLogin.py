from rest_framework import serializers
from ..models.DepartmentHead import DepartmentHead
from ..utils import is_password_expired

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
        
        if user and is_password_expired(user):
            user.must_change_password = True
            user.save(update_fields=["must_change_password"])

        attrs['user'] = user
        return attrs
