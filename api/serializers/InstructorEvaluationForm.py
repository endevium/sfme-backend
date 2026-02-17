from rest_framework import serializers
from django.contrib.contenttypes.models import ContentType
from ..models.InstructorEvaluationForm import InstructorEvaluationForm
from ..models.FeedbackResponse import FeedbackResponse

class InstructorEvaluationFormSerializer(serializers.ModelSerializer):
    # expose `instructor_name` as `title` for frontend compatibility
    title = serializers.CharField(source='instructor_name')
    is_completed = serializers.SerializerMethodField()
    completed_response_id = serializers.SerializerMethodField()

    class Meta:
        model = InstructorEvaluationForm
        fields = [
            'id',
            'title',
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
        ct = ContentType.objects.get_for_model(InstructorEvaluationForm)
        return FeedbackResponse.objects.filter(
        student=student,
        form_content_type=ct,
        form_object_id=obj.id,
        ).exists()

    def get_completed_response_id(self, obj):
        student = self._get_student()
        if not student:
            return None
        ct = ContentType.objects.get_for_model(InstructorEvaluationForm)
        fr = FeedbackResponse.objects.filter(
        student=student,
        form_content_type=ct,
        form_object_id=obj.id,
        ).order_by('-submitted_at').first()
        return fr.id if fr else None

    def create(self, validated_data):
        return super().create(validated_data)
