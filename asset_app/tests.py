from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model

from asset_app.forms import AssetForm
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


class DeadAssetFormTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='deadadmin',
            password='StrongPass123!',
            role='superadmin',
            is_staff=True,
        )
        self.base = {
            'asset_type': 'Laptop',
            'model': 'ThinkPad T14',
            'company_name': 'Test Company',
            'status': 'Dead',
            'purchase_date': '01/01/2024',
        }

    def test_cost_warranty_fields_are_disabled_for_dead_status(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('add_asset'))

        self.assertEqual(response.status_code, 200)
        for anchor in ('id="costContainer"', 'id="warrantyContainer"', 'id="warrantyEndDateContainer"'):
            self.assertContains(response, anchor)
        self.assertContains(response, "toLowerCase() === 'dead'")

    def test_dead_asset_saves_without_cost_or_warranty(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('add_asset'), {
            **self.base,
            'series_number': 'SN-DEAD-1',
        })

        self.assertEqual(response.status_code, 302)
        asset = Asset.objects.get(series_number='SN-DEAD-1')
        self.assertEqual(asset.status, 'Dead')
        self.assertIsNone(asset.cost)
        self.assertIsNone(asset.warranty)
        self.assertIsNone(asset.warranty_end_date)

    def test_dead_asset_ignores_injected_cost_and_warranty(self):
        form = AssetForm({
            **self.base,
            'series_number': 'SN-DEAD-2',
            'cost': '99999',
            'warranty': '3',
            'warranty_end_date': '01/01/2027',
        })

        self.assertTrue(form.is_valid(), form.errors)
        asset = form.save(commit=False)
        self.assertIsNone(asset.cost)
        self.assertIsNone(asset.warranty)
        self.assertIsNone(asset.warranty_end_date)

    def test_live_asset_still_requires_cost(self):
        form = AssetForm({
            **self.base,
            'status': 'Available',
            'series_number': 'SN-LIVE-1',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('cost', form.errors)
