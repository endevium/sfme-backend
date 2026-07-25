from rest_framework import serializers
from ..models.Program import Program

class ProgramSerializer(serializers.ModelSerializer):
    department = serializers.CharField(read_only=True)
    
    class Meta:
        model = Program
        fields = [
            "id", "program_name", "program_code",
            "department", "department_head",
        ]
        read_only_fields = ["id", "department"]

    def update(self, instance, validated_data):
        validated_data.pop("department", None)
        validated_data.pop("department_head", None)
        return super().update(instance, validated_data)