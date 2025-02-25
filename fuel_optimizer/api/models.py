# api/models.py
from django.db import models

class FuelPrice(models.Model):
    truckstop_id = models.IntegerField()
    truckstop_name = models.CharField(max_length=255)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=2)
    rack_id = models.IntegerField()
    retail_price = models.FloatField()

    def __str__(self):
        return f"{self.truckstop_name} ({self.city}, {self.state}) - ${self.retail_price}"
