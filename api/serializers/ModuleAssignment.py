from rest_framework import serializers
from ..models.ModuleAssignment import ModuleAssignment
from ..models.Module import Module
from ..models.Faculty import Faculty

class ModuleAssignmentSerializer(serializers.ModelSerializer):
    module_id = serializers.PrimaryKeyRelatedField(queryset=Module.objects.all(), source='module', write_only=True)
    faculty_id = serializers.PrimaryKeyRelatedField(queryset=Faculty.objects.all(), source='faculty', write_only=True)
    module = serializers.SerializerMethodField(read_only=True)
    faculty = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = ModuleAssignment
        fields = [
            'id',
            'module_id',
            'faculty_id',
            'module',
            'faculty'
        ]
    
    def get_module(self, obj):
        if not obj.module:
            return None
        return {
            "id": obj.module.id,
            "subject_code": getattr(obj.module, "subject_code", None),
            "module_name": getattr(obj.module, "module_name", None),
            "department": getattr(obj.module, "department", None),
            "semester": getattr(obj.module, "semester", None),
            "academic_year": getattr(obj.module, "academic_year", None),
        }

    def get_faculty(self, obj):
        if not obj.faculty:
            return None
        return {
            "id": obj.faculty.id,
            "firstname": getattr(obj.faculty, "firstname", None),
            "lastname": getattr(obj.faculty, "lastname", None),
            "email": getattr(obj.faculty, "email", None),
        }
    
    def validate(self, attrs):
        if ModuleAssignment.objects.filter(module=attrs['module'], faculty=attrs['faculty']).exists():
            raise serializers.ValidationError("Assignment already exists.")
        return attrs
    
