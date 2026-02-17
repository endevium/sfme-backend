from rest_framework import serializers
from ..models.AuditLog import AuditLog

class AuditLogSerializer(serializers.ModelSerializer):
    time = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = [
            'id',
            'user',
            'role',
            'action',
            'category',
            'status',
            'message',
            'ip',
            'time',
            'timestamp',
        ]

    def get_time(self, obj):
        return obj.timestamp.strftime('%b %d, %I:%M %p')