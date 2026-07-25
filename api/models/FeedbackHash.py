from django.db import models
from django.utils import timezone
from .FeedbackResponse import FeedbackResponse

class FeedbackHash(models.Model):
    id = models.BigAutoField(primary_key=True)
    feedback_response = models.OneToOneField(
        FeedbackResponse, on_delete=models.CASCADE, related_name='hash_record'
    )
    hash = models.CharField(max_length=64, db_index=True)   
    tx_hash = models.CharField(max_length=66)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'feedback_hashes'
        managed = False

    def __str__(self):
        return f"{self.hash} ({self.tx_hash})"