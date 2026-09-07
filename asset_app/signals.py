from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from .models import Asset, Assignment

@receiver(pre_save, sender=Asset)
def track_status_change(sender, instance, **kwargs):
    if instance.pk:
        try:
            old_asset = Asset.objects.get(pk=instance.pk)
            if old_asset.status != instance.status:
                pass  # TODO: implement status history tracking
        except Asset.DoesNotExist:
            pass

@receiver(post_save, sender=Assignment)
def track_assignment_change(sender, instance, created, **kwargs):
    pass  # TODO: implement assignment history tracking
