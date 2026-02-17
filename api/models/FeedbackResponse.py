from django.db import models
from django.db.models import Q
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from .Student import Student

class FeedbackResponse(models.Model):
    id = models.BigAutoField(primary_key=True)
    form_content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    form_object_id = models.BigIntegerField()
    form = GenericForeignKey('form_content_type', 'form_object_id')

    student = models.ForeignKey(Student, null=True, blank=True, on_delete=models.SET_NULL, related_name='feedback_responses')
    pseudonym = models.CharField(max_length=36, null=True, blank=True)
    responses = models.JSONField()  # list of {question_id, question_code, rating, comment}
    sentiment = models.JSONField(null=True, blank=True)  # {overall:{label,score}, by_question:[...]}
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    is_anonymous = models.BooleanField(default=False)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'feedback_responses'
        constraints = [
            models.UniqueConstraint(fields=['form_content_type','form_object_id','student'], name='unique_form_student', condition=Q(student__isnull=False)),
            models.UniqueConstraint(fields=['form_content_type','form_object_id','pseudonym'], name='unique_form_pseudonym', condition=Q(pseudonym__isnull=False)),
        ]
        managed = False

    def __str__(self):
        return f"FeedbackResponse {self.id} for {self.form_content_type}({self.form_object_id})"
