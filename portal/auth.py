from __future__ import annotations

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponseForbidden, HttpResponseRedirect
from django.urls import reverse

from portal.models import ApprovalState, UserProfile


def get_user_profile(user) -> UserProfile:
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile


def is_user_approved(user) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_staff or user.is_superuser:
        return True
    return get_user_profile(user).approval_state == ApprovalState.APPROVED


def approval_required(view_func):
    @wraps(view_func)
    @login_required
    def wrapper(request: HttpRequest, *args, **kwargs):
        if is_user_approved(request.user):
            return view_func(request, *args, **kwargs)
        return HttpResponseRedirect(reverse("account-status"))

    return wrapper


def staff_required(view_func):
    @wraps(view_func)
    @login_required
    def wrapper(request: HttpRequest, *args, **kwargs):
        if request.user.is_staff or request.user.is_superuser:
            return view_func(request, *args, **kwargs)
        return HttpResponseForbidden("Staff access required")

    return wrapper


def ensure_user_profile(user) -> UserProfile:
    return get_user_profile(user)
