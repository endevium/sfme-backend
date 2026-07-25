from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken
from .authentication import LegacyJWTAuthentication
from rest_framework.exceptions import ValidationError as DRFValidationError
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils.decorators import method_decorator
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from rest_framework.exceptions import ValidationError
import logging
import os
import requests
import re

from .throttles import AIRequestRateThrottle, LoginRateThrottle
from .models import Student
# from .sentiment_service import predict_sentiment, analyze_theme, BLOCKED_THEME_LABELS
from .security.implementation import sanitize_prompt, detect_poisoned_feedback
import csv
import io
from .recaptcha import verify_recaptcha_v2
from types import SimpleNamespace
from .blockchain import feedback_payload, compute_feedback_hash_hex, store_hash_onchain

from .models.AuditLog import AuditLog
from .models.DepartmentHead import DepartmentHead
from .models.FeedbackResponse import FeedbackResponse
from .models.ModuleEvaluationForm import ModuleEvaluationForm
from .models.InstructorEvaluationForm import InstructorEvaluationForm
from .models.EvaluationForm import EvaluationForm
from .models.Faculty import Faculty
from .models.InstructorEvaluationForm import InstructorEvaluationForm
from .models.Module import Module
from .models.Block import Block
from .models.Classroom import Classroom
from .models.ClassroomEnrollment import ClassroomEnrollment
from .models.Program import Program
from .models.ModuleEvaluationForm import ModuleEvaluationForm
from .models.Student import Student
from .models.FeedbackResponse import FeedbackResponse
from .models.FeedbackHash import FeedbackHash
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
from .serializers.PasswordReset import PasswordResetConfirmSerializer
from .serializers.Program import ProgramSerializer
from .serializers.Module import ModuleSerializer
from .serializers.Block import BlockSerializer
from .serializers.Classroom import ClassroomSerializer
from .serializers.ClassroomEnrollment import ClassroomEnrollmentSerializer


from .utils import create_and_send_otp, is_password_expired, validate_uploaded_csv, validate_plain_text
logger = logging.getLogger(__name__)

ACTIVE_STATUS = "active"
ARCHIVED_STATUS = "archived"

_SEXUAL_RE = re.compile(
    r"\b(daddy|mommy|porn|sex|sexy|nude|nsfw|cum|orgasm|xxx)\b",
    flags=re.IGNORECASE,
)
_HARSH_RE = re.compile(
    r"\b(fuck|fucking|shit|bitch|asshole|idiot|stupid|moron|bastard|dumb|crap|ugly|shut\s+the\s+fuck\s+up)\b",
    flags=re.IGNORECASE,
)
def _classify_blocked_theme_local(content: str):
    """Deterministic lexical checks to avoid fail-open moderation."""
    if _SEXUAL_RE.search(content):
        return "sexual content"
    if _HARSH_RE.search(content):
        return "harsh language"
    return None


def _classify_blocked_theme(text: str):
    content = str(text or "").strip()
    if not content:
        return None

    # Local deterministic checks first so moderation does not depend on model availability/rate limits.
    local_block = _classify_blocked_theme_local(content)
    if local_block:
        return local_block

    try:
        sentiment_label = str(predict_sentiment(content)).strip().lower()
        if "prompt injection detected" in sentiment_label:
            return "prompt injection"
        if "sexual words are not permitted" in sentiment_label:
            return "sexual content"
        if "harsh words are not permitted" in sentiment_label:
            return "harsh language"
    except Exception:
        pass

    try:
        theme = str(analyze_theme(content)).strip().lower()
    except Exception:
        return None
    if theme in BLOCKED_THEME_LABELS:
        return theme
    if "prompt injection detected" in theme:
        return "prompt injection"
    return None


def _run_feedback_ai_security_checks(comments):
    """Run AI security checks inspired by api/test_model.py for feedback comments."""
    violations = []
    normalized_feedbacks = []

    for idx, item in enumerate(comments):
        if isinstance(item, dict):
            text = item.get("text") or item.get("comment") or ""
            question = item.get("question")
        else:
            text = item
            question = None

        content = str(text or "").strip()
        if not content:
            continue

        prompt_check = sanitize_prompt(content)
        if not prompt_check.get("safe", True):
            violations.append(
                {
                    "index": idx,
                    "question": question,
                    "theme": "prompt injection",
                    "reason": prompt_check.get("reason") or "prompt_injection_detected",
                }
            )

        blocked_theme = _classify_blocked_theme(content)
        if blocked_theme:
            violations.append(
                {
                    "index": idx,
                    "question": question,
                    "theme": blocked_theme,
                    "reason": "restricted_theme",
                }
            )

        normalized_feedbacks.append(
            {
                "user": str(question or f"q_{idx}"),
                "text": content,
            }
        )

    if len(normalized_feedbacks) >= 3:
        poisoned, poison_info = detect_poisoned_feedback(normalized_feedbacks)
        if poisoned:
            violations.append(
                {
                    "index": None,
                    "question": None,
                    "theme": "poisoning",
                    "reason": poison_info.get("reason") or "poisoned_feedback_detected",
                }
            )

    deduped = []
    seen = set()
    for v in violations:
        key = (v.get("index"), v.get("question"), v.get("theme"), v.get("reason"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(v)

    return deduped


def _delete_connected_feedback_for_form(form_instance):
    """Delete feedback rows linked through GenericForeignKey to this form."""
    if not form_instance or not getattr(form_instance, "id", None):
        return {"responses_deleted": 0}

    form_content_type = ContentType.objects.get_for_model(form_instance.__class__)
    responses_qs = FeedbackResponse.objects.filter(
        form_content_type=form_content_type,
        form_object_id=form_instance.id,
    )
    responses_deleted = responses_qs.count()
    responses_qs.delete()
    return {"responses_deleted": responses_deleted}

def _issue_jwt(role: str, legacy_user_id: int) -> str:
    token = AccessToken()
    token["role"] = role
    token["legacy_user_id"] = legacy_user_id
    token["user_id"] = legacy_user_id
    return str(token)

def _issue_jwt_pair(role: str, legacy_user_id: int) -> dict:
    """
    Returns a token pair for your non-auth-user setup.
    refresh contains the same custom claims as access.
    """
    refresh = RefreshToken()
    refresh["role"] = role
    refresh["legacy_user_id"] = legacy_user_id
    refresh["user_id"] = legacy_user_id

    access = refresh.access_token
    access["role"] = role
    access["legacy_user_id"] = legacy_user_id
    access["user_id"] = legacy_user_id

    return {"access": str(access), "refresh": str(refresh)}

def _get_bearer_token(request) -> str | None:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header.split(" ", 1)[1].strip()
    return None


def _log_student_auth_event(student, action: str, message: str, request) -> None:
    if not student:
        return

    try:
        AuditLog.objects.create(
            user=f"{student.firstname} {student.lastname}".strip(),
            role="Student",
            action=action,
            category="AUTH",
            status="Success",
            message=message,
            ip=request.META.get("REMOTE_ADDR", "Unknown"),
        )
    except Exception:
        logger.exception("Failed to write student auth audit log")


def _log_faculty_auth_event(faculty, action: str, message: str, request) -> None:
    if not faculty:
        return

    try:
        AuditLog.objects.create(
            user=f"{faculty.firstname} {faculty.lastname}".strip(),
            role="Faculty",
            action=action,
            category="AUTH",
            status="Success",
            message=message,
            ip=request.META.get("REMOTE_ADDR", "Unknown"),
        )
    except Exception:
        logger.exception("Failed to write faculty auth audit log")


def _get_feedback_form_label(form_obj, fallback: str = "Unknown form") -> str:
    if isinstance(form_obj, ModuleEvaluationForm):
        return (
            getattr(form_obj, "subject_description", None)
            or getattr(form_obj, "subject_code", None)
            or fallback
        )
    if isinstance(form_obj, InstructorEvaluationForm):
        return getattr(form_obj, "instructor_name", None) or fallback
    return fallback

# List all students or create a new student
class StudentListCreateView(generics.ListCreateAPIView):
    authentication_classes = [LegacyJWTAuthentication]
    permission_classes = []
    queryset = Student.objects.all()
    serializer_class = StudentSerializer

    def get_queryset(self):
        return Student.objects.filter(status=ACTIVE_STATUS)

    def list(self, request, *args, **kwargs):
        token = _get_bearer_token(request)
        if not token:
            return Response({"detail": "No token provided"}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            decoded_token = AccessToken(token)
        except Exception as e:
            return Response({"detail": "Invalid token", "error": str(e)}, status=status.HTTP_401_UNAUTHORIZED)

        if decoded_token.get("role") != "department_head":
            return Response({"detail": "Forbidden - token role mismatch", "token_role": decoded_token.get("role")}, status=status.HTTP_403_FORBIDDEN)

        return super().list(request, *args, **kwargs)
    
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
    authentication_classes = [LegacyJWTAuthentication]
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


class ArchivedStudentListView(generics.ListAPIView):
    authentication_classes = [LegacyJWTAuthentication]
    permission_classes = []
    queryset = Student.objects.all()
    serializer_class = StudentSerializer

    def get_queryset(self):
        return Student.objects.filter(status=ARCHIVED_STATUS)

    def list(self, request, *args, **kwargs):
        token = _get_bearer_token(request)
        if not token:
            return Response({"detail": "No token provided"}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            decoded_token = AccessToken(token)
        except Exception as e:
            return Response({"detail": "Invalid token", "error": str(e)}, status=status.HTTP_401_UNAUTHORIZED)

        if decoded_token.get("role") != "department_head":
            return Response({"detail": "Forbidden - token role mismatch"}, status=status.HTTP_403_FORBIDDEN)

        return super().list(request, *args, **kwargs)

class FacultyListCreateView(generics.ListCreateAPIView):
    authentication_classes = [LegacyJWTAuthentication]
    permission_classes = []
    queryset = Faculty.objects.all()
    serializer_class = FacultySerializer

    def get_queryset(self):
        return Faculty.objects.filter(status=ACTIVE_STATUS)

    def list(self, request, *args, **kwargs):
        token = _get_bearer_token(request)
        if not token:
            return Response({"detail": "No token provided"}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            decoded_token = AccessToken(token)
        except Exception as e:
            return Response({"detail": "Invalid token", "error": str(e)}, status=status.HTTP_401_UNAUTHORIZED)

        if decoded_token.get("role") != "department_head":
            return Response({"detail": "Forbidden - token role mismatch", "token_role": decoded_token.get("role")}, status=status.HTTP_403_FORBIDDEN)

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

        response = super().create(request, *args, **kwargs)
        
        if response.status_code == status.HTTP_201_CREATED:
            faculty = Faculty.objects.get(id=response.data['id'])
            
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
    authentication_classes = [LegacyJWTAuthentication]
    permission_classes = []
    queryset = Faculty.objects.all()
    serializer_class = FacultySerializer

    def retrieve(self, request, *args, **kwargs):
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


class ArchivedFacultyListView(generics.ListAPIView):
    authentication_classes = [LegacyJWTAuthentication]
    permission_classes = []
    queryset = Faculty.objects.all()
    serializer_class = FacultySerializer

    def get_queryset(self):
        return Faculty.objects.filter(status=ARCHIVED_STATUS)

    def list(self, request, *args, **kwargs):
        token = _get_bearer_token(request)
        if not token:
            return Response({"detail": "No token provided"}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            decoded_token = AccessToken(token)
        except Exception as e:
            return Response({"detail": "Invalid token", "error": str(e)}, status=status.HTTP_401_UNAUTHORIZED)

        if decoded_token.get("role") != "department_head":
            return Response({"detail": "Forbidden - token role mismatch"}, status=status.HTTP_403_FORBIDDEN)

        return super().list(request, *args, **kwargs)

class DepartmentHeadListCreateView(generics.ListCreateAPIView):
    authentication_classes = [LegacyJWTAuthentication]
    permission_classes = []
    queryset = DepartmentHead.objects.all()
    serializer_class = DepartmentHeadSerializer

    def list(self, request, *args, **kwargs):
        token = _get_bearer_token(request)
        if not token:
            return Response({"detail": "No token provided"}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            decoded_token = AccessToken(token)
        except Exception as e:
            return Response({"detail": "Invalid token", "error": str(e)}, status=status.HTTP_401_UNAUTHORIZED)

        if decoded_token.get("role") != "department_head":
            return Response({"detail": "Forbidden - token role mismatch", "token_role": decoded_token.get("role")}, status=status.HTTP_403_FORBIDDEN)

        return super().list(request, *args, **kwargs)

class DepartmentHeadDetailView(generics.RetrieveUpdateDestroyAPIView):
    authentication_classes = [LegacyJWTAuthentication]
    permission_classes = []
    queryset = DepartmentHead.objects.all()
    serializer_class = DepartmentHeadSerializer

    def retrieve(self, request, *args, **kwargs):
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

class StudentLoginView(APIView):
    throttle_classes = [LoginRateThrottle]
    authentication_classes = [LegacyJWTAuthentication]
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
        except Exception as e:
            # guaranteed visibility in the runserver terminal
            print("OTP SEND FAILED (student):", repr(e))
            logger.exception("Failed to send OTP email (student) to %s", user.email)
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
    authentication_classes = [LegacyJWTAuthentication]
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
        except Exception as e:
            # guaranteed visibility in the runserver terminal
            print("OTP SEND FAILED (student):", repr(e))
            # full stack trace in logs
            logger.exception("Failed to send OTP email to %s", user.email)
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
    authentication_classes = [LegacyJWTAuthentication]
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
        except Exception as e:
            # guaranteed visibility in the runserver terminal
            print("OTP SEND FAILED (student):", repr(e))
            # full stack trace in logs
            logger.exception("Failed to send OTP email to %s", user.email)
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
    authentication_classes = [LegacyJWTAuthentication]
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


class StudentLogoutView(APIView):
    authentication_classes = [LegacyJWTAuthentication]
    permission_classes = []

    def post(self, request):
        user = getattr(request, "user", None)
        if not getattr(user, "is_authenticated", False) or getattr(user, "role", None) != "student":
            return Response({"detail": "Forbidden - token role mismatch"}, status=status.HTTP_403_FORBIDDEN)

        student = getattr(user, "instance", None)
        if not student:
            student_id = getattr(user, "legacy_user_id", None) or getattr(user, "id", None)
            student = Student.objects.filter(id=student_id).first()

        if not student:
            return Response({"detail": "Student not found"}, status=status.HTTP_404_NOT_FOUND)

        _log_student_auth_event(
            student,
            action="Student Logout",
            message="Student logged out successfully.",
            request=request,
        )
        return Response({"detail": "Student logout recorded."}, status=status.HTTP_200_OK)

class FacultyChangePasswordView(APIView):
    authentication_classes = [LegacyJWTAuthentication]
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


class FacultyLogoutView(APIView):
    authentication_classes = [LegacyJWTAuthentication]
    permission_classes = []

    def post(self, request):
        user = getattr(request, "user", None)
        if not getattr(user, "is_authenticated", False) or getattr(user, "role", None) != "faculty":
            return Response({"detail": "Forbidden - token role mismatch"}, status=status.HTTP_403_FORBIDDEN)

        faculty = getattr(user, "instance", None)
        if not faculty:
            faculty_id = getattr(user, "legacy_user_id", None) or getattr(user, "id", None)
            faculty = Faculty.objects.filter(id=faculty_id).first()

        if not faculty:
            return Response({"detail": "Faculty not found"}, status=status.HTTP_404_NOT_FOUND)

        _log_faculty_auth_event(
            faculty,
            action="Faculty Logout",
            message="Faculty logged out successfully.",
            request=request,
        )
        return Response({"detail": "Faculty logout recorded."}, status=status.HTTP_200_OK)

class StudentMeView(APIView):
    authentication_classes = [LegacyJWTAuthentication]
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

            approved = ClassroomEnrollment.objects.filter(
                student=student, approved=True
            ).select_related("classroom", "classroom__faculty")

            pending = ClassroomEnrollment.objects.filter(
                student=student, approved=False
            ).select_related("classroom", "classroom__faculty")

            # Get ModuleEvaluationForm content type for feedback lookup
            module_eval_ct = ContentType.objects.get_for_model(ModuleEvaluationForm)
            instructor_eval_ct = ContentType.objects.get_for_model(InstructorEvaluationForm)

            classrooms = []
            for e in approved:
                # Check if student has submitted feedback for this classroom
                module_feedback_exists = FeedbackResponse.objects.filter(
                    student=student,
                    form_content_type=module_eval_ct,
                    form_object_id__in=ModuleEvaluationForm.objects.filter(
                        classroom=e.classroom
                    ).values_list('id', flat=True)
                ).exists()

                instructor_feedback_exists = FeedbackResponse.objects.filter(
                    student=student,
                    form_content_type=instructor_eval_ct,
                    form_object_id__in=InstructorEvaluationForm.objects.filter(
                        classroom=e.classroom
                    ).values_list('id', flat=True)
                ).exists()

                # Mark as completed only if both module and instructor feedback are submitted
                is_completed = module_feedback_exists and instructor_feedback_exists

                classrooms.append({
                    "id": e.classroom.id,
                    "classroom_code": e.classroom.classroom_code,
                    "subject_code": e.classroom.subject_code,
                    "module_name": e.classroom.module_name,
                    "program": e.classroom.program,
                    "block": e.classroom.block,
                    "instructor": f"{e.classroom.faculty.firstname} {e.classroom.faculty.lastname}",
                    "schedule": e.classroom.schedule or "TBA",
                    "room": e.classroom.room or "TBA",
                    "students_count": ClassroomEnrollment.objects.filter(
                        classroom=e.classroom, approved=True
                    ).count(),
                    "evaluation_completed": is_completed,
                })

            applications = [
                {
                    "enrollment_id": e.id,
                    "classroom_code": e.classroom.classroom_code,
                    "subject_code": e.classroom.subject_code,
                    "module_name": e.classroom.module_name,
                    "program": e.classroom.program,
                    "block": e.classroom.block,
                    "instructor": f"{e.classroom.faculty.firstname} {e.classroom.faculty.lastname}",
                    "requested_at": e.requested_at,
                    "status": "Pending",
                }
                for e in pending
            ]

            return Response({
                "student": {
                    "id": student.id,
                    "student_number": student.student_number,
                    "email": student.email,
                    "firstname": student.firstname,
                    "lastname": student.lastname,
                    "program": student.program,
                    "year_level": student.year_level,
                },
                "classrooms": classrooms,
                "applications": applications,
                "stats": {
                    "total_classes": len(classrooms),
                    "pending_applications": len(applications),
                },
            }, status=status.HTTP_200_OK)

        except Student.DoesNotExist:
            return Response({"detail": "Student not found"}, status=status.HTTP_404_NOT_FOUND)


class FacultyModulesView(APIView):
    """Return modules assigned to the logged-in faculty along with basic evaluation stats."""
    authentication_classes = [LegacyJWTAuthentication]
    permission_classes = []

    def get(self, request):
        token = _get_bearer_token(request)
        if not token:
            return Response({"detail": "No token provided"}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            decoded = AccessToken(token)
        except Exception:
            return Response({"detail": "Invalid token"}, status=status.HTTP_401_UNAUTHORIZED)

        if decoded.get("role") != "faculty":
            return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        faculty_id = decoded.get("legacy_user_id") or decoded.get("user_id") or decoded.get("sub")
        if not faculty_id:
            return Response({"detail": "Invalid token payload"}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            faculty = Faculty.objects.get(id=faculty_id)
        except Faculty.DoesNotExist:
            return Response({"detail": "Faculty not found"}, status=status.HTTP_404_NOT_FOUND)

        classes = Classroom.objects.filter(faculty_id=faculty_id)
        results = []
        from django.contrib.contenttypes.models import ContentType
        mef_ct = ContentType.objects.get_for_model(ModuleEvaluationForm)

        for c in classes:
            subject_code = str(getattr(c, "subject_code", "") or "").strip()
            mod = Module.objects.filter(
                subject_code__iexact=subject_code,
                department=faculty.department,
            ).first() if subject_code else None
            # Resolve by classroom to avoid mixing forms from other faculty with the same subject code.
            mef = ModuleEvaluationForm.objects.filter(classroom=c).first()
            if not mef and subject_code:
                mef = ModuleEvaluationForm.objects.filter(
                    classroom__faculty_id=faculty_id,
                    subject_code__iexact=subject_code,
                ).first()
            responses_count = 0
            average_rating = None
            if mef:
                qs = FeedbackResponse.objects.filter(form_content_type=mef_ct, form_object_id=mef.id)
                responses_count = qs.count()
                # compute simple average across numeric ratings if present
                try:
                    total = 0
                    cnt = 0
                    for fr in qs:
                        if isinstance(fr.responses, list):
                            for item in fr.responses:
                                try:
                                    r = float(item.get('rating'))
                                except Exception:
                                    r = None
                                if r is not None:
                                    total += r
                                    cnt += 1
                    average_rating = (total / cnt) if cnt > 0 else None
                except Exception:
                    average_rating = None

            student_count = ClassroomEnrollment.objects.filter(
                classroom=c, approved=True
            ).count()
            
            results.append({
                'classroom_id': c.id,
                'module_id': getattr(mod, 'id', None),
                'subject_code': subject_code or getattr(mod, 'subject_code', None),
                'module_name': getattr(c, 'module_name', None) or getattr(mod, 'module_name', None),
                'department': getattr(mod, 'department', getattr(faculty, 'department', None)),
                'semester': getattr(c, 'semester', None) or getattr(mod, 'semester', None),
                'academic_year': getattr(mod, 'academic_year', None),
                'schedule': getattr(c, 'schedule', None),
                'room': getattr(c, 'room', None),
                'evaluation_form_id': mef.id if mef else None,
                'responses_count': responses_count,
                'average_rating': average_rating,
                'block': getattr(c, 'block', None),
                'program': getattr(c, 'program', None),
                'year_level': getattr(c, 'year_level', None),
                "classroom_code": c.classroom_code,
                "enrolled_students": student_count,
            })

        return Response(results, status=status.HTTP_200_OK)
    
class EvaluationFormListCreateView(generics.ListCreateAPIView):
    authentication_classes = [LegacyJWTAuthentication]
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
    authentication_classes = [LegacyJWTAuthentication]
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
    authentication_classes = [LegacyJWTAuthentication]
    permission_classes = []
    queryset = ModuleEvaluationForm.objects.all()
    serializer_class = ModuleEvaluationFormSerializer

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = self.get_serializer(page, many=True, context={"request": request})
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(qs, many=True, context={"request": request})
        return Response(serializer.data)

    def get_queryset(self):
        # base restriction – only active forms
        queryset = ModuleEvaluationForm.objects.filter(status="Active")
        token = _get_bearer_token(self.request)
        if not token:
            return queryset.none()
        try:
            decoded = AccessToken(token)
        except Exception:
            return queryset.none()

        role = decoded.get("role")
        if role == "student":
            student_id = decoded.get("legacy_user_id")
            if student_id:
                student = Student.objects.filter(id=student_id).first()
                if student:
                    # use the classroom enrolments rather than the old JSON field
                    codes = (
                        ClassroomEnrollment.objects
                        .filter(student=student, approved=True)
                        .values_list("classroom__subject_code", flat=True)
                    )
                    if codes:
                        queryset = queryset.filter(subject_code__in=codes)
                        # make student available to serializers as before
                        try:
                            self.request.user = SimpleNamespace(student=student)
                        except Exception:
                            pass
        elif role == "faculty":
            fac_id = decoded.get("legacy_user_id") or decoded.get("user_id") or decoded.get("sub")
            if fac_id:
                queryset = queryset.filter(classroom__faculty_id=fac_id)
        elif role == "department_head":
            hid = decoded.get("legacy_user_id") or decoded.get("user_id") or decoded.get("sub")
            head = DepartmentHead.objects.filter(id=hid).first()
            if head:
                queryset = queryset.filter(classroom__faculty__department=head.department)

        return queryset

    def create(self, request, *args, **kwargs):
        token = _get_bearer_token(request)
        if not token:
            return Response({"detail": "No token provided"}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            decoded = AccessToken(token)
        except Exception:
            return Response({"detail": "Invalid token"}, status=status.HTTP_401_UNAUTHORIZED)
        if decoded.get("role") != "faculty":
            return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        request.user = None
        response = super().create(request, *args, **kwargs)

        if response.status_code == status.HTTP_201_CREATED:
            try:
                decoded = AccessToken(_get_bearer_token(request))
                fac_id = decoded.get("legacy_user_id") or decoded.get("user_id")
                faculty = Faculty.objects.filter(id=fac_id).first()
                faculty_name = f"{faculty.firstname} {faculty.lastname}".strip() if faculty else "Faculty"
            except Exception:
                faculty_name = "Faculty"

            AuditLog.objects.create(
                user=faculty_name,
                role="Faculty",
                action="Created Module Evaluation Form",
                category="FORM MANAGEMENT",
                status="Success",
                message=f"Faculty created module evaluation form: {response.data.get('subject_code')} (classroom: {response.data.get('classroom')})",
                ip=request.META.get("REMOTE_ADDR", "Unknown"),
            )

        return response

class ModuleEvaluationFormDetailView(generics.RetrieveUpdateDestroyAPIView):
    authentication_classes = [LegacyJWTAuthentication]
    permission_classes = []
    queryset = ModuleEvaluationForm.objects.all()
    serializer_class = ModuleEvaluationFormSerializer

    def get_object(self):
        obj = super().get_object()
        token = _get_bearer_token(self.request)
        if not token:
            raise exceptions.NotAuthenticated()

        try:
            decoded = AccessToken(token)
        except Exception:
            raise exceptions.NotAuthenticated()

        role = decoded.get("role")
        # department head may see any form in their department
        if role == "department_head":
            hid = decoded.get("legacy_user_id") or decoded.get("user_id") or decoded.get("sub")
            head = DepartmentHead.objects.filter(id=hid).first()
            if head and obj.classroom.faculty.department == head.department:
                return obj

        # faculty may see forms for their own classrooms
        if role == "faculty":
            fac_id = decoded.get("legacy_user_id") or decoded.get("user_id") or decoded.get("sub")
            if fac_id and obj.classroom.faculty_id == fac_id:
                return obj

        # students may see forms for classes they are enrolled in
        if role == "student":
            sid = decoded.get("legacy_user_id")
            if sid and ClassroomEnrollment.objects.filter(
                student_id=sid, classroom=obj.classroom, approved=True
            ).exists():
                return obj

        raise exceptions.PermissionDenied()

    def perform_update(self, serializer):
        # same logging code you already have
        token = _get_bearer_token(self.request)
        if token:
            try:
                decoded = AccessToken(token)
                if decoded.get("role") == "department_head":
                    hid = decoded.get("legacy_user_id")
                    if hid:
                        head = DepartmentHead.objects.filter(id=hid).first()
                        if head:
                            self.request.user = head
            except:
                pass

        old = self.get_object()
        super().perform_update(serializer)
        new = serializer.instance
        user_name = "System"
        if hasattr(self.request, "user") and self.request.user:
            first_name = getattr(self.request.user, "firstname", "")
            last_name = getattr(self.request.user, "lastname", "")
            email = getattr(self.request.user, "email", "")
            username = getattr(self.request.user, "username", "")
            user_name = (
                f"{first_name} {last_name}".strip()
                or email
                or username
                or "Depthead User"
            )
        AuditLog.objects.create(
            user=user_name,
            role="Depthead",
            action="Updated Module Evaluation Form",
            category="FORM MANAGEMENT",
            status="Success",
            message=f"Updated module form: {getattr(new, 'subject_code', 'Unknown')}",
            ip=self.request.META.get("REMOTE_ADDR", "Unknown"),
        )

    def perform_destroy(self, instance):
        user_name = "System"
        if hasattr(self.request, "user") and self.request.user:
            first_name = getattr(self.request.user, "firstname", "")
            last_name = getattr(self.request.user, "lastname", "")
            email = getattr(self.request.user, "email", "")
            username = getattr(self.request.user, "username", "")
            user_name = (
                f"{first_name} {last_name}".strip()
                or email
                or username
                or "Depthead User"
            )
        with transaction.atomic():
            delete_summary = _delete_connected_feedback_for_form(instance)
            super().perform_destroy(instance)
            AuditLog.objects.create(
                user=user_name,
                role="Depthead",
                action="Deleted Module Evaluation Form",
                category="FORM MANAGEMENT",
                status="Success",
                message=(
                    f"Deleted module form: {getattr(instance, 'subject_code', 'Unknown')} "
                    f"(removed {delete_summary['responses_deleted']} feedback submission(s))"
                ),
                ip=self.request.META.get("REMOTE_ADDR", "Unknown"),
            )


class InstructorEvaluationFormListCreateView(generics.ListCreateAPIView):
    authentication_classes = [LegacyJWTAuthentication]
    permission_classes = []
    queryset = InstructorEvaluationForm.objects.all()
    serializer_class = InstructorEvaluationFormSerializer

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = self.get_serializer(page, many=True, context={"request": request})
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(qs, many=True, context={"request": request})
        return Response(serializer.data)

    def get_queryset(self):
        queryset = InstructorEvaluationForm.objects.all()
        token = _get_bearer_token(self.request)
        if not token:
            return queryset.none()
        try:
            decoded = AccessToken(token)
        except Exception:
            return queryset.none()

        role = decoded.get("role")
        if role == "faculty":
            fac_id = decoded.get("legacy_user_id") or decoded.get("user_id") or decoded.get("sub")
            if fac_id:
                queryset = queryset.filter(classroom__faculty_id=fac_id)
        elif role == "department_head":
            hid = decoded.get("legacy_user_id") or decoded.get("user_id") or decoded.get("sub")
            head = DepartmentHead.objects.filter(id=hid).first()
            if head:
                queryset = queryset.filter(classroom__faculty__department=head.department)
        elif role == "student":
            student_id = decoded.get("legacy_user_id")
            if student_id:
                student = Student.objects.filter(id=student_id).first()
                if student:

                    codes = (
                        ClassroomEnrollment.objects
                        .filter(student=student, approved=True)
                        .values_list("classroom__subject_code", flat=True)
                    )
                    if codes:
                        queryset = queryset.filter(
                            classroom__subject_code__in=codes
                        )

                    try:
                        self.request.user = SimpleNamespace(student=student)
                    except Exception:
                        pass

        return queryset

    def create(self, request, *args, **kwargs):
        token = _get_bearer_token(request)
        if not token:
            return Response({"detail": "No token provided"}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            decoded = AccessToken(token)
        except Exception:
            return Response({"detail": "Invalid token"}, status=status.HTTP_401_UNAUTHORIZED)
        if decoded.get("role") != "faculty":
            return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        request.user = None
        response = super().create(request, *args, **kwargs)
        if response.status_code == status.HTTP_201_CREATED:
            form_data = response.data
            user_name = "System"
            AuditLog.objects.create(
                user=user_name,
                role="Depthead",
                action="Created Instructor Evaluation Form",
                category="FORM MANAGEMENT",
                status="Success",
                message=f'Created new instructor form: {form_data.get("title", "Unknown")}',
                ip=request.META.get("REMOTE_ADDR", "Unknown"),
            )
        return response
class InstructorEvaluationFormDetailView(generics.RetrieveUpdateDestroyAPIView):
    authentication_classes = [LegacyJWTAuthentication]
    permission_classes = []
    queryset = InstructorEvaluationForm.objects.all()
    serializer_class = InstructorEvaluationFormSerializer

    def get_object(self):
        obj = super().get_object()
        token = _get_bearer_token(self.request)
        if not token:
            raise exceptions.NotAuthenticated()

        try:
            decoded = AccessToken(token)
        except Exception:
            raise exceptions.NotAuthenticated()

        role = decoded.get("role")
        if role == "department_head":
            hid = decoded.get("legacy_user_id") or decoded.get("user_id") or decoded.get("sub")
            head = DepartmentHead.objects.filter(id=hid).first()
            if head and obj.classroom.faculty.department == head.department:
                return obj

        if role == "faculty":
            fac_id = decoded.get("legacy_user_id") or decoded.get("user_id") or decoded.get("sub")
            if fac_id and obj.classroom.faculty_id == fac_id:
                return obj

        if role == "student":
            sid = decoded.get("legacy_user_id")
            if sid and ClassroomEnrollment.objects.filter(
                student_id=sid, classroom=obj.classroom, approved=True
            ).exists():
                return obj

        raise exceptions.PermissionDenied()

    def perform_update(self, serializer):
        token = _get_bearer_token(self.request)
        if token:
            try:
                decoded = AccessToken(token)
                if decoded.get("role") == "department_head":
                    hid = decoded.get("legacy_user_id")
                    if hid:
                        head = DepartmentHead.objects.filter(id=hid).first()
                        if head:
                            self.request.user = head
            except:
                pass

        old = self.get_object()
        super().perform_update(serializer)
        new = serializer.instance
        user_name = "System"
        if hasattr(self.request, "user") and self.request.user:
            user_name = (
                f"{self.request.user.firstname} {self.request.user.lastname}"
                .strip() or self.request.user.email or "Depthead User"
            )
        AuditLog.objects.create(
            user=user_name,
            role="Depthead",
            action="Updated Instructor Evaluation Form",
            category="FORM MANAGEMENT",
            status="Success",
            message=f"Updated instructor form: {getattr(new, 'instructor_name', 'Unknown')}",
            ip=self.request.META.get("REMOTE_ADDR", "Unknown"),
        )

    def perform_destroy(self, instance):
        user_name = "System"
        if hasattr(self.request, "user") and self.request.user:
            user_name = (
                f"{self.request.user.firstname} {self.request.user.lastname}"
                .strip() or self.request.user.email or "Depthead User"
            )
        with transaction.atomic():
            delete_summary = _delete_connected_feedback_for_form(instance)
            super().perform_destroy(instance)
            AuditLog.objects.create(
                user=user_name,
                role="Depthead",
                action="Deleted Instructor Evaluation Form",
                category="FORM MANAGEMENT",
                status="Success",
                message=(
                    f"Deleted instructor form: {getattr(instance, 'instructor_name', 'Unknown')} "
                    f"(removed {delete_summary['responses_deleted']} feedback submission(s))"
                ),
                ip=self.request.META.get("REMOTE_ADDR", "Unknown"),
            )

class StudentBulkImportView(APIView):
    """Bulk import students from CSV file"""
    authentication_classes = [LegacyJWTAuthentication]
    permission_classes = []

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

        # Check if file is provided. Be permissive about where the uploaded
        # file may appear: depending on middleware/parsers it can be in
        # `request.FILES`, `request._request.FILES` (the underlying Django
        # HttpRequest), or in DRF's `request.data`.
        content_type = request.META.get('CONTENT_TYPE') or request.content_type if hasattr(request, 'content_type') else request.META.get('CONTENT_TYPE')
        # Helpful debug info (will appear in logs)
        try:
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"Bulk import upload content-type: {content_type}")
            logger.info(f"request.FILES keys: {list(getattr(request, 'FILES', {}).keys())}")
            # underlying Django request
            underlying = getattr(request, '_request', None)
            if underlying is not None:
                logger.info(f"underlying request.FILES keys: {list(getattr(underlying, 'FILES', {}).keys())}")
        except Exception:
            pass

        csv_file = None
        # Prefer request.FILES (DRF wraps Django request but exposes FILES)
        if getattr(request, 'FILES', None) and 'file' in request.FILES:
            csv_file = request.FILES['file']
        else:
            # Try the underlying Django HttpRequest
            underlying = getattr(request, '_request', None)
            if underlying and getattr(underlying, 'FILES', None) and 'file' in underlying.FILES:
                csv_file = underlying.FILES['file']
            else:
                # As a last resort, DRF may have put the file in `request.data`
                try:
                    df = getattr(request, 'data', {})
                    if df and 'file' in df:
                        csv_file = df.get('file')
                except Exception:
                    csv_file = None

        if not csv_file:
            return Response({"detail": "No file provided"}, status=status.HTTP_400_BAD_REQUEST)

        # NEW: strict CSV validation (type + size + required header columns)
        try:
            _text, csv_reader = validate_uploaded_csv(
                csv_file,
                max_bytes=getattr(settings, "MAX_BULK_CSV_SIZE_BYTES", 2 * 1024 * 1024),
                required_columns={"email", "firstname", "lastname", "student_id"},
            )
        except DRFValidationError as exc:
            return Response({"detail": "Invalid CSV upload", "errors": exc.detail}, status=status.HTTP_400_BAD_REQUEST)

        # Parse CSV and create students
        try:
            created_count = 0
            errors = []

            for row_num, row in enumerate(csv_reader, start=2):
                try:
                    # Validate required fields (stop this row if missing)
                    required_fields = ["email", "firstname", "lastname", "student_id"]
                    missing = [f for f in required_fields if not str(row.get(f, "") or "").strip()]
                    if missing:
                        errors.append(f"Row {row_num}: Missing required field(s): {', '.join(missing)}")
                        continue

                    email = row["email"].strip()
                    student_id = row["student_id"].strip()

                    # Check duplicates
                    if Student.objects.filter(email=email).exists():
                        errors.append(f"Row {row_num}: Student with email '{email}' already exists")
                        continue

                    if Student.objects.filter(student_number=student_id).exists():
                        errors.append(f"Row {row_num}: Student with ID '{student_id}' already exists")
                        continue

                    # Parse enrolled_subjects (detailed format with code|description|instructor)
                    # Format: CODE|Description|Instructor;CODE2|Description2|Instructor2
                    # Also accepts simple format: CODE;CODE2;CODE3
                    raw_subjects = str(row.get("enrolled_subjects", "") or "").strip()
                    subjects_list = []
                    if raw_subjects:
                        for subject_entry in raw_subjects.split(";"):
                            subject_entry = subject_entry.strip()
                            if not subject_entry:
                                continue
                            
                            # Check if it contains pipes (detailed format)
                            if "|" in subject_entry:
                                parts = [p.strip() for p in subject_entry.split("|")]
                                if len(parts) >= 1:
                                    subjects_list.append({
                                        "code": parts[0],
                                        "description": parts[1] if len(parts) > 1 else "",
                                        "instructor_name": parts[2] if len(parts) > 2 else "",
                                    })
                            else:
                                # Simple format - just code
                                subjects_list.append({
                                    "code": subject_entry,
                                    "description": "",
                                    "instructor_name": "",
                                })
                    
                    block_val = str(row.get("block_section", "") or "").strip()

                    # Parse year level
                    year_val = str(row.get("year_level", "") or "").strip()
                    try:
                        year_val_parsed = int(year_val) if year_val else None
                    except ValueError:
                        year_val_parsed = None

                    # Parse birthdate
                    birthdate_str = str(row.get("birthdate", "") or "").strip()
                    birthdate = None
                    if birthdate_str:
                        from datetime import datetime
                        try:
                            birthdate = datetime.strptime(birthdate_str, "%Y-%m-%d").date()
                        except ValueError:
                            errors.append(f"Row {row_num}: Invalid birthdate format. Use YYYY-MM-DD")
                            continue

                    firstname = validate_plain_text(row["firstname"].strip(), field_name="firstname")
                    middlename = validate_plain_text(str(row.get("middlename", "") or "").strip(), field_name="middlename")
                    lastname = validate_plain_text(row["lastname"].strip(), field_name="lastname")
                    department = validate_plain_text(str(row.get("department", "") or "").strip(), field_name="department")
                    program = validate_plain_text(str(row.get("course", "") or "").strip(), field_name="course")
                    block_val = validate_plain_text(str(row.get("block_section", "") or "").strip(), field_name="block_section")

                    # Generate password from birthdate using same logic as StudentSerializer
                    if birthdate:
                        first_two = firstname[:2].upper() if firstname else ""
                        middle_two = middlename[:2].upper() if middlename else ""
                        last_two = lastname[:2].upper() if lastname else ""
                        name_key = f"{first_two}{middle_two}{last_two}"
                        month_year = f"{birthdate.month}{birthdate.year}"
                        password = f"{name_key}{month_year}"
                    else:
                        # Default password if no birthdate
                        password = "ChangeMe123!"

                    student = Student(
                        email=email,
                        firstname=firstname,
                        middlename=middlename if middlename else None,
                        lastname=lastname,
                        student_number=student_id,
                        department=department,
                        program=program,
                        year_level=year_val_parsed,
                        enrolled_subjects=subjects_list,
                        block_section=block_val or None,
                        birthdate=birthdate,
                        must_change_password=True,
                    )
                    student.set_password(password)
                    student.save()
                    created_count += 1

                except Exception as e:
                    errors.append(f"Row {row_num}: {str(e)}")

            # ...existing audit log + response...
            user_name = f"{dept_head.firstname} {dept_head.lastname}".strip() or dept_head.email or "Depthead User"
            AuditLog.objects.create(
                user=user_name,
                role="Depthead",
                action="Bulk Import Students",
                category="USER MANAGEMENT",
                status="Success" if created_count > 0 else "Failed",
                message=f"Imported {created_count} new student records from CSV file. {len(errors)} errors encountered.",
                ip=request.META.get("REMOTE_ADDR", "Unknown"),
            )

            return Response(
                {
                    "message": f"Successfully imported {created_count} students",
                    "created_count": created_count,
                    "errors": errors[:10],
                },
                status=status.HTTP_201_CREATED,
            )

        except Exception as e:
            return Response({"detail": f"Error processing CSV: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

class FacultyBulkImportView(APIView):
    """Bulk import faculty from CSV file"""
    authentication_classes = [LegacyJWTAuthentication]
    permission_classes = []

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
        if "file" not in request.FILES:
            return Response({"detail": "No file provided"}, status=status.HTTP_400_BAD_REQUEST)

        csv_file = request.FILES["file"]

        # NEW: strict CSV validation (type + size + required header columns)
        try:
            _text, csv_reader = validate_uploaded_csv(
                csv_file,
                max_bytes=getattr(settings, "MAX_BULK_CSV_SIZE_BYTES", 2 * 1024 * 1024),
                required_columns={"email", "firstname", "lastname"},
            )
        except DRFValidationError as exc:
            return Response({"detail": "Invalid CSV upload", "errors": exc.detail}, status=status.HTTP_400_BAD_REQUEST)

        # Parse CSV and create faculty
        try:
            created_count = 0
            errors = []

            for row_num, row in enumerate(csv_reader, start=2):
                try:
                    required_fields = ["email", "firstname", "lastname"]
                    missing = [f for f in required_fields if not str(row.get(f, "") or "").strip()]
                    if missing:
                        errors.append(f"Row {row_num}: Missing required field(s): {', '.join(missing)}")
                        continue

                    email = row["email"].strip()

                    if Faculty.objects.filter(email=email).exists():
                        errors.append(f"Row {row_num}: Faculty with email '{email}' already exists")
                        continue

                    firstname = validate_plain_text(row["firstname"].strip(), field_name="firstname")
                    lastname = validate_plain_text(row["lastname"].strip(), field_name="lastname")
                    middlename = validate_plain_text(str(row.get("middlename", "") or "").strip(), field_name="middlename")
                    department = validate_plain_text(str(row.get("department", "") or "").strip(), field_name="department")
                    contact_number = str(row.get("contact_number", "") or "").strip()
                    birthdate_str = str(row.get("birthdate", "") or "").strip()
                    
                    # Parse birthdate if provided
                    birthdate = None
                    if birthdate_str:
                        from datetime import datetime
                        try:
                            birthdate = datetime.strptime(birthdate_str, "%Y-%m-%d").date()
                        except ValueError:
                            errors.append(f"Row {row_num}: Invalid birthdate format. Use YYYY-MM-DD")
                            continue

                    Faculty.objects.create(
                        email=email,
                        firstname=firstname,
                        middlename=middlename if middlename else None,
                        lastname=lastname,
                        department=department if department else None,
                        contact_number=contact_number if contact_number else None,
                        birthdate=birthdate,
                        must_change_password=True,
                    )
                    created_count += 1

                except Exception as e:
                    errors.append(f"Row {row_num}: {str(e)}")

            user_name = f"{dept_head.firstname} {dept_head.lastname}".strip() or dept_head.email or "Depthead User"
            AuditLog.objects.create(
                user=user_name,
                role="Depthead",
                action="Bulk Import Faculty",
                category="USER MANAGEMENT",
                status="Success" if created_count > 0 else "Failed",
                message=f"Imported {created_count} new faculty records from CSV file. {len(errors)} errors encountered.",
                ip=request.META.get("REMOTE_ADDR", "Unknown"),
            )

            return Response(
                {
                    "message": f"Successfully imported {created_count} faculty members",
                    "created_count": created_count,
                    "errors": errors[:10],
                },
                status=status.HTTP_201_CREATED,
            )

        except Exception as e:
            return Response({"detail": f"Error processing CSV: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)


class AuditLogListView(generics.ListCreateAPIView):
    authentication_classes = [LegacyJWTAuthentication]
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
    authentication_classes = [LegacyJWTAuthentication]
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

        response_items = serializer.validated_data.get('responses', [])
        comment_items = [
            {
                "question": item.get('question_code') or item.get('question_id'),
                "text": item.get('comment') or '',
            }
            for item in response_items
            if str(item.get('comment') or '').strip()
        ]

        violations = _run_feedback_ai_security_checks(comment_items)

        if violations:
            return Response(
                {
                    "detail": "Submission blocked: comment failed AI security checks (restricted theme, prompt-injection, or poisoning pattern).",
                    "violations": violations,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        obj = serializer.save(
            student=student,
            ip_address=request.META.get("REMOTE_ADDR", "Unknown"),
        )

        # THEN create the audit log
        student_name = f"{student.firstname} {student.lastname}".strip() if student else "Anonymous"
        form_type_label = str(request.data.get("form_type") or "").capitalize()
        form_label = _get_feedback_form_label(getattr(obj, "form", None), fallback=str(request.data.get("form_id") or ""))

        AuditLog.objects.create(
            user=student_name,
            role="Student",
            action="Submitted Feedback",
            category="FEEDBACK",
            status="Success",
            message=f"Student submitted {form_type_label} evaluation feedback for {form_label}",
            ip=request.META.get("REMOTE_ADDR", "Unknown"),
        )

        response_data = self.get_serializer(obj).data
        headers = self.get_success_headers(response_data)
        return Response(response_data, status=status.HTTP_201_CREATED, headers=headers)
    
class FeedbackResponseListView(generics.ListAPIView):
    authentication_classes = [LegacyJWTAuthentication]
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
        role = decoded.get("role")
        actor_id = decoded.get("legacy_user_id") or decoded.get("user_id") or decoded.get("sub")
        if not actor_id:
            return Response({"detail": "Invalid token payload"}, status=status.HTTP_401_UNAUTHORIZED)

        if role == "department_head":
            try:
                DepartmentHead.objects.get(id=actor_id)
            except DepartmentHead.DoesNotExist:
                return Response({"detail": "Department head not found"}, status=status.HTTP_404_NOT_FOUND)
            qs = FeedbackResponse.objects.all()
        elif role == "faculty":
            try:
                Faculty.objects.get(id=actor_id)
            except Faculty.DoesNotExist:
                return Response({"detail": "Faculty not found"}, status=status.HTTP_404_NOT_FOUND)

            module_ct = ContentType.objects.get_for_model(ModuleEvaluationForm)
            faculty_form_ids = ModuleEvaluationForm.objects.filter(
                classroom__faculty_id=actor_id
            ).values_list("id", flat=True)

            qs = FeedbackResponse.objects.filter(
                form_content_type=module_ct,
                form_object_id__in=faculty_form_ids,
            )
        else:
            return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        form = request.query_params.get('form')
        if form:
            qs = qs.filter(form_object_id=form)
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)

class StudentFeedbackHistoryView(generics.ListAPIView):
    """
    GET /api/feedback/history/  – return the logged‑in student's submissions.
    """
    authentication_classes = [LegacyJWTAuthentication]
    permission_classes = []
    serializer_class = FeedbackResponseSerializer

    def get_queryset(self):
        token = _get_bearer_token(self.request)
        if not token:
            return FeedbackResponse.objects.none()

        try:
            decoded = AccessToken(token)
        except Exception:
            return FeedbackResponse.objects.none()

        if decoded.get("role") != "student":
            return FeedbackResponse.objects.none()

        student_id = (
            decoded.get("legacy_user_id")
            or decoded.get("user_id")
            or decoded.get("sub")
        )
        if not student_id:
            return FeedbackResponse.objects.none()

        return FeedbackResponse.objects.filter(student_id=student_id).order_by(
            "-submitted_at"
        )
        
class SentimentTestView(APIView):
    throttle_classes = []
    authentication_classes = [LegacyJWTAuthentication]
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


class FeedbackThemeCheckView(APIView):
    authentication_classes = [LegacyJWTAuthentication]
    permission_classes = []

    def post(self, request):
        comments = request.data.get("comments")
        if comments is None:
            text = request.data.get("text")
            comments = [text] if text is not None else []

        if not isinstance(comments, list):
            return Response({"detail": '"comments" must be a list'}, status=status.HTTP_400_BAD_REQUEST)

        violations = _run_feedback_ai_security_checks(comments)

        detail = ""
        if violations:
            detail = "Some comments cannot be submitted yet. Please use respectful, original feedback and remove any instruction-like wording."

        return Response(
            {
                "blocked": len(violations) > 0,
                "detail": detail,
                "violations": violations,
            },
            status=status.HTTP_200_OK,
        )


class ModuleRecommendationView(APIView):
    throttle_classes = [AIRequestRateThrottle]
    authentication_classes = [LegacyJWTAuthentication]
    permission_classes = []

    def post(self, request):
        token = _get_bearer_token(request)
        if not token:
            return Response({"detail": "No token provided"}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            decoded = AccessToken(token)
        except Exception:
            return Response({"detail": "Invalid token"}, status=status.HTTP_401_UNAUTHORIZED)

        if decoded.get("role") != "department_head":
            return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        module_name = str(request.data.get("module_name") or "").strip()
        average_rating = request.data.get("average_rating")
        responses_count = request.data.get("responses_count")
        rating_breakdown = request.data.get("rating_breakdown") or {}
        category_rates = request.data.get("category_rates") or []
        comments = request.data.get("comments") or []

        if not module_name:
            return Response({"detail": "module_name is required"}, status=status.HTTP_400_BAD_REQUEST)

        if not isinstance(comments, list):
            comments = []

        comments = [str(c).strip() for c in comments if str(c).strip()][:8]

        sentiment_counts = {"positive": 0, "neutral": 0, "negative": 0, "unknown": 0}
        for comment in comments:
            try:
                label = str(predict_sentiment(comment)).lower().strip()
            except Exception:
                label = "unknown"

            if label not in sentiment_counts:
                label = "unknown"

            sentiment_counts[label] += 1

        try:
            avg_text = f"{float(average_rating):.2f}" if average_rating is not None else "N/A"
        except Exception:
            avg_text = "N/A"

        try:
            count_text = str(int(responses_count))
        except Exception:
            count_text = "0"

        rb = {
            "very_good": int(rating_breakdown.get("very_good", 0) or 0),
            "good": int(rating_breakdown.get("good", 0) or 0),
            "fair": int(rating_breakdown.get("fair", 0) or 0),
            "poor": int(rating_breakdown.get("poor", 0) or 0),
        }

        category_lines = []
        if isinstance(category_rates, list):
            for item in category_rates:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                try:
                    rating = float(item.get("rating"))
                    rating_text = f"{rating:.2f}"
                except Exception:
                    rating_text = str(item.get("rating") or "N/A")
                category_lines.append(f"- {name}: {rating_text}")

        category_text_block = "\n".join(category_lines) if category_lines else "- No category rates provided"

        def build_fallback(reason=None):
            reason_text = f"\nReason: {reason}" if reason else ""
            concerns = rb["fair"] + rb["poor"]
            strengths = rb["very_good"] + rb["good"]
            if concerns > strengths:
                trend_line = "- Overall trend indicates more concerns than strengths in current responses."
            elif concerns == strengths and concerns > 0:
                trend_line = "- Overall trend is mixed, with strengths and concerns appearing in similar volume."
            else:
                trend_line = "- Overall trend is generally positive, with strengths outweighing concerns."

            return (
                "1) Key Findings\n"
                f"- Module: {module_name}\n"
                f"- Average Rating: {avg_text} (Responses: {count_text})\n"
                f"- Rating Breakdown: Very Good={rb['very_good']}, Good={rb['good']}, Fair={rb['fair']}, Poor={rb['poor']}\n"
                "- Category Rates:\n"
                f"{category_text_block}\n"
                f"- Comment Sentiment Summary: Positive={sentiment_counts['positive']}, Neutral={sentiment_counts['neutral']}, Negative={sentiment_counts['negative']}, Unknown={sentiment_counts['unknown']}\n"
                f"{trend_line}\n\n"
                "2) Priority Actions (next 30 days)\n"
                "- Instructor Effectiveness: run targeted coaching on clarity, preparedness, and classroom engagement.\n"
                "- Course Content & Materials: refine slides/handouts and align tasks with stated learning outcomes.\n"
                "- Assessment & Feedback: standardize rubrics and speed up feedback turnaround.\n"
                "- Learning Environment: address classroom/resource pain points raised by negative sentiment trends.\n\n"
                "3) Longer-Term Improvements\n"
                "- Track section-level results per cycle (Instructor, Content, Assessment, Environment) and compare trends term-over-term.\n"
                "- Build a module action plan with measurable targets per section and monthly review checkpoints.\n"
                "- Replicate strategies from high-performing modules and mentor lower-performing teaching teams."
                f"{reason_text}"
            )

        api_key = os.getenv("GEMINI_API_KEY", "").strip().strip('"').strip("'")
        if not api_key:
            api_key = os.getenv("GOOGLE_API_KEY", "").strip().strip('"').strip("'")
        if not api_key:
            fallback = build_fallback(None)
            return Response({"recommendation": fallback, "source": "local"}, status=200)

        prompt = (
            "You are an academic quality assistant. "
            "Given the module evaluation summary, provide concise recommendations for department heads. "
            "The recommendations MUST align with the module evaluation question sections used by students: "
            "(A) Instructor Effectiveness, (B) Course Content & Materials, (C) Assessment & Feedback, "
            "(D) Learning Environment, and (E) Overall Rating & Comments. "
            "Output rules are strict and must be followed exactly:\n"
            "- Output must contain ONLY these 3 sections in this order:\n"
            "1) Key Findings\n"
            "2) Priority Actions (next 30 days)\n"
            "3) Longer-Term Improvements\n"
            "- Under each section, provide 3 to 5 short bullet points.\n"
            "- Do NOT include any introduction sentence, disclaimer, conclusion, or extra section.\n"
            "- Do NOT use markdown emphasis like **bold** or code formatting.\n"
            "- Use plain text only.\n\n"
            "Important privacy rule: Do not request, infer, output, or reference any student-identifying data or raw student comments. "
            "Use only the aggregate statistics provided below.\n\n"
            f"Module: {module_name}\n"
            f"Average Rating: {avg_text}\n"
            f"Total Responses: {count_text}\n"
            f"Rating Breakdown: Very Good={rb['very_good']}, Good={rb['good']}, Fair={rb['fair']}, Poor={rb['poor']}\n"
            "Category Rates:\n"
            f"{category_text_block}\n"
            f"Comment Sentiment Summary (from sentiment_service): Positive={sentiment_counts['positive']}, Neutral={sentiment_counts['neutral']}, Negative={sentiment_counts['negative']}, Unknown={sentiment_counts['unknown']}\n"
            "Use both rating aggregates and sentiment summary when producing recommendations. "
            "Do not give generic recommendations that are unrelated to those five evaluation sections."
        )

        model_candidates = []
        payload = {
            "contents": [
                {
                    "parts": [{"text": prompt}]
                }
            ]
        }

        def _request_with_retry(method, url, **kwargs):
            last_exc = None
            for _ in range(2):
                try:
                    return requests.request(method=method, url=url, **kwargs)
                except requests.exceptions.RequestException as exc:
                    last_exc = exc
                    continue
            if last_exc:
                raise last_exc
            raise requests.RequestException("Gemini request failed")

        try:
            # Discover models available to this API key for generateContent.
            models_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
            models_resp = _request_with_retry("GET", models_url, timeout=20)
            if models_resp.ok:
                models_data = models_resp.json()
                for model in (models_data.get("models") or []):
                    if not isinstance(model, dict):
                        continue
                    name = str(model.get("name") or "")
                    methods = model.get("supportedGenerationMethods") or []
                    if "generateContent" not in methods:
                        continue
                    if not name:
                        continue
                    # API expects model id without "models/" prefix.
                    model_id = name.split("/", 1)[1] if name.startswith("models/") else name
                    if model_id and model_id not in model_candidates:
                        model_candidates.append(model_id)

            # Safety fallback if list call fails or returns no compatible models.
            if not model_candidates:
                model_candidates = [
                    "gemini-2.0-flash",
                    "gemini-2.0-flash-lite",
                    "gemini-2.5-flash",
                ]

            last_status = None
            last_reason = "Gemini request failed"

            for model_id in model_candidates:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={api_key}"
                resp = _request_with_retry("POST", url, json=payload, timeout=20)

                if not resp.ok:
                    last_status = resp.status_code
                    body_snippet = (resp.text or "").strip().replace("\n", " ")[:240]
                    last_reason = f"Model {model_id} failed with status {resp.status_code}" + (f": {body_snippet}" if body_snippet else "")
                    continue

                data = resp.json()
                text = ""
                candidates = data.get("candidates") or []
                if candidates:
                    parts = (((candidates[0] or {}).get("content") or {}).get("parts") or [])
                    text = "\n".join(str(p.get("text", "")).strip() for p in parts if isinstance(p, dict)).strip()

                if text:
                    return Response(
                        {
                            "recommendation": text,
                            "source": "gemini",
                            "model": model_id,
                            "sentiment_summary": sentiment_counts,
                        },
                        status=status.HTTP_200_OK,
                    )

                last_reason = f"Model {model_id} returned empty content"

            fallback = build_fallback(last_reason)
            return Response(
                {
                    "recommendation": fallback,
                    "source": "fallback",
                    "sentiment_summary": sentiment_counts,
                    "detail": "Gemini request failed",
                    "status": last_status,
                },
                status=status.HTTP_200_OK,
            )
        except requests.RequestException as exc:
            error_text = str(exc).strip() or exc.__class__.__name__
            error_text = error_text.replace("\n", " ")[:240]
            logger.warning("Gemini request exception: %s", error_text, exc_info=True)
            fallback = build_fallback(f"Unable to reach Gemini service ({error_text})")
            return Response(
                {
                    "recommendation": fallback,
                    "source": "fallback",
                    "sentiment_summary": sentiment_counts,
                    "detail": f"Unable to reach Gemini service: {error_text}",
                },
                status=status.HTTP_200_OK,
            )
    
class SendOTPView(APIView):
    throttle_classes = [LoginRateThrottle]
    authentication_classes = [LegacyJWTAuthentication]
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
    authentication_classes = [LegacyJWTAuthentication]
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

                # NEW: enforce password expiry before issuing tokens
                if is_password_expired(user):
                    user.must_change_password = True
                    user.save(update_fields=["must_change_password"])
                    return Response(
                        {
                            "detail": "Password expired. Please change your password.",
                            "password_expired": True,
                            "must_change_password": True,
                            "user_type": "student",
                            "email": user.email,
                        },
                        status=status.HTTP_403_FORBIDDEN,
                    )
                
                tokens = _issue_jwt_pair("student", user.id)
                _log_student_auth_event(
                    user,
                    action="Student Login",
                    message="Student logged in successfully via OTP verification.",
                    request=request,
                )
                return Response(
                    {
                        "detail": "OTP verified",
                        "access": tokens["access"],
                        "refresh": tokens["refresh"],
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

                # NEW: enforce password expiry before issuing tokens
                if is_password_expired(user):
                    user.must_change_password = True
                    user.save(update_fields=["must_change_password"])
                    return Response(
                        {
                            "detail": "Password expired. Please change your password.",
                            "password_expired": True,
                            "must_change_password": True,
                            "user_type": "faculty",
                            "email": user.email,
                        },
                        status=status.HTTP_403_FORBIDDEN,
                    )
                
                tokens = _issue_jwt_pair("faculty", user.id)
                _log_faculty_auth_event(
                    user,
                    action="Faculty Login",
                    message="Faculty logged in successfully via OTP verification.",
                    request=request,
                )
                return Response(
                    {
                        "detail": "OTP verified",
                        "access": tokens["access"],
                        "refresh": tokens["refresh"],
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

                # NEW: enforce password expiry before issuing tokens
                if is_password_expired(user):
                    user.must_change_password = True
                    user.save(update_fields=["must_change_password"])
                    return Response(
                        {
                            "detail": "Password expired. Please change your password.",
                            "password_expired": True,
                            "must_change_password": True,
                            "user_type": "department_head",
                            "email": user.email,
                        },
                        status=status.HTTP_403_FORBIDDEN,
                    )
                
                tokens = _issue_jwt_pair("department_head", user.id)
                return Response(
                    {
                        "detail": "OTP verified",
                        "access": tokens["access"],
                        "refresh": tokens["refresh"],
                        "user_type": "department_head",
                        "id": user.id,
                        "email": user.email,
                        "firstname": user.firstname,
                        "lastname": user.lastname,
                    },
                    status=status.HTTP_200_OK,
                )

            return Response({"detail": "Unsupported role"}, status=status.HTTP_400_BAD_REQUEST)

        # For RESET_PASSWORD: return a simple verification result used by password-reset flow
        if record.purpose == EmailOTP.Purpose.RESET_PASSWORD:
            return Response({
                "detail": "OTP verified for password reset",
                "pending_token": record.pending_token,
                "email": record.email,
                "role": record.role,
            }, status=status.HTTP_200_OK)

        return Response({"detail": "Unsupported purpose"}, status=status.HTTP_400_BAD_REQUEST)


class PasswordResetSendView(APIView):
    throttle_classes = [LoginRateThrottle]
    authentication_classes = [LegacyJWTAuthentication]
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
            ttl_minutes=15,
            purpose=EmailOTP.Purpose.RESET_PASSWORD,
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


class PasswordResetConfirmView(APIView):
    authentication_classes = [LegacyJWTAuthentication]
    permission_classes = []

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        pending_token = serializer.validated_data["pending_token"].strip()
        new_password = serializer.validated_data["new_password"]

        record = EmailOTP.objects.filter(pending_token=pending_token, purpose=EmailOTP.Purpose.RESET_PASSWORD).order_by("-created_at").first()
        if not record:
            return Response({"detail": "Invalid pending token"}, status=status.HTTP_400_BAD_REQUEST)

        if record.is_expired():
            return Response({"detail": "OTP expired"}, status=status.HTTP_400_BAD_REQUEST)

        # Determine user by role
        user = None
        if record.role == EmailOTP.Role.STUDENT:
            user = Student.objects.filter(email__iexact=record.email).first()
        elif record.role == EmailOTP.Role.FACULTY:
            user = Faculty.objects.filter(email__iexact=record.email).first()
        elif record.role == EmailOTP.Role.DEPARTMENT_HEAD:
            user = DepartmentHead.objects.filter(email__iexact=record.email).first()

        if not user:
            return Response({"detail": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        # Set new password
        user.set_password(new_password)
        user.must_change_password = False
        user.save()

        record.is_used = True
        record.save(update_fields=["is_used"])

        return Response({"detail": "Password updated"}, status=status.HTTP_200_OK)

@method_decorator(ensure_csrf_cookie, name="dispatch")
class CSRFCookieView(APIView):
    authentication_classes = [LegacyJWTAuthentication]
    permission_classes = []

    def get(self, request):
        return Response({"detail": "CSRF cookie set"})

class ClassroomListCreateView(generics.ListCreateAPIView):
    authentication_classes = [LegacyJWTAuthentication]
    permission_classes = []
    queryset = Classroom.objects.all()
    serializer_class = ClassroomSerializer

    def get_queryset(self):
        token = _get_bearer_token(self.request)
        if not token:
            return Classroom.objects.none()
        try:
            decoded = AccessToken(token)
        except Exception:
            return Classroom.objects.none()
        role = decoded.get("role")
        if role == "faculty":
            fac_id = decoded.get("legacy_user_id") or decoded.get("user_id") or decoded.get("sub")
            return Classroom.objects.filter(faculty_id=fac_id)
        if role == "department_head":
            # optionally allow heads to see all classes in their department
            head_id = decoded.get("legacy_user_id") or decoded.get("user_id") or decoded.get("sub")
            try:
                head = DepartmentHead.objects.get(id=head_id)
                return Classroom.objects.filter(faculty__department=head.department)
            except DepartmentHead.DoesNotExist:
                pass
        return Classroom.objects.none()

    def create(self, request, *args, **kwargs):
        token = _get_bearer_token(request)
        if not token:
            return Response({"detail": "No token provided"}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            decoded = AccessToken(token)
        except Exception:
            return Response({"detail": "Invalid token"}, status=status.HTTP_401_UNAUTHORIZED)
        if decoded.get("role") != "faculty":
            return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)
        fac_id = decoded.get("legacy_user_id") or decoded.get("user_id") or decoded.get("sub")
        if not fac_id:
            return Response({"detail": "Invalid token payload"}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            faculty = Faculty.objects.get(id=fac_id)
        except Faculty.DoesNotExist:
            return Response({"detail": "Faculty not found"}, status=status.HTTP_404_NOT_FOUND)

        request._faculty = faculty
        request.user = faculty
        response = super().create(request, *args, **kwargs)

        if response.status_code == status.HTTP_201_CREATED:
            faculty_name = f"{faculty.firstname} {faculty.lastname}".strip()
            AuditLog.objects.create(
                user=faculty_name,
                role="Faculty",
                action="Created Classroom",
                category="CLASSROOM MANAGEMENT",
                status="Success",
                message=f"Faculty created classroom: {response.data.get('classroom_code')} ({response.data.get('subject_code')})",
                ip=request.META.get("REMOTE_ADDR", "Unknown"),
            )

        return response

    def perform_create(self, serializer):
        faculty = getattr(self.request, "_faculty", None)
        if faculty is None:
            raise ValidationError("Internal error: faculty missing")
        serializer.save(faculty=faculty)


class ClassroomDetailView(generics.RetrieveUpdateDestroyAPIView):
    authentication_classes = [LegacyJWTAuthentication]
    permission_classes = []
    queryset = Classroom.objects.all()
    serializer_class = ClassroomSerializer

    def get_object(self):
        token = _get_bearer_token(self.request)
        if not token:
            raise exceptions.NotAuthenticated()

        try:
            decoded = AccessToken(token)
        except Exception:
            raise exceptions.NotAuthenticated()

        if decoded.get("role") != "faculty":
            raise exceptions.PermissionDenied()

        fac_id = decoded.get("legacy_user_id") or decoded.get("user_id") or decoded.get("sub")
        if not fac_id:
            raise exceptions.NotAuthenticated()

        try:
            classroom = super().get_object()
        except Classroom.DoesNotExist:
            raise exceptions.NotFound()

        if str(classroom.faculty_id) != str(fac_id):
            raise exceptions.PermissionDenied()

        faculty = Faculty.objects.filter(id=fac_id).first()
        if faculty:
            self.request.user = faculty

        return classroom

class ClassroomJoinView(APIView):
    authentication_classes = [LegacyJWTAuthentication]
    permission_classes = []

    def post(self, request):
        token = _get_bearer_token(request)
        if not token:
            return Response({"detail": "No token provided"}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            decoded = AccessToken(token)
        except Exception:
            return Response({"detail": "Invalid token"}, status=status.HTTP_401_UNAUTHORIZED)
        if decoded.get("role") != "student":
            return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)
        student_id = decoded.get("legacy_user_id") or decoded.get("user_id") or decoded.get("sub")
        if not student_id:
            return DRFValidationError({"detail": "Invalid token payload"}, status=status.HTTP_401_UNAUTHORIZED)
        code = str(request.data.get("classroom_code") or "").strip()
        if not code:
            raise DRFValidationError({"classroom_code": "This field is required."})
        try:
            classroom = Classroom.objects.get(classroom_code=code)
        except Classroom.DoesNotExist:
            return Response({"detail": "Classroom not found"}, status=status.HTTP_404_NOT_FOUND)
        enrollment, created = ClassroomEnrollment.objects.get_or_create(
            student_id=student_id,
            classroom=classroom,
            defaults={"approved": False},
        )
        if not created:
            return Response({"detail": "Join request already submitted"}, status=status.HTTP_400_BAD_REQUEST)
        
        student = Student.objects.filter(id=student_id).first()
        student_name = f"{student.firstname} {student.lastname}".strip() if student else str(student_id)

        AuditLog.objects.create(
            user=student_name,
            role="Student",
            action="Joined Classroom",
            category="ENROLLMENT",
            status="Success",
            message=f"Student joined classroom: {classroom.classroom_code} ({classroom.subject_code})",
            ip=request.META.get("REMOTE_ADDR", "Unknown"),
        )
        
        serializer = ClassroomEnrollmentSerializer(enrollment)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

class StudentLeaveClassroomView(APIView):
    authentication_classes = [LegacyJWTAuthentication]
    permission_classes = []

    def post(self, request):
        token = _get_bearer_token(request)
        if not token:
            return Response({"detail": "No token provided"},
                            status=status.HTTP_401_UNAUTHORIZED)
        try:
            decoded = AccessToken(token)
        except Exception:
            return Response({"detail": "Invalid token"},
                            status=status.HTTP_401_UNAUTHORIZED)
        if decoded.get("role") != "student":
            return Response({"detail": "Forbidden"},
                            status=status.HTTP_403_FORBIDDEN)

        student_id = decoded.get("legacy_user_id") or decoded.get("user_id") or decoded.get("sub")
        if not student_id:
            return Response({"detail": "Invalid token payload"},
                            status=status.HTTP_401_UNAUTHORIZED)

        enrollment_id = request.data.get("enrollment_id")
        code = str(request.data.get("classroom_code") or "").strip()

        try:
            if enrollment_id:
                enr = ClassroomEnrollment.objects.get(id=enrollment_id, student_id=student_id)
            elif code:
                cls = Classroom.objects.get(classroom_code=code)
                enr = ClassroomEnrollment.objects.get(student_id=student_id, classroom=cls)
            else:
                return Response({"detail": "enrollment_id or classroom_code required"},
                                status=status.HTTP_400_BAD_REQUEST)
        except (Classroom.DoesNotExist, ClassroomEnrollment.DoesNotExist):
            return Response({"detail": "Enrollment not found"},
                            status=status.HTTP_404_NOT_FOUND)

        student = Student.objects.filter(id=student_id).first()
        student_name = f"{student.firstname} {student.lastname}".strip() if student else str(student_id)
        classroom_code = enr.classroom.classroom_code if enr.classroom else "Unknown"
        subject_code = enr.classroom.subject_code if enr.classroom else "Unknown"

        enr.delete()

        AuditLog.objects.create(
            user=student_name,
            role="Student",
            action="Left Classroom",
            category="ENROLLMENT",
            status="Success",
            message=f"Student left classroom: {classroom_code} ({subject_code})",
            ip=request.META.get("REMOTE_ADDR", "Unknown"),
        )
        return Response({"detail": "Left classroom"}, status=status.HTTP_200_OK)

class FacultyPendingEnrollmentsView(APIView):
    authentication_classes = [LegacyJWTAuthentication]
    permission_classes = []

    def get(self, request):
        token = _get_bearer_token(request)
        if not token:
            return Response({"detail": "No token provided"}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            decoded = AccessToken(token)
        except Exception:
            return Response({"detail": "Invalid token"}, status=status.HTTP_401_UNAUTHORIZED)
        if decoded.get("role") != "faculty":
            return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)
        fac_id = decoded.get("legacy_user_id") or decoded.get("user_id") or decoded.get("sub")
        enrollments = ClassroomEnrollment.objects.filter(
            classroom__faculty_id=fac_id, approved=False
        ).select_related("student", "classroom")
        serializer = ClassroomEnrollmentSerializer(enrollments, many=True)
        return Response(serializer.data)


class FacultyEnrollmentHistoryView(APIView):
    authentication_classes = [LegacyJWTAuthentication]
    permission_classes = []

    def get(self, request):
        token = _get_bearer_token(request)
        if not token:
            return Response({"detail": "No token provided"}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            decoded = AccessToken(token)
        except Exception:
            return Response({"detail": "Invalid token"}, status=status.HTTP_401_UNAUTHORIZED)
        if decoded.get("role") != "faculty":
            return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        fac_id = decoded.get("legacy_user_id") or decoded.get("user_id") or decoded.get("sub")
        enrollments = ClassroomEnrollment.objects.filter(
            classroom__faculty_id=fac_id,
            approved=True,
        ).select_related("student", "classroom").order_by("-approved_at", "-requested_at")

        serializer = ClassroomEnrollmentSerializer(enrollments, many=True)
        return Response(serializer.data)


class FacultyApproveEnrollmentView(APIView):
    authentication_classes = [LegacyJWTAuthentication]
    permission_classes = []

    def post(self, request):
        token = _get_bearer_token(request)
        if not token:
            return Response({"detail": "No token provided"},
                            status=status.HTTP_401_UNAUTHORIZED)
        try:
            decoded = AccessToken(token)
        except Exception:
            return Response({"detail": "Invalid token"},
                            status=status.HTTP_401_UNAUTHORIZED)
        if decoded.get("role") != "faculty":
            return Response({"detail": "Forbidden"},
                            status=status.HTTP_403_FORBIDDEN)

        fac_id = decoded.get("legacy_user_id") or decoded.get("user_id") or decoded.get("sub")
        enrollment_id = request.data.get("enrollment_id")
        if not enrollment_id:
            return Response({"detail": "enrollment_id required"},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            enr = ClassroomEnrollment.objects.select_related("classroom").get(id=enrollment_id)
        except ClassroomEnrollment.DoesNotExist:
            return Response({"detail": "Enrollment not found"},
                            status=status.HTTP_404_NOT_FOUND)

        if enr.classroom.faculty_id != fac_id:
            return Response({"detail": "Not your classroom"},
                            status=status.HTTP_403_FORBIDDEN)

        # DECISION ALREADY MADE?
        if enr.approved and not request.data.get("approve", True):
            return Response({"detail": "Cannot reject an already‑approved enrollment"},
                            status=status.HTTP_400_BAD_REQUEST)
        if enr.approved and request.data.get("approve", True):
            return Response({"detail": "Enrollment already approved"},
                            status=status.HTTP_400_BAD_REQUEST)

        approve = request.data.get("approve", True)

        faculty = Faculty.objects.filter(id=fac_id).first()
        faculty_name = f"{faculty.firstname} {faculty.lastname}".strip() if faculty else str(fac_id)
        student_name = f"{enr.student.firstname} {enr.student.lastname}".strip() if enr.student else "Unknown Student"
        classroom_code = enr.classroom.classroom_code if enr.classroom else "Unknown"

        if not approve:
            enr.delete()
            AuditLog.objects.create(
                user=faculty_name,
                role="Faculty",
                action="Rejected Enrollment",
                category="ENROLLMENT",
                status="Success",
                message=f"Faculty rejected enrollment of {student_name} from classroom: {classroom_code}",
                ip=request.META.get("REMOTE_ADDR", "Unknown"),
            )
            return Response({"detail": "Enrollment rejected"}, status=status.HTTP_200_OK)

        enr.approved = True
        enr.approved_at = timezone.now()
        enr.save(update_fields=["approved", "approved_at"])

        AuditLog.objects.create(
            user=faculty_name,
            role="Faculty",
            action="Approved Enrollment",
            category="ENROLLMENT",
            status="Success",
            message=f"Faculty approved enrollment of {student_name} in classroom: {classroom_code}",
            ip=request.META.get("REMOTE_ADDR", "Unknown"),
        )

        return Response(ClassroomEnrollmentSerializer(enr).data)

class ProgramListCreateView(generics.ListCreateAPIView):
    authentication_classes = [LegacyJWTAuthentication]
    permission_classes = []
    queryset = Program.objects.all()
    serializer_class = ProgramSerializer

    def get_queryset(self):
        token = _get_bearer_token(self.request)
        if not token:
            return Program.objects.none()
        try:
            decoded = AccessToken(token)
        except Exception:
            return Program.objects.none()
        if decoded.get("role") == "department_head":
            hid = decoded.get("legacy_user_id") or decoded.get("user_id") or decoded.get("sub")
            head = DepartmentHead.objects.filter(id=hid).first()
            if head:
                return Program.objects.filter(department=head.department)
        return Program.objects.none()

    def create(self, request, *args, **kwargs):
        token = _get_bearer_token(request)
        if not token:
            return Response({"detail": "No token provided"}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            decoded = AccessToken(token)
        except Exception:
            return Response({"detail": "Invalid token"}, status=status.HTTP_401_UNAUTHORIZED)
        if decoded.get("role") != "department_head":
            return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)
        hid = decoded.get("legacy_user_id") or decoded.get("user_id") or decoded.get("sub")
        head = DepartmentHead.objects.filter(id=hid).first()
        if not head:
            return Response({"detail": "Dept head not found"}, status=status.HTTP_404_NOT_FOUND)

        # stash the DepartmentHead for perform_create()
        request._dept_head = head
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        head = getattr(self.request, "_dept_head", None)
        if head is None:
            raise ValidationError("Internal error: department head missing")
        serializer.save(department_head=head, department=head.department)

    def perform_update(self, serializer):
        serializer.save()

class ModuleListCreateView(generics.ListCreateAPIView):
    authentication_classes = [LegacyJWTAuthentication]
    permission_classes = []
    queryset = Module.objects.all()
    serializer_class = ModuleSerializer

    def get_queryset(self):
        token = _get_bearer_token(self.request)
        if not token:
            return Module.objects.none()
        try:
            decoded = AccessToken(token)
        except Exception:
            return Module.objects.none()

        role = decoded.get("role")
        uid = decoded.get("legacy_user_id") or decoded.get("user_id") or decoded.get("sub")
        queryset = Module.objects.none()

        if role == "department_head":
            head = DepartmentHead.objects.filter(id=uid).first()
            if head:
                queryset = Module.objects.filter(department=head.department)

        elif role == "faculty":
            faculty = Faculty.objects.filter(id=uid).first()
            if faculty and faculty.department:
                queryset = Module.objects.filter(department=faculty.department)

        if not queryset.exists():
            return queryset

        year_level = str(self.request.query_params.get("year_level", "") or "").strip()
        semester = str(self.request.query_params.get("semester", "") or "").strip()

        if year_level:
            queryset = queryset.filter(year_level__icontains=year_level)

        if semester:
            sem_key = semester.strip().lower()
            if sem_key in {"1st sem", "1st semester", "first sem", "first semester"}:
                queryset = queryset.filter(
                    Q(semester__iexact="1st Sem") |
                    Q(semester__iexact="1st Semester") |
                    Q(semester__iexact="First Sem") |
                    Q(semester__iexact="First Semester")
                )
            elif sem_key in {"2nd sem", "2nd semester", "second sem", "second semester"}:
                queryset = queryset.filter(
                    Q(semester__iexact="2nd Sem") |
                    Q(semester__iexact="2nd Semester") |
                    Q(semester__iexact="Second Sem") |
                    Q(semester__iexact="Second Semester")
                )
            elif sem_key == "summer":
                queryset = queryset.filter(semester__iexact="Summer")
            else:
                queryset = queryset.filter(semester__icontains=semester)

        return queryset

    def create(self, request, *args, **kwargs):
        token = _get_bearer_token(request)
        if not token:
            return Response({"detail": "No token provided"}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            decoded = AccessToken(token)
        except Exception:
            return Response({"detail": "Invalid token"}, status=status.HTTP_401_UNAUTHORIZED)
        if decoded.get("role") != "department_head":
            return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        hid = decoded.get("legacy_user_id") or decoded.get("user_id") or decoded.get("sub")
        head = DepartmentHead.objects.filter(id=hid).first()
        if not head:
            return Response({"detail": "Dept head not found"}, status=status.HTTP_404_NOT_FOUND)

        # stash the head for use in perform_create
        request._dept_head = head
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        head = getattr(self.request, "_dept_head", None)
        if head is None:
            raise DRFValidationError("Internal error: department head missing")
        serializer.save(department_head=head, department=head.department)


class ModuleDetailView(generics.RetrieveUpdateDestroyAPIView):
    authentication_classes = [LegacyJWTAuthentication]
    permission_classes = []
    queryset = Module.objects.all()
    serializer_class = ModuleSerializer

    def get_queryset(self):
        token = _get_bearer_token(self.request)
        if not token:
            return Module.objects.none()
        try:
            decoded = AccessToken(token)
        except Exception:
            return Module.objects.none()

        role = decoded.get("role")
        uid = decoded.get("legacy_user_id") or decoded.get("user_id") or decoded.get("sub")

        if role == "department_head":
            head = DepartmentHead.objects.filter(id=uid).first()
            if head:
                return Module.objects.filter(department=head.department)
            return Module.objects.none()

        if role == "faculty":
            faculty = Faculty.objects.filter(id=uid).first()
            if faculty and faculty.department:
                return Module.objects.filter(department=faculty.department)

        return Module.objects.none()

    def update(self, request, *args, **kwargs):
        token = _get_bearer_token(request)
        if not token:
            return Response({"detail": "No token provided"}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            decoded = AccessToken(token)
        except Exception:
            return Response({"detail": "Invalid token"}, status=status.HTTP_401_UNAUTHORIZED)
        if decoded.get("role") != "department_head":
            return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        token = _get_bearer_token(request)
        if not token:
            return Response({"detail": "No token provided"}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            decoded = AccessToken(token)
        except Exception:
            return Response({"detail": "Invalid token"}, status=status.HTTP_401_UNAUTHORIZED)
        if decoded.get("role") != "department_head":
            return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)

    def perform_update(self, serializer):
        instance = self.get_object()
        serializer.save(department_head=instance.department_head, department=instance.department)

class BlockListCreateView(generics.ListCreateAPIView):
    authentication_classes = [LegacyJWTAuthentication]
    permission_classes = []
    queryset = Block.objects.all()
    serializer_class = BlockSerializer

    def get_queryset(self):
        token = _get_bearer_token(self.request)
        if not token:
            return Block.objects.none()
        try:
            decoded = AccessToken(token)
        except Exception:
            return Block.objects.none()

        role = decoded.get("role")
        uid = decoded.get("legacy_user_id") or decoded.get("user_id") or decoded.get("sub")
        queryset = Block.objects.none()

        if role == "department_head":
            head = DepartmentHead.objects.filter(id=uid).first()
            if head:
                queryset = Block.objects.filter(program__department=head.department)

        elif role == "faculty":
            faculty = Faculty.objects.filter(id=uid).first()
            if faculty and faculty.department:
                queryset = Block.objects.filter(program__department=faculty.department)

        if not queryset.exists():
            return queryset

        year_level = str(self.request.query_params.get("year_level", "") or "").strip()
        if year_level:
            queryset = queryset.filter(year_level__icontains=year_level)

        return queryset

    def create(self, request, *args, **kwargs):
        token = _get_bearer_token(request)
        if not token:
            return Response({"detail": "No token provided"}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            decoded = AccessToken(token)
        except Exception:
            return Response({"detail": "Invalid token"}, status=status.HTTP_401_UNAUTHORIZED)
        if decoded.get("role") != "department_head":
            return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)
        hid = decoded.get("legacy_user_id") or decoded.get("user_id") or decoded.get("sub")
        head = DepartmentHead.objects.filter(id=hid).first()
        if not head:
            return Response({"detail": "Department head not found"}, status=status.HTTP_404_NOT_FOUND)
        request.user = head
        return super().create(request, *args, **kwargs)


class BlockDetailView(generics.RetrieveUpdateDestroyAPIView):
    authentication_classes = [LegacyJWTAuthentication]
    permission_classes = []
    queryset = Block.objects.all()
    serializer_class = BlockSerializer

    def get_queryset(self):
        token = _get_bearer_token(self.request)
        if not token:
            return Block.objects.none()
        try:
            decoded = AccessToken(token)
        except Exception:
            return Block.objects.none()

        role = decoded.get("role")
        uid = decoded.get("legacy_user_id") or decoded.get("user_id") or decoded.get("sub")

        if role == "department_head":
            head = DepartmentHead.objects.filter(id=uid).first()
            if head:
                return Block.objects.filter(program__department=head.department)
            return Block.objects.none()

        if role == "faculty":
            faculty = Faculty.objects.filter(id=uid).first()
            if faculty and faculty.department:
                return Block.objects.filter(program__department=faculty.department)

        return Block.objects.none()

    def update(self, request, *args, **kwargs):
        token = _get_bearer_token(request)
        if not token:
            return Response({"detail": "No token provided"}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            decoded = AccessToken(token)
        except Exception:
            return Response({"detail": "Invalid token"}, status=status.HTTP_401_UNAUTHORIZED)
        if decoded.get("role") != "department_head":
            return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        hid = decoded.get("legacy_user_id") or decoded.get("user_id") or decoded.get("sub")
        head = DepartmentHead.objects.filter(id=hid).first()
        if not head:
            return Response({"detail": "Department head not found"}, status=status.HTTP_404_NOT_FOUND)

        request.user = head
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        token = _get_bearer_token(request)
        if not token:
            return Response({"detail": "No token provided"}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            decoded = AccessToken(token)
        except Exception:
            return Response({"detail": "Invalid token"}, status=status.HTTP_401_UNAUTHORIZED)
        if decoded.get("role") != "department_head":
            return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        return super().destroy(request, *args, **kwargs)

class StoreRecommendationHashView(APIView):
    throttle_classes = [AIRequestRateThrottle]
    authentication_classes = [LegacyJWTAuthentication]
    permission_classes = []

    def post(self, request):
        token = _get_bearer_token(request)
        if not token:
            return Response({"detail": "No token provided"}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            decoded = AccessToken(token)
        except Exception:
            return Response({"detail": "Invalid token"}, status=status.HTTP_401_UNAUTHORIZED)

        if decoded.get("role") != "department_head":
            return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        module_name = str(request.data.get("module_name") or "").strip()
        recommendation = str(request.data.get("recommendation") or "").strip()
        average_rating = request.data.get("average_rating")
        responses_count = request.data.get("responses_count")
        rating_breakdown = request.data.get("rating_breakdown") or {}
        sentiment_summary = request.data.get("sentiment_summary") or {}

        if not module_name:
            return Response({"detail": "module_name is required"}, status=status.HTTP_400_BAD_REQUEST)

        if not recommendation:
            return Response({"detail": "recommendation is required"}, status=status.HTTP_400_BAD_REQUEST)

        # Build the payload that will be hashed
        payload = {
            "module_name": module_name,
            "recommendation": recommendation,
            "average_rating": average_rating,
            "responses_count": responses_count,
            "rating_breakdown": rating_breakdown,
            "sentiment_summary": sentiment_summary,
            "generated_at": timezone.now().isoformat(),
        }

        hash_hex = compute_feedback_hash_hex(payload)

        # Check if this exact hash was already stored
        if FeedbackHash.objects.filter(tx_hash=hash_hex).exists():
            return Response(
                {
                    "detail": "This recommendation has already been stored on-chain.",
                    "hash": hash_hex,
                    "already_stored": True,
                },
                status=status.HTTP_200_OK,
            )

        # Store on blockchain
        try:
            tx_hash = store_hash_onchain(hash_hex)
        except Exception as e:
            logger.exception("Failed to store recommendation hash on-chain")
            return Response(
                {"detail": f"Blockchain storage failed: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        dept_head_id = decoded.get("legacy_user_id") or decoded.get("user_id")
        dept_head = DepartmentHead.objects.filter(id=dept_head_id).first()
        user_name = f"{dept_head.firstname} {dept_head.lastname}".strip() if dept_head else "Department Head"

        AuditLog.objects.create(
            user=user_name,
            role="Depthead",
            action="Stored AI Recommendation Hash",
            category="BLOCKCHAIN",
            status="Success",
            message=f"Stored AI recommendation hash for module: {module_name} | tx: {tx_hash}",
            ip=request.META.get("REMOTE_ADDR", "Unknown"),
        )

        return Response(
            {
                "detail": "Recommendation hash stored on-chain successfully.",
                "hash": hash_hex,
                "tx_hash": tx_hash,
                "already_stored": False,
            },
            status=status.HTTP_201_CREATED,
        )
        
class StudentAuditLogListView(generics.ListAPIView):
    authentication_classes = [LegacyJWTAuthentication]
    permission_classes = []
    serializer_class = AuditLogSerializer

    def get_queryset(self):
        token = _get_bearer_token(self.request)
        if not token:
            return AuditLog.objects.none()
        try:
            decoded = AccessToken(token)
        except Exception:
            return AuditLog.objects.none()

        if decoded.get("role") != "student":
            return AuditLog.objects.none()

        student_id = decoded.get("legacy_user_id") or decoded.get("user_id") or decoded.get("sub")
        student = Student.objects.filter(id=student_id).first()
        if not student:
            return AuditLog.objects.none()

        student_name = f"{student.firstname} {student.lastname}".strip()
        return AuditLog.objects.filter(
            role="Student",
            user=student_name,
        ).order_by("-timestamp")


class FacultyAuditLogListView(generics.ListAPIView):
    authentication_classes = [LegacyJWTAuthentication]
    permission_classes = []
    serializer_class = AuditLogSerializer

    def get_queryset(self):
        token = _get_bearer_token(self.request)
        if not token:
            return AuditLog.objects.none()
        try:
            decoded = AccessToken(token)
        except Exception:
            return AuditLog.objects.none()

        if decoded.get("role") != "faculty":
            return AuditLog.objects.none()

        fac_id = decoded.get("legacy_user_id") or decoded.get("user_id") or decoded.get("sub")
        faculty = Faculty.objects.filter(id=fac_id).first()
        if not faculty:
            return AuditLog.objects.none()

        faculty_name = f"{faculty.firstname} {faculty.lastname}".strip()
        return AuditLog.objects.filter(
            role="Faculty",
            user=faculty_name,
        ).order_by("-timestamp")

class ClassroomStudentsView(APIView):
    authentication_classes = [LegacyJWTAuthentication]
    permission_classes = []

    def get(self, request, classroom_id):
        token = _get_bearer_token(request)
        if not token:
            return Response({"detail": "No token provided"}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            decoded = AccessToken(token)
        except Exception:
            return Response({"detail": "Invalid token"}, status=status.HTTP_401_UNAUTHORIZED)

        role = decoded.get("role")
        raw_user_id = decoded.get("legacy_user_id") or decoded.get("user_id") or decoded.get("sub")
        try:
            user_id = int(raw_user_id)
        except (TypeError, ValueError):
            user_id = None
        if not user_id:
            return Response({"detail": "Invalid token payload"}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            classroom = Classroom.objects.get(id=classroom_id)
        except Classroom.DoesNotExist:
            return Response({"detail": "Classroom not found"}, status=status.HTTP_404_NOT_FOUND)

        # Access rules:
        # - faculty: only own classrooms
        # - department head: only classrooms in their department
        # - student: only classrooms where they have an approved enrollment
        if role == "faculty":
            if classroom.faculty_id != user_id:
                return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)
        elif role == "department_head":
            head = DepartmentHead.objects.filter(id=user_id).first()
            if not head or classroom.faculty.department != head.department:
                return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)
        elif role == "student":
            is_enrolled = ClassroomEnrollment.objects.filter(
                classroom=classroom,
                student_id=user_id,
                approved=True,
            ).exists()
            if not is_enrolled:
                return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)
        else:
            return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        enrollments = ClassroomEnrollment.objects.filter(
            classroom=classroom,
            approved=True,
        ).select_related("student")

        data = [
            {
                "enrollment_id": enr.id,
                "student_id": enr.student.id,
                "student_number": enr.student.student_number,
                "firstname": enr.student.firstname,
                "lastname": enr.student.lastname,
                "email": enr.student.email,
                "approved_at": enr.approved_at,
            }
            for enr in enrollments
        ]

        classroom_info = {
            "id": classroom.id,
            "classroom_code": classroom.classroom_code,
            "subject_code": classroom.subject_code,
            "module_name": classroom.module_name,
            "program": classroom.program,
            "block": classroom.block,
            "year_level": classroom.year_level,
            "semester": classroom.semester,
            "academic_year": getattr(classroom, "academic_year", None),
            "schedule": classroom.schedule,
            "room": classroom.room,
            "instructor": (
                f"{classroom.faculty.firstname} {classroom.faculty.lastname}"
                if classroom.faculty else None
            ),
        }

        return Response({
            **classroom_info,
            "total_students": len(data),
            "students": data,
        })