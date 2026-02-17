from rest_framework import serializers
from ..models.EvaluationForm import EvaluationForm

class EvaluationFormSerializer(serializers.ModelSerializer):
    questions_count = serializers.SerializerMethodField()
    usage_count = serializers.SerializerMethodField()

    class Meta:
        model = EvaluationForm
        fields = [
            'id',
            'title',
            'form_type',
            'description',
            'status',
            'questions',
            'questions_count',
            'usage_count',
            'created_at',
        ]

    def validate_title(self, value):
        """Validate title to prevent XSS and SQL injection attempts"""
        if not value or len(value.strip()) == 0:
            raise serializers.ValidationError("Title cannot be empty")
        if len(value) > 200:
            raise serializers.ValidationError("Title cannot exceed 200 characters")
        # Check for potentially dangerous characters
        dangerous_chars = ['<', '>', '&', '"', "'", ';', '--', '/*', '*/']
        for char in dangerous_chars:
            if char in value:
                raise serializers.ValidationError(f"Title contains invalid character: {char}")
        return value.strip()

    def validate_description(self, value):
        """Validate description to prevent XSS"""
        if value and len(value) > 1000:
            raise serializers.ValidationError("Description cannot exceed 1000 characters")
        if value:
            # Basic XSS prevention - remove script tags
            import re
            value = re.sub(r'<script[^>]*>.*?</script>', '', value, flags=re.IGNORECASE | re.DOTALL)
            value = re.sub(r'<[^>]+>', '', value)  # Remove all HTML tags
        return value

    def validate_questions(self, value):
        """Validate questions JSON structure"""
        if not isinstance(value, list):
            raise serializers.ValidationError("Questions must be a list")

        for i, question in enumerate(value):
            if not isinstance(question, dict):
                raise serializers.ValidationError(f"Question {i+1} must be an object")

            required_fields = ['type', 'question']
            for field in required_fields:
                if field not in question:
                    raise serializers.ValidationError(f"Question {i+1} missing required field: {field}")

            # Validate question text
            if len(question['question']) > 500:
                raise serializers.ValidationError(f"Question {i+1} text too long (max 500 chars)")

            # Prevent dangerous content in questions
            dangerous_patterns = ['<script', 'javascript:', r'on\w+\s*=', 'SELECT', 'INSERT', 'UPDATE', 'DELETE']
            for pattern in dangerous_patterns:
                if pattern.lower() in question['question'].lower():
                    raise serializers.ValidationError(f"Question {i+1} contains potentially dangerous content")

        return value

    def get_questions_count(self, obj):
        return len(obj.questions) if obj.questions else 0

    def get_usage_count(self, obj):
        # Placeholder for usage count, can be calculated based on evaluations
        return 0
