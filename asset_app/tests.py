from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model

from asset_app.models import Asset


class AssetDeleteFlowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='adminuser',
            password='StrongPass123!',
            role='superadmin',
            is_staff=True,
        )
        self.asset = Asset.objects.create(
            asset_type='Laptop',
            company_name='Test Company',
            series_number='SN-1001',
            model='ThinkPad T14',
            status='Available',
            purchase_date='2024-01-01',
            warranty='1',
        )

    def test_asset_detail_has_delete_form_for_admin(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('asset_detail', args=[self.asset.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Delete Asset')
        self.assertContains(response, reverse('delete_asset', args=[self.asset.pk]))
        self.assertContains(response, 'csrfmiddlewaretoken')

    def test_delete_asset_requires_post(self):
        self.client.force_login(self.user)

        get_response = self.client.get(reverse('delete_asset', args=[self.asset.pk]))
        self.assertEqual(get_response.status_code, 302)
        self.assertTrue(Asset.objects.filter(pk=self.asset.pk).exists())

        post_response = self.client.post(reverse('delete_asset', args=[self.asset.pk]))
        self.assertEqual(post_response.status_code, 302)
        self.assertFalse(Asset.objects.filter(pk=self.asset.pk).exists())
