from rest_framework import serializers
from django.contrib.contenttypes.models import ContentType
from ..models.ModuleEvaluationForm import ModuleEvaluationForm
from ..models.FeedbackResponse import FeedbackResponse

class ModuleEvaluationFormSerializer(serializers.ModelSerializer):
    # expose `subject_code` as `title` for frontend compatibility
    title = serializers.CharField(source='subject_code')
    is_completed = serializers.SerializerMethodField()
    completed_response_id = serializers.SerializerMethodField()

    class Meta:
        model = ModuleEvaluationForm
        fields = [
            'id',
            'title',
            'subject_description',
            'description',
            'status',
            'created_at',
            'is_completed',
            'completed_response_id',
        ]

    def _get_student(self):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        return getattr(user, 'student', None)

    def get_is_completed(self, obj):
        student = self._get_student()
        if not student:
            return False
        ct = ContentType.objects.get_for_model(ModuleEvaluationForm)
        return FeedbackResponse.objects.filter(
        student=student,
        form_content_type=ct,
        form_object_id=obj.id,
        ).exists()

    def get_completed_response_id(self, obj):
        student = self._get_student()
        if not student:
            return None
        ct = ContentType.objects.get_for_model(ModuleEvaluationForm)
        fr = FeedbackResponse.objects.filter(
        student=student,
        form_content_type=ct,
        form_object_id=obj.id,
        ).order_by('-submitted_at').first()
        return fr.id if fr else None


    def create(self, validated_data):
        # `title` is mapped to subject_code via source
        # If frontend sent `description` but not `subject_description`, copy it over
        if 'subject_description' not in validated_data and 'description' in validated_data:
            validated_data['subject_description'] = validated_data.get('description')
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if 'subject_description' not in validated_data and 'description' in validated_data:
            validated_data['subject_description'] = validated_data.get('description')
        return super().update(instance, validated_data)
