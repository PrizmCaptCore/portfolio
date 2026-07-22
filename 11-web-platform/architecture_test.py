# 아키텍처 테스트: API 표면이 템플릿을 렌더링하면 CI 실패 (core/tests.py 발췌)
# 포트폴리오용으로 sanitize 되었습니다: 내부 endpoint/키/제품 특정 내용 제거.

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from apps.teams.models import Membership, Role, Team
from apps.users.models import Level

from .architecture import (
    LEGACY_TEMPLATE_RENDERERS,
    find_template_renderer_functions,
    iter_api_surface_files,
    iter_project_python_files,
)


class AppBootstrapTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="core-user",
            email="core@example.com",
            password="testpass123",
        )
        EmailAddress.objects.create(
            user=self.user,
            email=self.user.email,
            verified=True,
            primary=True,
        )
        self.user.profile.level = Level.A2
        self.team = Team.objects.create(name="Core Team")
        Membership.objects.create(user=self.user, team=self.team, role=Role.ADMIN)
        self.user.profile.level = Level.A2
        self.user.profile.current_team = self.team
        self.user.profile.save(update_fields=["level", "current_team"])

    def test_bootstrap_api_returns_runtime_config_for_guests(self):
        response = self.client.get(reverse("api:core_api:bootstrap"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["apiBaseUrl"], "http://testserver/api/v1")
        self.assertEqual(payload["backendBaseUrl"], "http://testserver")
        self.assertEqual(payload["routes"]["home"], "http://testserver/")
        self.assertIn("csrfToken", payload)
        self.assertIsNone(payload["user"])

    def test_bootstrap_api_includes_authenticated_user(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("api:core_api:bootstrap"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["user"]["email"], self.user.email)
        self.assertEqual(payload["user"]["uuid"], str(self.user.uuid))
        self.assertEqual(payload["user"]["profile"]["name"], self.user.profile.name)
        self.assertEqual(payload["routes"]["login"], "http://testserver/accounts/login/")
        self.assertEqual(payload["routes"]["appHome"], "http://localhost:5174/")
        self.assertEqual(payload["routes"]["personalDashboard"], "http://localhost:5174/users/dashboard/")
        self.assertEqual(payload["routes"]["profileDetail"], "http://localhost:5174/users/profile/")
        self.assertEqual(
            payload["routes"]["currentTeamDashboard"],
            f"http://localhost:5174/teams/{self.team.uuid}/dashboard/",
        )
        self.assertIn("notifications", payload)


class FrontendArchitectureTests(SimpleTestCase):
    def test_api_surface_never_renders_templates(self):
        renderers = find_template_renderer_functions(iter_api_surface_files())

        self.assertEqual(
            renderers,
            set(),
            msg=self._format_message(
                "API-only surface must not render templates",
                renderers,
            ),
        )

    def test_legacy_template_renderers_are_explicitly_allowlisted(self):
        current_renderers = find_template_renderer_functions(iter_project_python_files())

        self.assertEqual(
            current_renderers,
            LEGACY_TEMPLATE_RENDERERS,
            msg=self._format_message(
                "Unexpected template-backed product views detected",
                current_renderers.symmetric_difference(LEGACY_TEMPLATE_RENDERERS),
            ),
        )

    def _format_message(self, title, items):
        if not items:
            return title
        lines = "\n".join(f"- {item}" for item in sorted(items))
        return f"{title}:\n{lines}"
