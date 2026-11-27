import pytest
from django.urls import reverse
from django.test import TestCase, Client
from authentication.models import CustomUser


@pytest.mark.django_db
class SessionAndLoginInactivityTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.password = "StrongPass123!"
        self.user = CustomUser.objects.create_user(
            username="doctor_user",
            password=self.password,
            role="doctor"
        )

    def test_session_ping_unauthenticated(self):
        """Unauthenticated session ping returns 401."""
        response = self.client.get(reverse('authentication:session_ping'))
        self.assertEqual(response.status_code, 401)
        data = response.json()
        self.assertFalse(data.get('authenticated'))

    def test_session_ping_authenticated(self):
        """Authenticated session ping returns 200 and user info, extending session."""
        self.client.login(username=self.user.username, password=self.password)
        response = self.client.get(reverse('authentication:session_ping'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get('authenticated'))
        self.assertEqual(data.get('username'), self.user.username)

    def test_unauthenticated_therapy_entry_redirects_to_login(self):
        """Unauthenticated access to therapy_entry page redirects to login with next parameter."""
        response = self.client.get('/sheduling/therapy-entry/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/authentication/login/', response.url)
        self.assertIn('next=/sheduling/therapy-entry/', response.url)

    def test_unauthenticated_prescription_entry_redirects_to_login(self):
        """Unauthenticated access to prescription_entry page redirects to login with next parameter."""
        response = self.client.get('/sheduling/prescriptions/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/authentication/login/', response.url)
        self.assertIn('next=/sheduling/prescriptions/', response.url)

    def test_login_redirects_to_next_url(self):
        """Logging in preserves and redirects to the safe next parameter."""
        response = self.client.post(
            f"{reverse('authentication:login')}?next=/sheduling/therapy-entry/",
            {'username': self.user.username, 'password': self.password}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/sheduling/therapy-entry/')

    def test_already_authenticated_user_visiting_login_redirects_to_next_or_dashboard(self):
        """An already authenticated user visiting login page is redirected to next url or user profile."""
        self.client.login(username=self.user.username, password=self.password)
        response = self.client.get(f"{reverse('authentication:login')}?next=/sheduling/therapy-entry/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/sheduling/therapy-entry/')

    def test_logout_redirects_to_login(self):
        """Logging out flushes the session and redirects to login."""
        self.client.login(username=self.user.username, password=self.password)
        response = self.client.get(reverse('authentication:logout'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/authentication/login/', response.url)
