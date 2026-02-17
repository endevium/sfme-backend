from rest_framework import serializers
from .models import Student, Faculty, DepartmentHead, EvaluationForm, AuditLog, ModuleEvaluationForm, InstructorEvaluationForm
from django.contrib.auth import authenticate

# Students
class StudentSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False)
    must_change_password = serializers.BooleanField(read_only=True)

    class Meta:
        model = Student
        fields = [
            'id',
            'student_number',
            'email',
            'password',
            'profile_picture',
            'firstname',
            'middlename',
            'lastname',
            'contact_number',
            'department',
            'program',
            'enrolled_subjects',
            'block_section',
            'year_level',
            'birthdate',
            'must_change_password',
        ]

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        student = Student(**validated_data)
        birthdate = validated_data.get('birthdate')
        if birthdate:
            first = (validated_data.get('firstname') or '').strip()
            middle = (validated_data.get('middlename') or '').strip()
            last = (validated_data.get('lastname') or '').strip()

            first_two = first[:2].upper()
            middle_two = middle[:2].upper() if middle else ''
            last_two = last[:2].upper()

            name_key = f"{first_two}{middle_two}{last_two}"
            month_year = f"{birthdate.month}{birthdate.year}"
            password = f"{name_key}{month_year}"

        if not password:
            raise serializers.ValidationError("Password or birthdate is required to create a student")

        student.set_password(password)
        student.must_change_password = True
        student.save()
        return student

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance

class StudentChangePasswordSerializer(serializers.Serializer):
    student_number = serializers.CharField()
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        student_number = attrs.get('student_number')
        old_password = attrs.get('old_password')
        new_password = attrs.get('new_password')

        if not new_password or len(new_password) < 6:
            raise serializers.ValidationError("New password must be at least 6 characters")

        try:
            student = Student.objects.get(student_number=student_number)
        except Student.DoesNotExist:
            raise serializers.ValidationError("Invalid credentials")

        if not student.check_password(old_password):
            raise serializers.ValidationError("Invalid credentials")

        attrs['user'] = student
        return attrs

class FacultyChangePasswordSerializer(serializers.Serializer):
    email = serializers.CharField()
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email = attrs.get('email')
        old_password = attrs.get('old_password')
        new_password = attrs.get('new_password')

        if not new_password or len(new_password) < 6:
            raise serializers.ValidationError("New password must be at least 6 characters")

        try:
            faculty = Faculty.objects.get(email=email)
        except Faculty.DoesNotExist:
            raise serializers.ValidationError("Invalid credentials")

        if not faculty.check_password(old_password):
            raise serializers.ValidationError("Invalid credentials")

        attrs['user'] = faculty
        return attrs

# Faculty
class FacultySerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False)
    must_change_password = serializers.BooleanField(read_only=True)

    class Meta:
        model = Faculty
        fields = [
            'id',
            'email',
            'password',
            'profile_picture',
            'firstname',
            'middlename',
            'lastname',
            'contact_number',
            'department',
            'status',
            'birthdate',
            'must_change_password',
        ]

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        faculty = Faculty(**validated_data)
        birthdate = validated_data.get('birthdate')
        if birthdate:
            first = (validated_data.get('firstname') or '').strip()
            middle = (validated_data.get('middlename') or '').strip()
            last = (validated_data.get('lastname') or '').strip()

            first_two = first[:2].upper()
            middle_two = middle[:2].upper() if middle else ''
            last_two = last[:2].upper()

            name_key = f"{first_two}{middle_two}{last_two}"
            month_year = f"{birthdate.month}{birthdate.year}"
            password = f"{name_key}{month_year}"

        if not password:
            raise serializers.ValidationError("Password or birthdate is required to create a faculty")

        faculty.set_password(password)
        faculty.must_change_password = True
        faculty.save()
        return faculty

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


# Department Heads
class DepartmentHeadSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = DepartmentHead
        fields = [
            'id',
            'email',
            'password',
            'profile_picture',
            'firstname',
            'middlename',
            'lastname',
            'contact_number',
            'department',
            'status',
            'birthdate',
        ]

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        head = DepartmentHead(**validated_data)
        if password:
            head.set_password(password)
        head.save()
        return head

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance

# Login
class StudentLoginSerializer(serializers.Serializer):
    student_number = serializers.CharField()  
    password = serializers.CharField(write_only=True)
    role = serializers.CharField(required=False)

    def validate(self, attrs):
        student_number = attrs.get('student_number')
        password = attrs.get('password')

        user = None

        try:
            student = Student.objects.get(student_number=student_number)
            if student.check_password(password):
                user = student
        except Student.DoesNotExist:
            pass

        if not user:
            raise serializers.ValidationError("Invalid credentials")

        attrs['user'] = user
        return attrs

class FacultyLoginSerializer(serializers.Serializer):
    email = serializers.CharField()  
    password = serializers.CharField(write_only=True)
    role = serializers.CharField(required=False)

    def validate(self, attrs):
        email = attrs.get('email')
        password = attrs.get('password')

        user = None

        try:
            faculty = Faculty.objects.get(email=email)
            if faculty.check_password(password):
                user = faculty
        except Faculty.DoesNotExist:
            pass

        if not user:
            try:
                head = DepartmentHead.objects.get(email__iexact=email)
                if head.check_password(password):
                    user = head
            except DepartmentHead.DoesNotExist:
                pass

        if not user:
            raise serializers.ValidationError("Invalid credentials")

        attrs['user'] = user
        return attrs

class DepartmentHeadLoginSerializer(serializers.Serializer):
    email = serializers.CharField()  
    password = serializers.CharField(write_only=True)
    role = serializers.CharField(required=False)

    def validate(self, attrs):
        email = attrs.get('email')
        password = attrs.get('password')

        user = None

        try:
            head = DepartmentHead.objects.get(email=email)
            if head.check_password(password):
                user = head
        except DepartmentHead.DoesNotExist:
            pass

        if not user:
            raise serializers.ValidationError("Invalid credentials")

        attrs['user'] = user
        return attrs

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


class ModuleEvaluationFormSerializer(serializers.ModelSerializer):
    # expose `subject_code` as `title` for frontend compatibility
    title = serializers.CharField(source='subject_code')

    class Meta:
        model = ModuleEvaluationForm
        fields = [
            'id',
            'title',
            'subject_description',
            'description',
            'status',
            'created_at',
        ]

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


class InstructorEvaluationFormSerializer(serializers.ModelSerializer):
    # expose `instructor_name` as `title` for frontend compatibility
    title = serializers.CharField(source='instructor_name')

    class Meta:
        model = InstructorEvaluationForm
        fields = [
            'id',
            'title',
            'description',
            'status',
            'created_at',
        ]

    def create(self, validated_data):
        return super().create(validated_data)

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