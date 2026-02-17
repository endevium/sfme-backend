from rest_framework import serializers
from ..models.Faculty import Faculty

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
