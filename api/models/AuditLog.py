from django.db import models

class AuditLog(models.Model):
    user = models.CharField(max_length=100)  # User who performed the action
    role = models.CharField(max_length=50)  # Role like 'Depthead', 'Faculty', etc.
    action = models.CharField(max_length=200)  # Action performed
    category = models.CharField(max_length=50)  # Category like 'USER MANAGEMENT', 'FORM MANAGEMENT'
    status = models.CharField(max_length=20, default='Success')  # Status like 'Success', 'Failed'
    message = models.TextField()  # Detailed message
    ip = models.CharField(max_length=45, blank=True, null=True)  # IP address
    timestamp = models.DateTimeField(auto_now_add=True)  # When it happened

    class Meta:
        db_table = "audit_logs"
        managed = False
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.user} - {self.action} - {self.timestamp}"