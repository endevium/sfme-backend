from django.urls import path
from . import views
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView

urlpatterns = [
    path("students/", views.StudentListCreateView.as_view(), name="student-list-create"),
    path("students/archived/", views.ArchivedStudentListView.as_view(), name="student-archived-list"),
    path("students/<int:pk>/", views.StudentDetailView.as_view(), name="student-detail"),
    path("students/login/", views.StudentLoginView.as_view(), name="student-login"),
    path("students/logout/", views.StudentLogoutView.as_view(), name="student-logout"),
    path("students/change-password/", views.StudentChangePasswordView.as_view(), name="student-change-password"),
    path("students/me/", views.StudentMeView.as_view(), name="student-me"),

    path("faculty/", views.FacultyListCreateView.as_view(), name="faculty-list-create"),
    path("faculty/archived/", views.ArchivedFacultyListView.as_view(), name="faculty-archived-list"),
    path("faculty/<int:pk>/", views.FacultyDetailView.as_view(), name="faculty-detail"),
    path("faculty/modules/", views.FacultyModulesView.as_view(), name="faculty-modules"),
    path("faculty/login/", views.FacultyLoginView.as_view(), name="faculty-login"),
    path("faculty/logout/", views.FacultyLogoutView.as_view(), name="faculty-logout"),
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
    path("feedback/theme-check/", views.FeedbackThemeCheckView.as_view(), name="feedback-theme-check"),
    path("feedback/submissions/", views.FeedbackResponseListView.as_view(), name="student-feedback-detail"),
    path("feedback/history/", views.StudentFeedbackHistoryView.as_view(), name="student-feedback-history"),
    path("ai/recommendation/", views.ModuleRecommendationView.as_view(), name="module-recommendation"),
    path("ai/store-recommendation-hash/", views.StoreRecommendationHashView.as_view(), name="store-recommendation-hash"),
    
    path("audit-logs/", views.AuditLogListView.as_view(), name="audit-log-list"),
    path("audit-logs/faculty/", views.FacultyAuditLogListView.as_view(), name="faculty-audit-log-list"),
    path("audit-logs/students/", views.StudentAuditLogListView.as_view(), name="student-audit-log-list"),

    path("otp/send/", views.SendOTPView.as_view(), name="otp-send"),
    path("otp/verify/", views.VerifyOTPView.as_view(), name="otp-verify"),
    
    path("password-reset/send/", views.PasswordResetSendView.as_view(), name="password-reset-send"),
    path("password-reset/verify/", views.VerifyOTPView.as_view(), name="password-reset-verify"),
    path("password-reset/confirm/", views.PasswordResetConfirmView.as_view(), name="password-reset-confirm"),

    path("classrooms/", views.ClassroomListCreateView.as_view(), name="classroom-list-create"),
    path("classrooms/<int:pk>/", views.ClassroomDetailView.as_view(), name="classroom-detail"),
    path("classrooms/join/", views.ClassroomJoinView.as_view(), name="classroom-join"),
    path("classrooms/leave/", views.StudentLeaveClassroomView.as_view(), name="classroom-leave"),
    path("classrooms/enrollments/pending/", views.FacultyPendingEnrollmentsView.as_view(), name="classroom-enrollments-pending"),
    path("classrooms/enrollments/history/", views.FacultyEnrollmentHistoryView.as_view(), name="classroom-enrollments-history"),
    path("classrooms/enrollments/decision/", views.FacultyApproveEnrollmentView.as_view(), name="classroom-enrollment-decision"),
    path("classrooms/<int:classroom_id>/students/", views.ClassroomStudentsView.as_view(), name="classroom-students",),
    
    path("programs/", views.ProgramListCreateView.as_view(), name="program-list-create"),
    path("modules/", views.ModuleListCreateView.as_view(), name="module-list-create"),
    path("modules/<int:pk>/", views.ModuleDetailView.as_view(), name="module-detail"),
    path("blocks/", views.BlockListCreateView.as_view(), name="block-list-create"),
    path("blocks/<int:pk>/", views.BlockDetailView.as_view(), name="block-detail"),
    
    path("auth/csrf/", views.CSRFCookieView.as_view(), name="csrf_cookie"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("auth/token/verify/", TokenVerifyView.as_view(), name="token_verify"),
]
