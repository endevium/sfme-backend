from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.exceptions import ValidationError as DRFValidationError
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from .throttles import AIRequestRateThrottle, LoginRateThrottle
from .models import Student
from .sentiment_service import predict_sentiment
import csv
import io
from .recaptcha import verify_recaptcha_v2

from .models.AuditLog import AuditLog
from .models.DepartmentHead import DepartmentHead
from .models.EvaluationForm import EvaluationForm
from .models.Faculty import Faculty
from .models.InstructorEvaluationForm import InstructorEvaluationForm
from .models.Module import Module
from .models.ModuleAssignment import ModuleAssignment
from .models.ModuleEvaluationForm import ModuleEvaluationForm
from .models.Student import Student
from .models.FeedbackResponse import FeedbackResponse
from .models.OTP import EmailOTP

from .serializers.AuditLog import AuditLogSerializer
from .serializers.DepartmentHead import DepartmentHeadSerializer
from .serializers.DepartmentHeadLogin import DepartmentHeadLoginSerializer
from .serializers.EvaluationForm import EvaluationFormSerializer
from .serializers.Faculty import FacultySerializer
from .serializers.FacultyChangePassword import FacultyChangePasswordSerializer
from .serializers.FacultyLogin import FacultyLoginSerializer
from .serializers.InstructorEvaluationForm import InstructorEvaluationFormSerializer
from .serializers.ModuleEvaluationForm import ModuleEvaluationFormSerializer
from .serializers.Student import StudentSerializer
from .serializers.StudentChangePassword import StudentChangePasswordSerializer
from .serializers.StudentLogin import StudentLoginSerializer
from .serializers.FeedbackResponse import FeedbackResponseSerializer
from .serializers.OTP import SendOTPSerializer, VerifyOTPSerializer

from .utils import create_and_send_otp

def _issue_jwt(role: str, legacy_user_id: int) -> str:
    token = AccessToken()
    token["role"] = role
    token["legacy_user_id"] = legacy_user_id
    token["user_id"] = legacy_user_id
    return str(token)

def _get_bearer_token(request) -> str | None:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header.split(" ", 1)[1].strip()
    return None

# List all students or create a new student
class StudentListCreateView(generics.ListCreateAPIView):
    authentication_classes = []
    permission_classes = []
    queryset = Student.objects.all()
    serializer_class = StudentSerializer

    def create(self, request, *args, **kwargs):
        # Manual authentication for department head
        token = _get_bearer_token(request)
        if not token:
            return Response({"detail": "No token provided", "auth_header": request.headers.get("Authorization")}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            decoded_token = AccessToken(token)
        except Exception as e:
            return Response({"detail": "Invalid token", "error": str(e)}, status=status.HTTP_401_UNAUTHORIZED)

        if decoded_token.get("role") != "department_head":
            return Response({"detail": "Forbidden - token role mismatch", "token_role": decoded_token.get("role")}, status=status.HTTP_403_FORBIDDEN)

        # Accept either legacy_user_id or the standard user_id claim
        dept_head_id = decoded_token.get("legacy_user_id") or decoded_token.get("user_id") or decoded_token.get("sub")
        if not dept_head_id:
            return Response(
                {"detail": "Invalid token payload - user id not found", "token_claims": list(decoded_token.keys())},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
             dept_head = DepartmentHead.objects.get(id=dept_head_id)
        except DepartmentHead.DoesNotExist:
            return Response(
                {
                   "detail": f"Department head not found (id={dept_head_id})",
                    "used_id": dept_head_id,
                    "used_id_type": type(dept_head_id).__name__,
                    "token_claims": dict(decoded_token),
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # Attach the dept head to the request so serializers / signals can access it
        request.user = dept_head

        try:
            response = super().create(request, *args, **kwargs)
        except DRFValidationError as exc:
            # Return serializer validation errors to the client (400)
            return Response({"detail": "Validation error", "errors": exc.detail}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            return Response({"detail": str(e), "trace": tb}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if response.status_code == status.HTTP_201_CREATED:
            # Get the created student
            student = Student.objects.get(id=response.data['id'])
            
            # Log the creation
            user_name = f"{dept_head.firstname} {dept_head.lastname}".strip() or dept_head.email or 'Depthead User'
            AuditLog.objects.create(
                user=user_name,
                role='Depthead',
                action='Create Student',
                category='USER MANAGEMENT',
                status='Success',
                message=f'Created new student: {student.firstname} {student.lastname} ({student.student_number})',
                ip=request.META.get('REMOTE_ADDR', 'Unknown')
            )
        
        return response
    
# Retrieve, update, or delete a single student
class StudentDetailView(generics.RetrieveUpdateDestroyAPIView):
    authentication_classes = []
    permission_classes = []
    queryset = Student.objects.all()
    serializer_class = StudentSerializer

    def retrieve(self, request, *args, **kwargs):
        # Manual authentication for department head
        token = _get_bearer_token(request)
        if not token:
            return Response({"detail": "No token provided"}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            decoded_token = AccessToken(token)
        except Exception as e:
            return Response({"detail": "Invalid token", "error": str(e)}, status=status.HTTP_401_UNAUTHORIZED)

        if decoded_token.get("role") != "department_head":
            return Response({"detail": "Forbidden - token role mismatch"}, status=status.HTTP_403_FORBIDDEN)

        return super().retrieve(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        # Manual authentication for department head
        token = _get_bearer_token(request)
        if not token:
            return Response({"detail": "No token provided"}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            decoded_token = AccessToken(token)
        except Exception as e:
            return Response({"detail": "Invalid token", "error": str(e)}, status=status.HTTP_401_UNAUTHORIZED)

        if decoded_token.get("role") != "department_head":
            return Response({"detail": "Forbidden - token role mismatch"}, status=status.HTTP_403_FORBIDDEN)

        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        # Manual authentication for department head
        token = _get_bearer_token(request)
        if not token:
            return Response({"detail": "No token provided"}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            decoded_token = AccessToken(token)
        except Exception as e:
            return Response({"detail": "Invalid token", "error": str(e)}, status=status.HTTP_401_UNAUTHORIZED)

        if decoded_token.get("role") != "department_head":
            return Response({"detail": "Forbidden - token role mismatch"}, status=status.HTTP_403_FORBIDDEN)

        return super().destroy(request, *args, **kwargs)

class FacultyListCreateView(generics.ListCreateAPIView):
    authentication_classes = []
    permission_classes = []
    queryset = Faculty.objects.all()
    serializer_class = FacultySerializer

    def create(self, request, *args, **kwargs):
        # Manual authentication for department head
        token = _get_bearer_token(request)
        if not token:
            return Response({"detail": "No token provided"}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            decoded_token = AccessToken(token)
        except:
            return Response({"detail": "Invalid token"}, status=status.HTTP_401_UNAUTHORIZED)

        if decoded_token.get("role") != "department_head":
            return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        dept_head_id = decoded_token.get("legacy_user_id")
        if not dept_head_id:
            return Response({"detail": "Invalid token payload"}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            dept_head = DepartmentHead.objects.get(id=dept_head_id)
        except DepartmentHead.DoesNotExist:
            return Response({"detail": "Department head not found"}, status=status.HTTP_404_NOT_FOUND)

        response = super().create(request, *args, **kwargs)
        
        if response.status_code == status.HTTP_201_CREATED:
            # Get the created faculty
            faculty = Faculty.objects.get(id=response.data['id'])
            
            # Log the creation
            user_name = f"{dept_head.firstname} {dept_head.lastname}".strip() or dept_head.email or 'Depthead User'
            AuditLog.objects.create(
                user=user_name,
                role='Depthead',
                action='Create Faculty',
                category='USER MANAGEMENT',
                status='Success',
                message=f'Created new faculty: {faculty.firstname} {faculty.lastname} ({faculty.email})',
                ip=request.META.get('REMOTE_ADDR', 'Unknown')
            )
        
        return response

class FacultyDetailView(generics.RetrieveUpdateDestroyAPIView):
    authentication_classes = []
    permission_classes = []
    queryset = Faculty.objects.all()
    serializer_class = FacultySerializer

class DepartmentHeadListCreateView(generics.ListCreateAPIView):
    queryset = DepartmentHead.objects.all()
    serializer_class = DepartmentHeadSerializer

class DepartmentHeadDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = DepartmentHead.objects.all()
    serializer_class = DepartmentHeadSerializer

class StudentLoginView(APIView):
    throttle_classes = [LoginRateThrottle]
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        verify_recaptcha_v2(
            token=request.data.get("recaptcha_token"),
            remote_ip=request.META.get("REMOTE_ADDR"),
        )

        serializer = StudentLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']

        try:
            record = create_and_send_otp(
                email=user.email,
                ttl_minutes=5,
                purpose=EmailOTP.Purpose.LOGIN,
                role=EmailOTP.Role.STUDENT
            )
        except Exception:
            return Response(
                {"detail": "Failed to send OTP email. Please try again later."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )


        return Response(
            {
                "otp_required": True,
                "detail": "OTP has been sent to your email",
                "pending_token": record.pending_token,
                "expires_at": record.expires_at,
                "user_type": "student",
                "email": user.email,
                "must_change_password": user.must_change_password,
            },
            status=status.HTTP_200_OK,
        )

class FacultyLoginView(APIView):
    throttle_classes = [LoginRateThrottle]
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        verify_recaptcha_v2(
            token=request.data.get("recaptcha_token"),
            remote_ip=request.META.get("REMOTE_ADDR"),
        )

        serializer = FacultyLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']

        try:
            record = create_and_send_otp(
                email=user.email,
                ttl_minutes=5,
                purpose=EmailOTP.Purpose.LOGIN,
                role=EmailOTP.Role.FACULTY
            )
        except Exception:
            return Response(
                {"detail": "Failed to send OTP email. Please try again later."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )


        return Response(
            {
                "otp_required": True,
                "detail": "OTP has been sent to your email",
                "pending_token": record.pending_token,
                "expires_at": record.expires_at,
                "user_type": "faculty",
                "email": user.email,
                "must_change_password": user.must_change_password,
            },
            status=status.HTTP_200_OK,
        )

class DepartmentHeadLoginView(APIView):
    throttle_classes = [LoginRateThrottle]
    authentication_classes = []
    permission_classes = []
    
    def post(self, request):
        verify_recaptcha_v2(
            token=request.data.get("recaptcha_token"),
            remote_ip=request.META.get("REMOTE_ADDR"),
        )

        serializer = DepartmentHeadLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']

        try:
            record = create_and_send_otp(
                email=user.email,
                ttl_minutes=5,
                purpose=EmailOTP.Purpose.LOGIN,
                role=EmailOTP.Role.DEPARTMENT_HEAD
            )
        except Exception:
            return Response(
                {"detail": "Failed to send OTP email. Please try again later."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            {
                "otp_required": True,
                "detail": "OTP has been sent to your email",
                "pending_token": record.pending_token,
                "expires_at": record.expires_at,
                "user_type": "department_head",
                "email": user.email,
            },
            status=status.HTTP_200_OK,
        )

class StudentChangePasswordView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = StudentChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']

        new_password = serializer.validated_data['new_password']
        user.set_password(new_password)
        user.must_change_password = False
        user.save()

        return Response({"detail": "Password updated"}, status=status.HTTP_200_OK)

class FacultyChangePasswordView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = FacultyChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']

        new_password = serializer.validated_data['new_password']
        user.set_password(new_password)
        user.must_change_password = False
        user.save()

        return Response({"detail": "Password updated"}, status=status.HTTP_200_OK)

class StudentMeView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        token_str = _get_bearer_token(request)
        if not token_str:
            return Response({"detail": "Authorization token missing"}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            token = AccessToken(token_str)
        except Exception:
            return Response({"detail": "Invalid token"}, status=status.HTTP_401_UNAUTHORIZED)

        if token.get("role") != "student":
            return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        student_id = token.get("legacy_user_id")
        if not student_id:
            return Response({"detail": "Invalid token payload"}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            student = Student.objects.get(id=student_id)
            # Provide enrolled subjects/modules so frontend can determine available forms
            enrolled = student.enrolled_subjects or []
            enrolled_codes = [item.get('code', '').strip().upper() for item in enrolled if isinstance(item, dict) and item.get('code')]
            # Normalize into a minimal module shape expected by frontend
            enrolled_modules = []
            if isinstance(enrolled, list):
                for item in enrolled:
                    if isinstance(item, dict) and item.get('code'):
                        c = item['code'].strip()
                        instructor_name = ''
                        try:
                            module = Module.objects.get(subject_code=c)
                            assignment = ModuleAssignment.objects.filter(module=module).first()
                            if assignment:
                                faculty = assignment.faculty
                                instructor_name = f"{faculty.firstname} {faculty.lastname}"
                        except:
                            pass
                        enrolled_modules.append({
                            "id": c,
                            "code": c,
                            "name": item.get('description', c),
                            "instructor": instructor_name,
                            "description": item.get('description', ''),
                            "form_available": False,
                        })

            return Response({
                "student": {
                    "id": student.id,
                    "student_number": student.student_number,
                    "email": student.email,
                    "firstname": student.firstname,
                    "lastname": student.lastname,
                    "program": student.program,
                    "year_level": student.year_level,
                    "enrolled_subjects": enrolled,
                },
                "stats": {
                    "total_modules": len(enrolled_modules),
                    "instructors": 0,
                    "completed": 0,
                    "pending": 0,
                },
                "enrolled_modules": enrolled_modules,
                "recent_modules": enrolled_modules[:5],
            }, status=status.HTTP_200_OK)
        except Student.DoesNotExist:
            return Response({"detail": "Student not found"}, status=status.HTTP_404_NOT_FOUND)
    
class EvaluationFormListCreateView(generics.ListCreateAPIView):
    authentication_classes = []
    permission_classes = []
    queryset = EvaluationForm.objects.all()
    serializer_class = EvaluationFormSerializer

    def create(self, request, *args, **kwargs):
        # Manual authentication for department head
        token = _get_bearer_token(request)
        if not token:
            return Response({"detail": "No token provided"}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            decoded_token = AccessToken(token)
        except:
            return Response({"detail": "Invalid token"}, status=status.HTTP_401_UNAUTHORIZED)

        if decoded_token.get("role") != "department_head":
            return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        dept_head_id = decoded_token.get("legacy_user_id")
        if not dept_head_id:
            return Response({"detail": "Invalid token payload"}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            dept_head = DepartmentHead.objects.get(id=dept_head_id)
        except DepartmentHead.DoesNotExist:
            return Response({"detail": "Department head not found"}, status=status.HTTP_404_NOT_FOUND)

        request.user = dept_head

        response = super().create(request, *args, **kwargs)
        if response.status_code == status.HTTP_201_CREATED:
            form_data = response.data
            user_name = 'System'
            if hasattr(request, 'user') and request.user:
                user_name = f"{request.user.firstname} {request.user.lastname}".strip() or request.user.email or 'Depthead User'
            AuditLog.objects.create(
                user=user_name,
                role='Depthead',
                action='Created Evaluation Form',
                category='FORM MANAGEMENT',
                status='Success',
                message=f'Created new form: {form_data.get("title", "Unknown")}',
                ip=request.META.get('REMOTE_ADDR', 'Unknown')
            )
        return response

class EvaluationFormDetailView(generics.RetrieveUpdateDestroyAPIView):
    authentication_classes = []
    permission_classes = []
    queryset = EvaluationForm.objects.all()
    serializer_class = EvaluationFormSerializer

    def perform_update(self, serializer):
        # Manual authentication for department head
        token = _get_bearer_token(self.request)
        if token:
            try:
                decoded_token = AccessToken(token)
                if decoded_token.get("role") == "department_head":
                    dept_head_id = decoded_token.get("legacy_user_id")
                    if dept_head_id:
                        try:
                            dept_head = DepartmentHead.objects.get(id=dept_head_id)
                            self.request.user = dept_head
                        except DepartmentHead.DoesNotExist:
                            pass
            except:
                pass

        old_instance = self.get_object()
        super().perform_update(serializer)
        new_instance = serializer.instance
        # Log the update
        user_name = 'System'
        if hasattr(self.request, 'user') and self.request.user:
            user_name = f"{self.request.user.firstname} {self.request.user.lastname}".strip() or self.request.user.email or 'Depthead User'
        AuditLog.objects.create(
            user=user_name,
            role='Depthead',
            action='Updated Evaluation Form',
            category='FORM MANAGEMENT',
            status='Success',
            message=f'Updated form: {new_instance.title}',
            ip=self.request.META.get('REMOTE_ADDR', 'Unknown')
        )

    def perform_destroy(self, instance):
        # Manual authentication for department head
        token = _get_bearer_token(self.request)
        if token:
            try:
                decoded_token = AccessToken(token)
                if decoded_token.get("role") == "department_head":
                    dept_head_id = decoded_token.get("legacy_user_id")
                    if dept_head_id:
                        try:
                            dept_head = DepartmentHead.objects.get(id=dept_head_id)
                            self.request.user = dept_head
                        except DepartmentHead.DoesNotExist:
                            pass
            except:
                pass

        # Log the deletion
        user_name = 'System'
        if hasattr(self.request, 'user') and self.request.user:
            user_name = f"{self.request.user.firstname} {self.request.user.lastname}".strip() or self.request.user.email or 'Depthead User'
        AuditLog.objects.create(
            user=user_name,
            role='Depthead',
            action='Deleted Evaluation Form',
            category='FORM MANAGEMENT',
            status='Success',
            message=f'Deleted form: {instance.title}',
            ip=self.request.META.get('REMOTE_ADDR', 'Unknown')
        )
        super().perform_destroy(instance)


class ModuleEvaluationFormListCreateView(generics.ListCreateAPIView):
    authentication_classes = []
    permission_classes = []
    queryset = ModuleEvaluationForm.objects.all()
    serializer_class = ModuleEvaluationFormSerializer

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = self.get_serializer(page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(qs, many=True, context={'request': request})
        return Response(serializer.data)

    def get_queryset(self):
        queryset = ModuleEvaluationForm.objects.filter(status='Active')
        token = _get_bearer_token(self.request)
        if token:
            try:
                decoded_token = AccessToken(token)
                if decoded_token.get("role") == "student":
                    student_id = decoded_token.get("legacy_user_id")
                    if student_id:
                        try:
                            student = Student.objects.get(id=student_id)
                            enrolled = student.enrolled_subjects or []
                            enrolled_codes = [item.get('code', '').strip().upper() for item in enrolled if isinstance(item, dict) and item.get('code')]
                            if enrolled_codes:
                                queryset = queryset.filter(title__in=enrolled_codes)
                        except Student.DoesNotExist:
                            pass
            except:
                pass
        return queryset

    def create(self, request, *args, **kwargs):
        token = _get_bearer_token(request)
        if not token:
            return Response({"detail": "No token provided"}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            decoded_token = AccessToken(token)
        except:
            return Response({"detail": "Invalid token"}, status=status.HTTP_401_UNAUTHORIZED)
        if decoded_token.get("role") != "department_head":
            return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        request.user = None
        response = super().create(request, *args, **kwargs)
        if response.status_code == status.HTTP_201_CREATED:
            form_data = response.data
            user_name = 'System'
            AuditLog.objects.create(
                user=user_name,
                role='Depthead',
                action='Created Module Evaluation Form',
                category='FORM MANAGEMENT',
                status='Success',
                message=f'Created new module form: {form_data.get("title", "Unknown")}',
                ip=request.META.get('REMOTE_ADDR', 'Unknown')
            )
        return response


class ModuleEvaluationFormDetailView(generics.RetrieveUpdateDestroyAPIView):
    authentication_classes = []
    permission_classes = []
    queryset = ModuleEvaluationForm.objects.all()
    serializer_class = ModuleEvaluationFormSerializer

    def perform_update(self, serializer):
        token = _get_bearer_token(self.request)
        if token:
            try:
                decoded_token = AccessToken(token)
                if decoded_token.get("role") == "department_head":
                    dept_head_id = decoded_token.get("legacy_user_id")
                    if dept_head_id:
                        try:
                            dept_head = DepartmentHead.objects.get(id=dept_head_id)
                            self.request.user = dept_head
                        except DepartmentHead.DoesNotExist:
                            pass
            except:
                pass

        old_instance = self.get_object()
        super().perform_update(serializer)
        new_instance = serializer.instance
        user_name = 'System'
        if hasattr(self.request, 'user') and self.request.user:
            user_name = f"{self.request.user.firstname} {self.request.user.lastname}".strip() or self.request.user.email or 'Depthead User'
        AuditLog.objects.create(
            user=user_name,
            role='Depthead',
            action='Updated Module Evaluation Form',
            category='FORM MANAGEMENT',
            status='Success',
            message=f'Updated module form: {getattr(new_instance, "subject_code", "Unknown")}',
            ip=self.request.META.get('REMOTE_ADDR', 'Unknown')
        )

    def perform_destroy(self, instance):
        user_name = 'System'
        if hasattr(self.request, 'user') and self.request.user:
            user_name = f"{self.request.user.firstname} {self.request.user.lastname}".strip() or self.request.user.email or 'Depthead User'
        AuditLog.objects.create(
            user=user_name,
            role='Depthead',
            action='Deleted Module Evaluation Form',
            category='FORM MANAGEMENT',
            status='Success',
            message=f'Deleted module form: {getattr(instance, "subject_code", "Unknown")}',
            ip=self.request.META.get('REMOTE_ADDR', 'Unknown')
        )
        super().perform_destroy(instance)


class InstructorEvaluationFormListCreateView(generics.ListCreateAPIView):
    authentication_classes = []
    permission_classes = []
    queryset = InstructorEvaluationForm.objects.all()
    serializer_class = InstructorEvaluationFormSerializer

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = self.get_serializer(page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(qs, many=True, context={'request': request})
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        token = _get_bearer_token(request)
        if not token:
            return Response({"detail": "No token provided"}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            decoded_token = AccessToken(token)
        except:
            return Response({"detail": "Invalid token"}, status=status.HTTP_401_UNAUTHORIZED)
        if decoded_token.get("role") != "department_head":
            return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        request.user = None
        response = super().create(request, *args, **kwargs)
        if response.status_code == status.HTTP_201_CREATED:
            form_data = response.data
            user_name = 'System'
            AuditLog.objects.create(
                user=user_name,
                role='Depthead',
                action='Created Instructor Evaluation Form',
                category='FORM MANAGEMENT',
                status='Success',
                message=f'Created new instructor form: {form_data.get("title", "Unknown")}',
                ip=request.META.get('REMOTE_ADDR', 'Unknown')
            )
        return response


class InstructorEvaluationFormDetailView(generics.RetrieveUpdateDestroyAPIView):
    authentication_classes = []
    permission_classes = []
    queryset = InstructorEvaluationForm.objects.all()
    serializer_class = InstructorEvaluationFormSerializer

    def perform_update(self, serializer):
        token = _get_bearer_token(self.request)
        if token:
            try:
                decoded_token = AccessToken(token)
                if decoded_token.get("role") == "department_head":
                    dept_head_id = decoded_token.get("legacy_user_id")
                    if dept_head_id:
                        try:
                            dept_head = DepartmentHead.objects.get(id=dept_head_id)
                            self.request.user = dept_head
                        except DepartmentHead.DoesNotExist:
                            pass
            except:
                pass

        old_instance = self.get_object()
        super().perform_update(serializer)
        new_instance = serializer.instance
        user_name = 'System'
        if hasattr(self.request, 'user') and self.request.user:
            user_name = f"{self.request.user.firstname} {self.request.user.lastname}".strip() or self.request.user.email or 'Depthead User'
        AuditLog.objects.create(
            user=user_name,
            role='Depthead',
            action='Updated Instructor Evaluation Form',
            category='FORM MANAGEMENT',
            status='Success',
            message=f'Updated instructor form: {getattr(new_instance, "instructor_name", "Unknown")}',
            ip=self.request.META.get('REMOTE_ADDR', 'Unknown')
        )

    def perform_destroy(self, instance):
        user_name = 'System'
        if hasattr(self.request, 'user') and self.request.user:
            user_name = f"{self.request.user.firstname} {self.request.user.lastname}".strip() or self.request.user.email or 'Depthead User'
        AuditLog.objects.create(
            user=user_name,
            role='Depthead',
            action='Deleted Instructor Evaluation Form',
            category='FORM MANAGEMENT',
            status='Success',
            message=f'Deleted instructor form: {getattr(instance, "instructor_name", "Unknown")}',
            ip=self.request.META.get('REMOTE_ADDR', 'Unknown')
        )
        super().perform_destroy(instance)

class StudentBulkImportView(APIView):
    """Bulk import students from CSV file"""

    def post(self, request):
        # Manual authentication for department head
        token = _get_bearer_token(request)
        if not token:
            return Response({"detail": "No token provided"}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            decoded_token = AccessToken(token)
        except:
            return Response({"detail": "Invalid token"}, status=status.HTTP_401_UNAUTHORIZED)

        if decoded_token.get("role") != "department_head":
            return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        dept_head_id = decoded_token.get("legacy_user_id")
        if not dept_head_id:
            return Response({"detail": "Invalid token payload"}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            dept_head = DepartmentHead.objects.get(id=dept_head_id)
        except DepartmentHead.DoesNotExist:
            return Response({"detail": "Department head not found"}, status=status.HTTP_404_NOT_FOUND)

        # Check if file is provided
        if 'file' not in request.FILES:
            return Response({"detail": "No file provided"}, status=status.HTTP_400_BAD_REQUEST)

        csv_file = request.FILES['file']
        if not csv_file.name.endswith('.csv'):
            return Response({"detail": "File must be a CSV"}, status=status.HTTP_400_BAD_REQUEST)

        # Parse CSV and create students
        try:
            decoded_file = csv_file.read().decode('utf-8')
            csv_reader = csv.DictReader(io.StringIO(decoded_file))

            created_count = 0
            errors = []

            for row_num, row in enumerate(csv_reader, start=2):  # Start at 2 to account for header
                try:
                    # Validate required fields
                    required_fields = ['email', 'firstname', 'lastname', 'student_id']
                    for field in required_fields:
                        if not row.get(field, '').strip():
                            errors.append(f"Row {row_num}: Missing required field '{field}'")
                            continue

                    # Check if student already exists
                    if Student.objects.filter(email=row['email']).exists():
                        errors.append(f"Row {row_num}: Student with email '{row['email']}' already exists")
                        continue

                    if Student.objects.filter(student_number=row['student_id']).exists():
                        errors.append(f"Row {row_num}: Student with ID '{row['student_id']}' already exists")
                        continue

                    # Parse enrolled_subjects (semicolon-separated) and block
                    raw_subjects = row.get('enrolled_subjects', '').strip()
                    subjects_list = [s.strip() for s in raw_subjects.split(';') if s.strip()] if raw_subjects else []
                    block_val = row.get('block_section', '').strip()

                    # Create student
                    year_val = row.get('year_level', '').strip()
                    try:
                        year_val_parsed = int(year_val) if year_val else None
                    except ValueError:
                        year_val_parsed = None

                    student = Student.objects.create(
                        email=row['email'].strip(),
                        firstname=row['firstname'].strip(),
                        lastname=row['lastname'].strip(),
                        student_number=row['student_id'].strip(),
                        department=row.get('department', '').strip(),
                        program=row.get('course', '').strip(),
                        year_level=year_val_parsed,
                        enrolled_subjects=subjects_list,
                        block_section=block_val or None,
                        must_change_password=True
                    )
                    created_count += 1

                except Exception as e:
                    errors.append(f"Row {row_num}: {str(e)}")

            # Log the bulk import
            user_name = f"{dept_head.firstname} {dept_head.lastname}".strip() or dept_head.email or 'Depthead User'
            AuditLog.objects.create(
                user=user_name,
                role='Depthead',
                action='Bulk Import Students',
                category='USER MANAGEMENT',
                status='Success' if created_count > 0 else 'Failed',
                message=f'Imported {created_count} new student records from CSV file. {len(errors)} errors encountered.',
                ip=request.META.get('REMOTE_ADDR', 'Unknown')
            )

            return Response({
                "message": f"Successfully imported {created_count} students",
                "created_count": created_count,
                "errors": errors[:10]  # Limit errors shown to first 10
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({"detail": f"Error processing CSV: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)


class FacultyBulkImportView(APIView):
    """Bulk import faculty from CSV file"""

    def post(self, request):
        # Manual authentication for department head
        token = _get_bearer_token(request)
        if not token:
            return Response({"detail": "No token provided"}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            decoded_token = AccessToken(token)
        except:
            return Response({"detail": "Invalid token"}, status=status.HTTP_401_UNAUTHORIZED)

        if decoded_token.get("role") != "department_head":
            return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        dept_head_id = decoded_token.get("legacy_user_id")
        if not dept_head_id:
            return Response({"detail": "Invalid token payload"}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            dept_head = DepartmentHead.objects.get(id=dept_head_id)
        except DepartmentHead.DoesNotExist:
            return Response({"detail": "Department head not found"}, status=status.HTTP_404_NOT_FOUND)

        # Check if file is provided
        if 'file' not in request.FILES:
            return Response({"detail": "No file provided"}, status=status.HTTP_400_BAD_REQUEST)

        csv_file = request.FILES['file']
        if not csv_file.name.endswith('.csv'):
            return Response({"detail": "File must be a CSV"}, status=status.HTTP_400_BAD_REQUEST)

        # Parse CSV and create faculty
        try:
            decoded_file = csv_file.read().decode('utf-8')
            csv_reader = csv.DictReader(io.StringIO(decoded_file))

            created_count = 0
            errors = []

            for row_num, row in enumerate(csv_reader, start=2):  # Start at 2 to account for header
                try:
                    # Validate required fields
                    required_fields = ['email', 'firstname', 'lastname', 'employee_id']
                    for field in required_fields:
                        if not row.get(field, '').strip():
                            errors.append(f"Row {row_num}: Missing required field '{field}'")
                            continue

                    # Check if faculty already exists
                    if Faculty.objects.filter(email=row['email']).exists():
                        errors.append(f"Row {row_num}: Faculty with email '{row['email']}' already exists")
                        continue

                    if Faculty.objects.filter(employee_id=row['employee_id']).exists():
                        errors.append(f"Row {row_num}: Faculty with ID '{row['employee_id']}' already exists")
                        continue

                    # Create faculty
                    faculty = Faculty.objects.create(
                        email=row['email'].strip(),
                        firstname=row['firstname'].strip(),
                        lastname=row['lastname'].strip(),
                        employee_id=row['employee_id'].strip(),
                        department=row.get('department', '').strip(),
                        position=row.get('position', '').strip(),
                        must_change_password=True
                    )
                    created_count += 1

                except Exception as e:
                    errors.append(f"Row {row_num}: {str(e)}")

            # Log the bulk import
            user_name = f"{dept_head.firstname} {dept_head.lastname}".strip() or dept_head.email or 'Depthead User'
            AuditLog.objects.create(
                user=user_name,
                role='Depthead',
                action='Bulk Import Faculty',
                category='USER MANAGEMENT',
                status='Success' if created_count > 0 else 'Failed',
                message=f'Imported {created_count} new faculty records from CSV file. {len(errors)} errors encountered.',
                ip=request.META.get('REMOTE_ADDR', 'Unknown')
            )

            return Response({
                "message": f"Successfully imported {created_count} faculty members",
                "created_count": created_count,
                "errors": errors[:10]  # Limit errors shown to first 10
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({"detail": f"Error processing CSV: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)


class AuditLogListView(generics.ListCreateAPIView):
    authentication_classes = []
    permission_classes = []
    queryset = AuditLog.objects.filter(role__in=['Depthead', 'Department Head'])
    serializer_class = AuditLogSerializer

    def list(self, request, *args, **kwargs):
        # Manual authentication for department head
        token = _get_bearer_token(request)
        if not token:
            return Response({"detail": "No token provided"}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            decoded_token = AccessToken(token)
        except:
            return Response({"detail": "Invalid token"}, status=status.HTTP_401_UNAUTHORIZED)

        if decoded_token.get("role") != "department_head":
            return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        return super().list(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        # Manual authentication for department head
        token = _get_bearer_token(request)
        if not token:
            return Response({"detail": "No token provided"}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            decoded_token = AccessToken(token)
        except:
            return Response({"detail": "Invalid token"}, status=status.HTTP_401_UNAUTHORIZED)

        if decoded_token.get("role") != "department_head":
            return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        dept_head_id = decoded_token.get("legacy_user_id")
        if not dept_head_id:
            return Response({"detail": "Invalid token payload"}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            dept_head = DepartmentHead.objects.get(id=dept_head_id)
        except DepartmentHead.DoesNotExist:
            return Response({"detail": "Department head not found"}, status=status.HTTP_404_NOT_FOUND)

        # Create the audit log with the correct user
        data = request.data.copy()
        data['user'] = f"{dept_head.firstname} {dept_head.lastname}".strip() or dept_head.email or 'Depthead User'
        data['role'] = 'Depthead'
        data['ip'] = request.META.get('REMOTE_ADDR', 'Unknown')

        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

class FeedbackResponseCreateView(generics.CreateAPIView):
    authentication_classes = []
    permission_classes = []
    serializer_class = FeedbackResponseSerializer
    queryset = FeedbackResponse.objects.all()

    def create(self, request, *args, **kwargs):
        token = _get_bearer_token(request)
        student = None
        if token:
            try:
                decoded = AccessToken(token)
                if decoded.get('role') == 'student':
                    sid = decoded.get('legacy_user_id') or decoded.get('user_id') or decoded.get('sub')
                    if sid:
                        student = Student.objects.filter(pk=sid).first()
                        if not student:
                            return Response({"detail": "Student not found"}, status=status.HTTP_401_UNAUTHORIZED)
            except Exception:
                return Response({"detail": "Invalid token"}, status=status.HTTP_401_UNAUTHORIZED)

        data = request.data.copy()

        # Backwards compatibility: accept legacy "form" (single id) or new form_type+form_id
        if not (data.get('form_type') and data.get('form_id')):
            legacy_form_id = data.get('form')
            if legacy_form_id is None:
                return Response({"detail": "form_type+form_id or legacy 'form' field required"}, status=status.HTTP_400_BAD_REQUEST)

            module_obj = None
            instructor_obj = None
            try:
                legacy_pk = int(str(legacy_form_id))
                module_obj = ModuleEvaluationForm.objects.filter(pk=legacy_pk).first()
                instructor_obj = InstructorEvaluationForm.objects.filter(pk=legacy_pk).first()
            except (ValueError, TypeError):
                legacy_str = str(legacy_form_id).strip()
                if legacy_str:
                    module_obj = ModuleEvaluationForm.objects.filter(subject_code__iexact=legacy_str).first()
                    instructor_obj = InstructorEvaluationForm.objects.filter(instructor_name__iexact=legacy_str).first()

            if module_obj:
                data['form_type'] = 'module'
                data['form_id'] = module_obj.id
            elif instructor_obj:
                data['form_type'] = 'instructor'
                data['form_id'] = instructor_obj.id
            else:
                return Response({"detail": "Form not found"}, status=status.HTTP_404_NOT_FOUND)

        # Validate target form exists and prevent duplicate submissions
        model = ModuleEvaluationForm if data['form_type'] == 'module' else InstructorEvaluationForm if data['form_type'] == 'instructor' else None
        if not model:
            return Response({"detail": "invalid form_type"}, status=status.HTTP_400_BAD_REQUEST)
        form_identifier = data.get('form_id')
        form_obj = None
        try:
            fid = int(str(form_identifier))
            form_obj = model.objects.filter(pk=fid).first()
        except (ValueError, TypeError):
            ident = str(form_identifier).strip()
            if model is ModuleEvaluationForm:
                form_obj = ModuleEvaluationForm.objects.filter(subject_code__iexact=ident).first()
            else:
                form_obj = InstructorEvaluationForm.objects.filter(instructor_name__iexact=ident).first()

        if not form_obj:
            return Response({"detail": "Form not found"}, status=status.HTTP_404_NOT_FOUND)

        ct = ContentType.objects.get_for_model(model)
        if student and FeedbackResponse.objects.filter(form_content_type=ct, form_object_id=form_obj.id, student=student).exists():
            return Response({"detail": "You have already submitted feedback for this form"}, status=status.HTTP_400_BAD_REQUEST)

        if not student and not data.get('pseudonym') and not data.get('is_anonymous', False):
            return Response({"detail": "Provide pseudonym or submit as anonymous or authenticate as student"}, status=status.HTTP_400_BAD_REQUEST)

        serializer = self.get_serializer(data=data)
        try:
            serializer.is_valid(raise_exception=True)
        except DRFValidationError as exc:
            errors = exc.detail

            def _flatten(e, prefix=""):
                # turns nested DRF error structures into a readable string
                if isinstance(e, dict):
                    parts = []
                    for k, v in e.items():
                        key = f"{prefix}.{k}" if prefix else str(k)
                        parts.append(_flatten(v, key))
                    return "; ".join([p for p in parts if p])
                if isinstance(e, (list, tuple)):
                    return "; ".join([_flatten(i, prefix) for i in e if i])
                return f"{prefix}: {e}" if prefix else str(e)

            message = _flatten(errors) or "Validation error"
            return Response(
                {"detail": message, "errors": errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        obj = serializer.save(
            student=student,
            ip_address=request.META.get('REMOTE_ADDR', 'Unknown'),
        )
        
        out = self.get_serializer(obj).data
        headers = self.get_success_headers(out)
        return Response(out, status=status.HTTP_201_CREATED, headers=headers)

class FeedbackResponseListView(generics.ListAPIView):
    authentication_classes = []
    permission_classes = []
    serializer_class = FeedbackResponseSerializer

    def list(self, request, *args, **kwargs):
        token = _get_bearer_token(request)
        if not token:
            return Response({"detail": "No token provided"}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            decoded = AccessToken(token)
        except Exception:
            return Response({"detail": "Invalid token"}, status=status.HTTP_401_UNAUTHORIZED)
        if decoded.get("role") != "department_head":
            return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)
        dept_head_id = decoded.get("legacy_user_id") or decoded.get("user_id") or decoded.get("sub")
        if not dept_head_id:
            return Response({"detail": "Invalid token payload"}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            DepartmentHead.objects.get(id=dept_head_id)
        except DepartmentHead.DoesNotExist:
            return Response({"detail": "Department head not found"}, status=status.HTTP_404_NOT_FOUND)

        qs = FeedbackResponse.objects.all()
        form = request.query_params.get('form')
        if form:
            qs = qs.filter(form_id=form)
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)

class SentimentTestView(APIView):
    throttle_classes = []
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        text = request.data.get("text")
        if not text:
            return Response({"detail": 'Missing "text" field'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            label = predict_sentiment(text)
        except Exception as e:
            return Response({"detail": "Model error", "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"label": label}, status=status.HTTP_200_OK)
    
class SendOTPView(APIView):
    throttle_classes = [LoginRateThrottle]
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = SendOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"].strip().lower()

        role = None
        if Student.objects.filter(email__iexact=email).exists():
            role = EmailOTP.Role.STUDENT
        elif Faculty.objects.filter(email__iexact=email).exists():
            role = EmailOTP.Role.FACULTY
        elif DepartmentHead.objects.filter(email__iexact=email).exists():
            role = EmailOTP.Role.DEPARTMENT_HEAD
        else:
            return Response({"detail": "Email not found"}, status=status.HTTP_404_NOT_FOUND)

        record = create_and_send_otp(
            email=email,
            ttl_minutes=5,
            purpose=EmailOTP.Purpose.LOGIN,
            role=role,
        )

        return Response(
            {
                "detail": "OTP has been sent to your email",
                "pending_token": record.pending_token,
                "expires_at": record.expires_at,
            },
            status=status.HTTP_200_OK,
        )

class VerifyOTPView(APIView):
    throttle_classes = [LoginRateThrottle]
    authentication_classes = []
    permission_classes = []

    MAX_ATTEMPTS = 5

    def post(self, request):
        serializer = VerifyOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        pending_token = serializer.validated_data["pending_token"].strip()
        otp = serializer.validated_data["otp"].strip()

        record = EmailOTP.objects.filter(pending_token=pending_token).order_by("-created_at").first()
        if not record:
            return Response({"detail": "Invalid pending token"}, status=status.HTTP_400_BAD_REQUEST)

        if record.is_used:
            return Response({"detail": "OTP already used"}, status=status.HTTP_400_BAD_REQUEST)

        if record.is_expired():
            return Response({"detail": "OTP expired"}, status=status.HTTP_400_BAD_REQUEST)

        if record.attempts >= self.MAX_ATTEMPTS:
            return Response({"detail": "Too many attempts"}, status=status.HTTP_429_TOO_MANY_REQUESTS)

        if record.otp != otp:
            record.attempts = record.attempts + 1
            record.save(update_fields=["attempts"])
            return Response({"detail": "Invalid OTP"}, status=status.HTTP_400_BAD_REQUEST)

        # success
        record.is_used = True
        record.save(update_fields=["is_used"])

        # For LOGIN: issue JWT for the linked user
        if record.purpose == EmailOTP.Purpose.LOGIN:
            # STUDENT
            if record.role == EmailOTP.Role.STUDENT:
                user = Student.objects.filter(email__iexact=record.email).first()
                if not user:
                    return Response({"detail": "User not found"}, status=status.HTTP_404_NOT_FOUND)

                token = _issue_jwt("student", user.id)
                return Response(
                    {
                        "detail": "OTP verified",
                        "token": token,
                        "user_type": "student",
                        "id": user.id,
                        "student_number": user.student_number,
                        "email": user.email,
                        "firstname": user.firstname,
                        "lastname": user.lastname,
                        "must_change_password": user.must_change_password,
                    },
                    status=status.HTTP_200_OK,
                )

            # FACULTY
            if record.role == EmailOTP.Role.FACULTY:
                user = Faculty.objects.filter(email__iexact=record.email).first()
                if not user:
                    return Response({"detail": "User not found"}, status=status.HTTP_404_NOT_FOUND)

                token = _issue_jwt("faculty", user.id)
                return Response(
                    {
                        "detail": "OTP verified",
                        "token": token,
                        "user_type": "faculty",
                        "id": user.id,
                        "email": user.email,
                        "firstname": user.firstname,
                        "lastname": user.lastname,
                        "must_change_password": user.must_change_password,
                    },
                    status=status.HTTP_200_OK,
                )

            # DEPARTMENT HEAD
            if record.role == EmailOTP.Role.DEPARTMENT_HEAD:
                user = DepartmentHead.objects.filter(email__iexact=record.email).first()
                if not user:
                    return Response({"detail": "User not found"}, status=status.HTTP_404_NOT_FOUND)

                token = _issue_jwt("department_head", user.id)
                return Response(
                    {
                        "detail": "OTP verified",
                        "token": token,
                        "user_type": "department_head",
                        "id": user.id,
                        "email": user.email,
                        "firstname": user.firstname,
                        "lastname": user.lastname,
                    },
                    status=status.HTTP_200_OK,
                )

            return Response({"detail": "Unsupported role"}, status=status.HTTP_400_BAD_REQUEST)

        # For RESET_PASSWORD: (leave as-is if you implemented it already)
        if record.purpose == EmailOTP.Purpose.RESET_PASSWORD:
            return Response({"detail": "Unsupported purpose"}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"detail": "Unsupported purpose"}, status=status.HTTP_400_BAD_REQUEST)