from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from portal.auth import ensure_user_profile
from portal.models import ApprovalState, UserRole


class Command(BaseCommand):
    help = "Create a local admin user and an approved demo user."

    def add_arguments(self, parser):
        parser.add_argument("--admin-username", default="admin")
        parser.add_argument("--admin-password", default="admin123")
        parser.add_argument("--demo-username", default="demo")
        parser.add_argument("--demo-password", default="demo123")

    def handle(self, *args, **options):
        user_model = get_user_model()

        admin, _ = user_model.objects.get_or_create(
            username=options["admin_username"],
            defaults={"email": "", "is_staff": True, "is_superuser": True},
        )
        admin.is_staff = True
        admin.is_superuser = True
        admin.set_password(options["admin_password"])
        admin.save()
        admin_profile = ensure_user_profile(admin)
        admin_profile.role = UserRole.ADMIN
        admin_profile.approval_state = ApprovalState.APPROVED
        admin_profile.approved_at = timezone.now()
        admin_profile.save(
            update_fields=["role", "approval_state", "approved_at"]
        )

        demo, _ = user_model.objects.get_or_create(
            username=options["demo_username"],
            defaults={"email": "", "is_staff": False, "is_superuser": False},
        )
        demo.is_staff = False
        demo.is_superuser = False
        demo.set_password(options["demo_password"])
        demo.save()
        demo_profile = ensure_user_profile(demo)
        demo_profile.role = UserRole.USER
        demo_profile.approval_state = ApprovalState.APPROVED
        demo_profile.approved_at = timezone.now()
        demo_profile.save(
            update_fields=["role", "approval_state", "approved_at"]
        )

        self.stdout.write(
            self.style.SUCCESS(
                "Created admin and demo users. "
                f"Admin={options['admin_username']} Demo={options['demo_username']}"
            )
        )
