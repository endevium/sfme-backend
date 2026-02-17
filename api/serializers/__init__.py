from .AuditLog import AuditLogSerializer
from .DepartmentHead import DepartmentHeadSerializer
from .DepartmentHeadLogin import DepartmentHeadLoginSerializer
from .EvaluationForm import EvaluationFormSerializer
from .Faculty import FacultySerializer
from .FacultyChangePassword import FacultyChangePasswordSerializer
from .FacultyLogin import FacultyLoginSerializer
from .InstructorEvaluationForm import InstructorEvaluationFormSerializer
from .ModuleEvaluationForm import ModuleEvaluationFormSerializer
from .Student import StudentSerializer
from .StudentChangePassword import StudentChangePasswordSerializer
from .StudentLogin import StudentLoginSerializer
from .OTP import SendOTPSerializer, VerifyOTPSerializer

__all__ = [
    "AuditLogSerializer",
    "DepartmentHeadSerializer",
    "DepartmentHeadLoginSerializer",
    "EvaluationFormSerializer",
    "FacultySerializer",
    "FacultyChangePasswordSerializer",
    "FacultyLoginSerializer",
    "InstructorEvaluationFormSerializer",
    "ModuleEvaluationFormSerializer",
    "StudentSerializer",
    "StudentChangePasswordSerializer",
    "StudentLoginSerializer",
    "SendOTPSerializer",
    "VerifyOTPSerializer"
]