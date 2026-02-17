from rest_framework import serializers
from django.contrib.contenttypes.models import ContentType
from ..models.FeedbackResponse import FeedbackResponse
from ..models.EvaluationQuestion import EvaluationQuestion
from ..models.ModuleEvaluationForm import ModuleEvaluationForm
from ..models.InstructorEvaluationForm import InstructorEvaluationForm
from ..models.EvaluationForm import EvaluationForm

class FeedbackResponseItemSerializer(serializers.Serializer):
    question = serializers.CharField()
    rating = serializers.IntegerField(min_value=1, max_value=5, required=False)
    comment = serializers.CharField(required=False, allow_blank=True)

class FeedbackResponseSerializer(serializers.ModelSerializer):
    form_type = serializers.ChoiceField(choices=[('module','module'), ('instructor','instructor')], write_only=True)
    form_id = serializers.CharField(write_only=True)

    # Accept input list, but don't let DRF try to serialize stored JSON using this schema
    responses = serializers.ListField(child=FeedbackResponseItemSerializer(), write_only=True)
    responses_out = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = FeedbackResponse
        fields = [
            'id',
            'form_type', 'form_id',
            'student', 'pseudonym',
            'responses',        # write-only input
            'responses_out',    # read-only output
            'sentiment', 'is_anonymous', 'ip_address', 'submitted_at'
        ]
        read_only_fields = ['id', 'student', 'ip_address', 'sentiment', 'submitted_at', 'responses_out']

    def _extract_allowed_question_codes_from_form(self, form_obj, form_type):
        ef_type = 'Module' if form_type == 'module' else 'Instructor'
        
        title = None
        if form_type == 'module':
            title = getattr(form_obj, 'subject_code', None) or str(form_obj)
        else:
            title = getattr(form_obj, 'instructor_name', None) or str(form_obj)
        title = str(title).strip()
        
        ef = EvaluationForm.objects.filter(form_type=ef_type, title__iexact=title).first()
        if not ef or not isinstance(ef.questions, list):
            return set()

        allowed = set()
        for section in ef.questions:
            if not isinstance(section, dict):
                continue
            qs = section.get('questions', [])
            if not isinstance(qs, list):
                continue
            for q in qs:
                if isinstance(q, dict) and q.get('id'):
                    allowed.add(str(q['id']).strip())
        return allowed

    def _find_question(self, identifier):
        if str(identifier).isdigit():
            q = EvaluationQuestion.objects.filter(pk=int(identifier)).first()
            if q:
                return q
        if hasattr(EvaluationQuestion, 'code'):
            q = EvaluationQuestion.objects.filter(code=identifier).first()
            if q:
                return q
        return None
    
    def validate_responses(self, value):
        if not isinstance(value, list) or not value:
            raise serializers.ValidationError('responses must be a non-empty list')
        
        # If validate() already resolved the form, use its question set for validation
        form_type = (self.initial_data.get('form_type') or '').strip().lower()
        form_obj = getattr(self, '_resolved_form_obj', None)
        allowed_codes = set()
        if form_obj and form_type in ('module', 'instructor'):
            allowed_codes = self._extract_allowed_question_codes_from_form(form_obj, form_type)
        
        seen = set()
        normalized = []
        for item in value:
            q_ident = item.get('question')
            if not q_ident:
                raise serializers.ValidationError("each response must include 'question'")
            if q_ident in seen:
                raise serializers.ValidationError(f"duplicate question '{q_ident}'")
            seen.add(q_ident)

            if allowed_codes:
                if str(q_ident).strip() not in allowed_codes:
                    raise serializers.ValidationError(f"unknown question '{q_ident}'")
                # Still try to resolve to EvaluationQuestion for storage (optional)
                q = self._find_question(q_ident)
            else:
                q = self._find_question(q_ident)

            if not allowed_codes and not q:
                raise serializers.ValidationError(f"unknown question '{q_ident}'")
            rating = item.get('rating')
            comment = item.get('comment')
            q_type = None
            if q:
                q_type = getattr(q, 'type', None) or getattr(q, 'question_type', None)

            if q_type and str(q_type).lower() in ('scale','rating','number') and rating is None:
                raise serializers.ValidationError(f"question '{q_ident}' requires a rating")
            if rating is not None:
                try:
                    r = int(rating)
                    if r < 1 or r > 5:
                        raise Exception()
                except Exception:
                    raise serializers.ValidationError("rating must be integer between 1 and 5")
            normalized.append({
                'question_id': q.id if q else None,
                'question_code': getattr(q, 'code', None) if q else str(q_ident).strip(),
                'rating': rating,
                'comment': comment,
            })
        return normalized
    
    def get_responses_out(self, instance):
        expanded = []

        raw_responses = None
        if isinstance(instance, dict):
            raw_responses = instance.get('responses') or instance.get('responses_out') or []
        else:
            raw_responses = getattr(instance, 'responses', None) or []

        for r in (raw_responses or []):
            q_text = None
            try:
                qid = r.get('question_id')
                if qid:
                    q = EvaluationQuestion.objects.get(pk=qid)
                    q_text = getattr(q, 'question_text', None)
            except Exception:
                q_text = None

            if not q_text:
                q_text = r.get('question_code') or r.get('question_id')

            expanded.append({
                'question_id': r.get('question_id'),
                'question_code': r.get('question_code'),
                'question_text': q_text,
                'rating': r.get('rating'),
                'comment': r.get('comment'),
            })
        return expanded

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # keep legacy key name "responses" for frontend convenience
        data['responses'] = data.pop('responses_out', [])
        return data
    
    def validate(self, attrs):
        form_type = (self.initial_data.get('form_type') or attrs.pop('form_type', None))
        form_id = (self.initial_data.get('form_id') or attrs.pop('form_id', None))
        if not form_type or form_id in (None, ''):
            raise serializers.ValidationError("form_type and form_id are required")

        model = ModuleEvaluationForm if form_type == 'module' else InstructorEvaluationForm if form_type == 'instructor' else None
        if not model:
            raise serializers.ValidationError({'form_type': 'invalid value'})

        obj = None
        # try numeric PK first
        try:
            fid = int(str(form_id))
            obj = model.objects.filter(pk=fid).first()
        except (ValueError, TypeError):
            pass

        # fallback to code/name identifier
        if not obj:
            ident = str(form_id).strip()
            if model is ModuleEvaluationForm:
                obj = ModuleEvaluationForm.objects.filter(subject_code__iexact=ident).first()
            else:
                obj = InstructorEvaluationForm.objects.filter(instructor_name__iexact=ident).first()

        if not obj:
            raise serializers.ValidationError({'form_id': 'form not found'})

        # store resolved form object for validate_responses()
        self._resolved_form_obj = obj

        # block submissions when form is not Active (fixes "can still evaluate draft/closed")
        status = getattr(obj, 'status', None)
        if str(status).lower() != 'active':
            raise serializers.ValidationError({'form_id': f'form not available (status: {status})'})

        attrs['form_content_type'] = ContentType.objects.get_for_model(model)
        attrs['form_object_id'] = obj.id
        return attrs

    def create(self, validated_data):
        # Sentiment analysis is handled externally
        validated_data.pop('form_type', None)
        validated_data.pop('form_id', None)

        student = validated_data.pop('student', None)
        ip = validated_data.pop('ip_address', None)
        responses = validated_data.pop('responses', [])
        validated_data['responses'] = responses
        validated_data['sentiment'] = None
        return FeedbackResponse.objects.create(student=student, ip_address=ip, **validated_data)

    # ...keep validate_responses, sentiment logic, create and to_representation...