'''
from django.db import models
from .Student import Student
from .ModuleAssignment import ModuleAssignment

class EnrolledModule(models.Model):
    id = models.BigAutoField(primary_key=True)
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    module_assignment = models.ForeignKey(ModuleAssignment, on_delete=models.CASCADE)

    class Meta:
        db_table = 'student_modules'
        unique_together = (('student', 'module_assignment'),)
        managed = False
    
    def __str__(self):
        return f"{self.student} -> {self.module_assignment}"
'''
