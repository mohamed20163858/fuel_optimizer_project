# api/serializers.py
from rest_framework import serializers
from .models import FuelPrice

class FuelPriceSerializer(serializers.ModelSerializer):
    class Meta:
        model = FuelPrice
        fields = '__all__'
