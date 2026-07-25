from rest_framework import serializers
from ..models.FeedbackHash import FeedbackHash

class FeedbackHashSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeedbackHash
        fields = ['id', 'feedback_response', 'hash', 'tx_hash', 'created_at']
        read_only_fields = ['id', 'created_at']