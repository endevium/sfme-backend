from rest_framework import serializers
from ..password_rules import validate_strong_password


class PasswordResetConfirmSerializer(serializers.Serializer):
    pending_token = serializers.CharField()
    new_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        pending_token = attrs.get('pending_token')
        new_password = attrs.get('new_password')

        if not pending_token:
            raise serializers.ValidationError('Pending token is required')

        # Validate password rules
        validate_strong_password(new_password)

        return attrs
