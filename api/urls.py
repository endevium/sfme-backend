from django.urls import path
from . import views

urlpatterns = [
    path("students/", views.StudentListCreateView.as_view(), name="student-list-create"),
    path("students/<int:pk>/", views.StudentDetailView.as_view(), name="student-detail"),
    path("students/login/", views.StudentLoginView.as_view(), name="student-login"),
    path("students/change-password/", views.StudentChangePasswordView.as_view(), name="student-change-password"),
    path("students/me/", views.StudentMeView.as_view(), name="student-me"),

    path("faculty/", views.FacultyListCreateView.as_view(), name="faculty-list-create"),
    path("faculty/<int:pk>/", views.FacultyDetailView.as_view(), name="faculty-detail"),
    path("faculty/login/", views.FacultyLoginView.as_view(), name="faculty-login"),
    path("faculty/change-password/", views.FacultyChangePasswordView.as_view(), name="faculty-change-password"),

    path("department-heads/", views.DepartmentHeadListCreateView.as_view(), name="department-head-list-create"),
    path("department-heads/<int:pk>/", views.DepartmentHeadDetailView.as_view(), name="department-head-detail"),
    path("department-head/login/", views.DepartmentHeadLoginView.as_view(), name="department-head-login"),

    path("evaluation-forms/", views.EvaluationFormListCreateView.as_view(), name="evaluation-form-list-create"),
    path("evaluation-forms/<int:pk>/", views.EvaluationFormDetailView.as_view(), name="evaluation-form-detail"),
    path("module-evaluation-forms/", views.ModuleEvaluationFormListCreateView.as_view(), name="module-evaluation-form-list-create"),
    path("module-evaluation-forms/<int:pk>/", views.ModuleEvaluationFormDetailView.as_view(), name="module-evaluation-form-detail"),
    path("instructor-evaluation-forms/", views.InstructorEvaluationFormListCreateView.as_view(), name="instructor-evaluation-form-list-create"),
    path("instructor-evaluation-forms/<int:pk>/", views.InstructorEvaluationFormDetailView.as_view(), name="instructor-evaluation-form-detail"),

    path("students/bulk-import/", views.StudentBulkImportView.as_view(), name="student-bulk-import"),
    path("faculty/bulk-import/", views.FacultyBulkImportView.as_view(), name="faculty-bulk-import"),

    path("feedback/submit/", views.FeedbackResponseCreateView.as_view(), name="student-submit-feedback"),
    path("feedback/submissions/", views.FeedbackResponseListView.as_view(), name="student-feedback-detail"),

    path("audit-logs/", views.AuditLogListView.as_view(), name="audit-log-list"),

    path("otp/send/", views.SendOTPView.as_view(), name="otp-send"),
    path("otp/verify/", views.VerifyOTPView.as_view(), name="otp-verify"),
]
