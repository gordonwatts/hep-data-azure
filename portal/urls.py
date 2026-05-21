from django.contrib.auth import views as auth_views
from django.urls import path

from .views import (
    PortalLogoutView,
    account_status,
    admin_users,
    approve_user,
    cancel_job,
    clone_job,
    home,
    job_artifact,
    job_detail,
    job_generated_code,
    job_status_partial,
    reject_user,
    submit_job,
)

urlpatterns = [
    path("", home, name="home"),
    path("submit/", submit_job, name="submit"),
    path("jobs/<uuid:submission_id>/", job_detail, name="job-detail"),
    path("jobs/<uuid:submission_id>/status/", job_status_partial, name="job-status"),
    path(
        "jobs/<uuid:submission_id>/generated-code/",
        job_generated_code,
        name="job-generated-code",
    ),
    path("jobs/<uuid:submission_id>/clone/", clone_job, name="job-clone"),
    path("jobs/<uuid:submission_id>/cancel/", cancel_job, name="job-cancel"),
    path(
        "jobs/<uuid:submission_id>/artifacts/<int:artifact_id>/",
        job_artifact,
        name="job-artifact",
    ),
    path(
        "accounts/login/",
        auth_views.LoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path("accounts/logout/", PortalLogoutView.as_view(), name="logout"),
    path("accounts/status/", account_status, name="account-status"),
    path("approvals/users/", admin_users, name="admin-users"),
    path("approvals/users/<int:user_id>/approve/", approve_user, name="approve-user"),
    path("approvals/users/<int:user_id>/reject/", reject_user, name="reject-user"),
]
