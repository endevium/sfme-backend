from django.db import models
from .Program import Program

class Block(models.Model):
    id = models.BigAutoField(primary_key=True)
    program = models.ForeignKey(
        Program, on_delete=models.CASCADE, related_name="blocks"
    )
    department = models.CharField(max_length=50)
    year_level = models.CharField(max_length=8)
    block_name = models.CharField(max_length=50)
    
    class Meta:
        db_table = 'blocks'
        managed = False
        
    def __str__(self):
        return f"{self.block_name} {self.year_level} - {self.department}"