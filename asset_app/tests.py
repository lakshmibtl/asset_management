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


class SerialNumberAutoGenerateTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='serialadmin',
            password='StrongPass123!',
            role='superadmin',
            is_staff=True,
        )
        self.base = {
            'asset_type': 'Laptop',
            'model': 'ThinkPad T14',
            'company_name': 'DELL',
            'status': 'Available',
            'cost': '50000',
        }

    def test_generate_series_number_uses_asset_type_prefix(self):
        self.assertEqual(Asset.generate_series_number('Laptop'), 'SN-LP-0001')
        self.assertEqual(Asset.generate_series_number('Printer'), 'SN-PR-0001')
        self.assertEqual(Asset.generate_series_number('Mouse'), 'SN-AS-0001')

    def test_generate_series_number_continues_from_existing(self):
        Asset.objects.create(asset_type='Laptop', series_number='SN-LP-0001')

        self.assertEqual(Asset.generate_series_number('Laptop'), 'SN-LP-0002')

    def test_generate_series_number_can_exclude_the_current_candidate(self):
        self.assertEqual(
            Asset.generate_series_number('Laptop', exclude=['SN-LP-0001']),
            'SN-LP-0002',
        )

    def test_blank_serial_number_is_generated_on_save(self):
        form = AssetForm({**self.base})

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().series_number, 'SN-LP-0001')

    def test_whitespace_only_serial_number_is_generated_on_save(self):
        form = AssetForm({**self.base, 'series_number': '   '})

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().series_number, 'SN-LP-0001')

    def test_manually_entered_serial_number_is_kept(self):
        form = AssetForm({**self.base, 'series_number': 'JGVHY02'})

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().series_number, 'JGVHY02')

    def test_duplicate_manual_serial_number_is_still_rejected(self):
        Asset.objects.create(asset_type='Laptop', series_number='JGVHY02')
        form = AssetForm({**self.base, 'series_number': 'JGVHY02'})

        self.assertFalse(form.is_valid())
        self.assertIn('series_number', form.errors)

    def test_successive_blank_adds_get_distinct_serial_numbers(self):
        for expected in ('SN-LP-0001', 'SN-LP-0002', 'SN-LP-0003'):
            form = AssetForm({**self.base})
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(form.save().series_number, expected)

    def test_serial_optional_on_add_but_required_on_edit(self):
        self.assertFalse(AssetForm().fields['series_number'].required)

        existing = Asset.objects.create(asset_type='Laptop', series_number='SN-LP-0001')
        edit_form = AssetForm(instance=existing)

        self.assertTrue(edit_form.fields['series_number'].required)
        self.assertEqual(edit_form.fields['series_number'].widget.attrs.get('required'), 'required')

    def test_add_view_saves_without_a_serial_number(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('add_asset'), self.base)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Asset.objects.get().series_number, 'SN-LP-0001')

    def test_add_view_offers_auto_generate_control(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('add_asset'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="generateSerialBtn"')
        self.assertContains(response, reverse('generate_serial_number'))

    def test_generate_endpoint_requires_login(self):
        response = self.client.get(reverse('generate_serial_number'))

        self.assertEqual(response.status_code, 302)

    def test_generate_endpoint_returns_next_unused_serial_number(self):
        Asset.objects.create(asset_type='Printer', series_number='SN-PR-0001')
        self.client.force_login(self.user)
        response = self.client.get(reverse('generate_serial_number'), {'asset_type': 'Printer'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['series_number'], 'SN-PR-0002')

    def test_previewed_serial_number_is_what_gets_stored(self):
        """The Generate button must preview the exact value save() will write."""
        self.client.force_login(self.user)
        previewed = self.client.get(
            reverse('generate_serial_number'), {'asset_type': 'Laptop'}
        ).json()['series_number']

        self.client.post(reverse('add_asset'), {**self.base, 'series_number': previewed})

        self.assertEqual(Asset.objects.get().series_number, previewed)
