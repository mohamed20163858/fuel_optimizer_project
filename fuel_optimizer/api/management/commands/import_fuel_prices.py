# api/management/commands/import_fuel_prices.py
import csv
import os
from django.core.management.base import BaseCommand
from api.models import FuelPrice

class Command(BaseCommand):
    help = 'Import fuel prices from CSV file located in the project root'

    def handle(self, *args, **options):
        # Build the file path assuming the CSV file is in the project root
        file_path = os.path.join(os.getcwd(), 'fuel-prices-for-be-assessment.csv')
        
        fuel_prices = []
        with open(file_path, newline='') as file:
            reader = csv.DictReader(file)
            for row in reader:
                fuel_price = FuelPrice(
                    truckstop_id=int(row['OPIS Truckstop ID']),
                    truckstop_name=row['Truckstop Name'],
                    address=row['Address'],
                    city=row['City'],
                    state=row['State'],
                    rack_id=int(row['Rack ID']),
                    retail_price=float(row['Retail Price'])
                )
                fuel_prices.append(fuel_price)
                
        FuelPrice.objects.bulk_create(fuel_prices)
        self.stdout.write(self.style.SUCCESS(f"Imported {len(fuel_prices)} fuel prices."))
