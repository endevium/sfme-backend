from rest_framework import serializers
from ..models.Student import Student

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

    def _normalize_enrolled_subjects(self, value):
        """
        Accept both legacy and new shapes.

        Legacy (strings):
          ["ITE370", "CS101"]

        New (objects):
          [{"code":"ITE370","description":"...","instructor_name":"..."}, ...]

        Normalize to objects:
          [{"code":"ITE370","description":"...","instructor_name":"..."}, ...]
        """
        if value is None:
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError("enrolled_subjects must be a list")

        normalized = []
        for item in value:
            if isinstance(item, str):
                code = item.strip()
                if code:
                    normalized.append({
                        "code": code,
                        "description": "",
                        "instructor_name": "",
                    })
                continue

            if isinstance(item, dict):
                code = str(item.get("code", "")).strip()
                if not code:
                    continue
                description = str(item.get("description", item.get("name", ""))).strip()
                instructor_name = str(
                    item.get("instructor_name", item.get("instructor", item.get("professor", "")))
                ).strip()
                normalized.append({
                    "code": code,
                    "description": description,
                    "instructor_name": instructor_name,
                })
                continue

        dedup = {}
        for x in normalized:
            dedup[x["code"].upper()] = x
        return list(dedup.values())

    def validate_enrolled_subjects(self, value):
        return self._normalize_enrolled_subjects(value)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        try:
            data["enrolled_subjects"] = self._normalize_enrolled_subjects(data.get("enrolled_subjects"))
        except Exception:
            data["enrolled_subjects"] = []
        return data

    def create(self, validated_data):
        password = validated_data.pop('password', None)

        if "enrolled_subjects" in validated_data:
            validated_data["enrolled_subjects"] = self._normalize_enrolled_subjects(
                validated_data.get("enrolled_subjects")
            )

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

        if "enrolled_subjects" in validated_data:
            validated_data["enrolled_subjects"] = self._normalize_enrolled_subjects(
                validated_data.get("enrolled_subjects")
            )

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if password:
            instance.set_password(password)

        instance.save()
        return instance
