from django.db import models

class EvaluationQuestion(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=64, unique=True, null=True, blank=True, help_text="Stable front-end id (e.g. 'inst_1')")
    question_text = models.TextField()
    QUESTION_TYPES = [
        ('rating', 'Rating'),
        ('comment', 'Comment'),
        ('scale', 'Scale'),
        ('text', 'Text'),
    ]
    question_type = models.CharField(max_length=20, choices=QUESTION_TYPES)
    position = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'evaluation_questions'
        unique_together = ('position',)
        managed = False

    def __str__(self):
        return self.code or (self.question_text[:50] + '...')