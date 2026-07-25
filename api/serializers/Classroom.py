import uuid
from rest_framework import serializers
from api.models import Classroom, Module, Block, Program

class ClassroomSerializer(serializers.ModelSerializer):
    faculty = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Classroom
        fields = [
            "id",
            "faculty",
            "block",
            "subject_code",
            "module_name",      
            "program",
            "year_level",
            "semester",
            "classroom_code",
            "schedule",
            "room"
        ]
        read_only_fields = ["id", "classroom_code", "faculty", "module_name"]

    def validate(self, attrs):
        faculty = getattr(self.context.get("request"), "user", None)
        if not faculty:
            raise serializers.ValidationError("Unable to determine faculty from token.")

        block = attrs.get("block") or getattr(self.instance, "block", None)
        if not block:
            raise serializers.ValidationError("Block/section is required.")
        if not Block.objects.filter(
            block_name__iexact=block,
            department=faculty.department,
        ).exists():
            raise serializers.ValidationError(
                "Block invalid or not in your department."
            )
            
        # subject / module
        subject_code = attrs.get("subject_code") or getattr(self.instance, "subject_code", None)
        if not subject_code:
            raise serializers.ValidationError("Subject code is required.")
        mod = Module.objects.filter(
            subject_code__iexact=subject_code,
            department=faculty.department,
        ).first()
        if not mod:
            raise serializers.ValidationError(
                "Subject code does not exist or is not in your department."
            )
        attrs["module_name"] = mod.module_name 

        # block
        block = attrs.get("block") or getattr(self.instance, "block", None)
        if not block:
            raise serializers.ValidationError("Block/section is required.")
        if not Block.objects.filter(
            block_name__iexact=block,
            department=faculty.department,
        ).exists():
            raise serializers.ValidationError(
                "Block/section invalid or not in your department."
            )

        program_val = attrs.get("program") or getattr(self.instance, "program", None)
        if not program_val:
            raise serializers.ValidationError("Program is required.")
        prog = Program.objects.filter(
            program_code__iexact=program_val,
            department=faculty.department,
        ).first()
        if not prog:
            prog = Program.objects.filter(
                program_name__iexact=program_val,
                department=faculty.department,
            ).first()
        if not prog:
            raise serializers.ValidationError(
                "Program does not exist or is not in your department."
            )
        attrs["program"] = prog.program_code 

        # Prevent duplicate classroom assignments for the same faculty + subject + block.
        # Different sections/blocks are allowed.
        duplicate_qs = Classroom.objects.filter(
            faculty=faculty,
            subject_code__iexact=subject_code,
            block__iexact=block,
        )
        if self.instance is not None:
            duplicate_qs = duplicate_qs.exclude(pk=self.instance.pk)
        if duplicate_qs.exists():
            raise serializers.ValidationError(
                "You already have a classroom with this subject code and block/section."
            )

        return super().validate(attrs)

    def create(self, validated_data):
        if not validated_data.get("classroom_code"):
            validated_data["classroom_code"] = uuid.uuid4().hex[:8].upper()
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data.pop("classroom_code", None)
        validated_data.pop("faculty", None)   
        return super().update(instance, validated_data)