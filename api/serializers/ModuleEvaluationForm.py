from rest_framework import serializers
from ..models import ModuleEvaluationForm, Classroom
from ..models.FeedbackResponse import FeedbackResponse
from django.contrib.contenttypes.models import ContentType

class ModuleEvaluationFormSerializer(serializers.ModelSerializer):
    classroom_code = serializers.CharField(write_only=True, required=False)
    module_name = serializers.CharField(
        source="subject_description", read_only=True
    )
    instructor_name = serializers.SerializerMethodField()
    is_completed = serializers.SerializerMethodField(read_only=True)
    completed_response_id = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = ModuleEvaluationForm
        fields = [
            "id",
            "classroom",          
            "classroom_code",     
            "subject_code",       
            "module_name",
            "instructor_name",        
            "description",
            "status",
            "created_at",
            "updated_at",
            "is_completed",
            "completed_response_id",
        ]
        read_only_fields = [
            "id",
            "subject_code",
            "module_name",
            "instructor_name",
            "created_at",
            "updated_at",
            "is_completed",
            "completed_response_id"
        ]

    def _latest_response(self, obj, student_id):
        if not student_id:
            return None
        return (
            FeedbackResponse.objects
            .filter(
                student_id=student_id,
                form_content_type=ContentType.objects.get_for_model(obj),
                form_object_id=obj.id,
            )
            .order_by("-id")
            .first()
        )

    def get_is_completed(self, obj):
        req = self.context.get("request")
        student = getattr(req.user, "student", None) if req else None
        if not student:
            return False
        resp = self._latest_response(obj, student.id)
        return bool(resp)

    def get_completed_response_id(self, obj):
        req = self.context.get("request")
        student = getattr(req.user, "student", None) if req else None
        if not student:
            return None
        resp = self._latest_response(obj, student.id)
        return resp.id if resp else None
    
    def get_instructor_name(self, obj):
        fac = getattr(obj.classroom, "faculty", None)
        if fac:
            return f"{fac.firstname} {fac.lastname}"
        return ""
    
    def validate(self, attrs):
        code = attrs.pop("classroom_code", None)
        if code:
            try:
                attrs["classroom"] = Classroom.objects.get(
                    classroom_code=code
                )
            except Classroom.DoesNotExist:
                raise serializers.ValidationError(
                    {"classroom_code": "Invalid classroom_code"}
                )

        classroom = attrs.get("classroom")
        if not classroom:
            raise serializers.ValidationError(
                {"classroom": "This field is required."}
            )

        attrs["subject_code"] = classroom.subject_code
        attrs["subject_description"] = classroom.module_name

        return super().validate(attrs)

    def create(self, validated_data):
        validated_data.pop("classroom_code", None)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data.pop("classroom_code", None)
        return super().update(instance, validated_data)