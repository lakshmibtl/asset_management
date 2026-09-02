from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from .models import Asset, Assignment, AssetHistory

@receiver(pre_save, sender=Asset)
def track_status_change(sender, instance, **kwargs):
    if instance.pk:  # Only on update
        old_asset = Asset.objects.get(pk=instance.pk)
        if old_asset.status != instance.status:
            AssetHistory.objects.create(
                asset=instance,
                previous_status=old_asset.status,
                new_status=instance.status,
                assigned_to=None,
                notes="Status updated"
            )

@receiver(post_save, sender=Assignment)
def track_assignment_change(sender, instance, created, **kwargs):
    if created:
        AssetHistory.objects.create(
            asset=instance.asset,
            previous_status=instance.asset.status,
            new_status='In Use',
            assigned_to=instance.employee,
            notes=f"Assigned to {instance.employee.username}"
        )
    elif instance.returned_at:
        AssetHistory.objects.create(
            asset=instance.asset,
            previous_status='In Use',
            new_status='Available',
            assigned_to=instance.employee,
            notes=f"Returned by {instance.employee.username}"
        )
