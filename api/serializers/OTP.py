from rest_framework import serializers

class SendOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()

class VerifyOTPSerializer(serializers.Serializer):
    pending_token = serializers.CharField()
    otp = serializers.CharField(min_length=6, max_length=6)