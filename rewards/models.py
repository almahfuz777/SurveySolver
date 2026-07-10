import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum


class PointTransactionQuerySet(models.QuerySet):
    def balance_for(self, user):
        return self.filter(user=user).aggregate(total=Sum('amount'))['total'] or 0


class PointTransaction(models.Model):
    class Reason(models.TextChoices):
        PROFILE_COMPLETION = 'profile_completion', 'Profile completion'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='point_transactions',
    )
    amount = models.IntegerField()
    reason = models.CharField(max_length=32, choices=Reason.choices)
    idempotency_key = models.CharField(max_length=160, unique=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = PointTransactionQuerySet.as_manager()

    class Meta:
        ordering = ('-created_at',)
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(amount=0),
                name='rewards_point_transaction_nonzero',
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Point transactions are immutable.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Point transactions are immutable.')

    def __str__(self):
        return f'{self.amount} points for {self.user.email}'
