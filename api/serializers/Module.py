from rest_framework import serializers
from ..models.Module import Module

class ModuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Module
        fields = ['id', 'subject_code', 'module_name', 'department', 'semester', 'academic_year']

    def create(self, validated_data):
        return Module.objects.create(**validated_data)

    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance
    
