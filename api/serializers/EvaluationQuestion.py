from rest_framework import serializers
from ..models.EvaluationQuestion import EvaluationQuestion

class EvaluationQuestionSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)

    class Meta:
        model = EvaluationQuestion
        fields = '__all__'

    def validate_question_type(self, value):
        v = str(value).lower()
        allowed = {'scale', 'rating', 'text', 'comment'}
        if v not in allowed:
            raise serializers.ValidationError(f"Unsupported question_type '{value}'")
        # keep the raw value (model choices should accept it)
        return v

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not data.get('code'):
            data['code'] = f"q_{instance.id}"
        data['question'] = data.get('question_text')
        return data