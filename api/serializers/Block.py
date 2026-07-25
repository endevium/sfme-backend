# api/serializers/Block.py
from rest_framework import serializers
from ..models.Block import Block
from ..models.Program import Program

class BlockSerializer(serializers.ModelSerializer):
    program = serializers.PrimaryKeyRelatedField(
        queryset=Program.objects.all()
    )
    department = serializers.CharField(read_only=True)

    class Meta:
        model = Block
        fields = ["id", "program", "department", "year_level", "block_name"]
        read_only_fields = ["id", "department"]

    def validate(self, attrs):
        instance = getattr(self, "instance", None)

        program = attrs.get("program") if "program" in attrs else getattr(instance, "program", None)
        year_level = attrs.get("year_level") if "year_level" in attrs else getattr(instance, "year_level", "")
        block_name = attrs.get("block_name") if "block_name" in attrs else getattr(instance, "block_name", "")

        if not program:
            raise serializers.ValidationError({"program": "Program is required."})

        normalized_block_name = str(block_name or "").strip()
        normalized_year_level = str(year_level or "").strip()
        if not normalized_block_name:
            raise serializers.ValidationError({"block_name": "Block/section name is required."})
        if not normalized_year_level:
            raise serializers.ValidationError({"year_level": "Year level is required."})

        duplicate_qs = Block.objects.filter(
            program=program,
            year_level__iexact=normalized_year_level,
            block_name__iexact=normalized_block_name,
        )
        if instance:
            duplicate_qs = duplicate_qs.exclude(id=instance.id)

        if duplicate_qs.exists():
            raise serializers.ValidationError(
                {"block_name": "This block/section already exists for the selected program and year level."}
            )

        attrs["block_name"] = normalized_block_name
        attrs["year_level"] = normalized_year_level
        return attrs

    def validate_program(self, prog):
        head = self.context.get("dept_head")
        if head and prog.department != head.department:
            raise serializers.ValidationError(
                "Cannot create a block for a program you don't own."
            )
        return prog

    def create(self, validated_data):
        prog = validated_data["program"]
        validated_data["department"] = prog.department
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data.pop("department", None)
        if "program" in validated_data:
            validated_data["department"] = validated_data["program"].department
        return super().update(instance, validated_data)