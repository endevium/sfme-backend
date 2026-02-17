from rest_framework import serializers
from ..models.EnrolledModule import EnrolledModule
from ..models.Student import Student
from ..models.ModuleAssignment import ModuleAssignment

class EnrolledModuleSerializer(serializers.ModelSerializer):
    student_id = serializers.PrimaryKeyRelatedField(queryset=Student.objects.all(), source='student', write_only=True)
    module_assignment_id = serializers.PrimaryKeyRelatedField(queryset=ModuleAssignment.objects.all(), source='module_assignment', write_only=True)
    student = serializers.SerializerMethodField(read_only=True)
    module_assignment = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = EnrolledModule
        fields = [
            "id",
            "student_id",
            "module_assignment_id",
            "student",
            "module_assignment"
        ]
    
    def get_student(self, obj):
        if not obj.student:
            return None
        return {
            "id": obj.student.id,
            "student_number": getattr(obj.student, "student_number", None),
            "firstname": getattr(obj.student, "firstname", None),
            "lastname": getattr(obj.student, "lastname", None)
        }

    def get_module_assignment(self, obj):
        ma = getattr(obj, "module_assignment", None)
        if not ma:
            return None
        module = getattr(ma, "module", None)
        faculty = getattr(ma, "faculty", None)
        return {
            "id": getattr(ma, "id", None),
            "subject_code": getattr(module, "subject_code", None),
            "module_name": getattr(module, "module_name", None),
            "department": getattr(module, "department", None),
            "faculty_firstname": getattr(faculty, "firstname", None),
            "faculty_lastname": getattr(faculty, "lastname", None),
            "semester": getattr(module, "semester", None),
            "academic_year": getattr(module, "academic_year", None),
        }

    def validate(self, attrs):
        if EnrolledModule.objects.filter(student=attrs['student'], module_assignment=attrs['module_assignment']).exists():
            raise serializers.ValidationError("Student is already enrolled in this subject")
        return attrs
    
    def create(self, validated_data):
        return EnrolledModule.objects.create(**validated_data)