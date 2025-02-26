# api/management/commands/bulk_update_fuel_stations_geo.py
import time
import math
import os
import requests
from django.core.management.base import BaseCommand
from api.models import FuelPrice

class Command(BaseCommand):
    help = 'Bulk update FuelPrice records with lat/lon using MapQuest Batch Geocoding API'

    def handle(self, *args, **options):
        # Get all fuel stations missing latitude or longitude
        stations = list(FuelPrice.objects.filter(lat__isnull=True, lon__isnull=True))
        total = len(stations)
        self.stdout.write(f"Found {total} fuel stations to update.")

        # Set your batch size (adjust as needed)
        batch_size = 100
        mapquest_api_key = os.getenv("MAPQUEST_API_KEY")  # Replace with your MapQuest API key

        for i in range(0, total, batch_size):
            batch = stations[i:i+batch_size]
            # Prepare a list of address strings
            addresses = [f"{station.address}, {station.city}, {station.state}, USA" for station in batch]

            # Build the payload for the batch request
            url = "https://www.mapquestapi.com/geocoding/v1/batch"
            params = {"key": mapquest_api_key}
            payload = {"locations": addresses}

            self.stdout.write(f"Geocoding batch {i // batch_size + 1} ({len(batch)} addresses)...")
            response = requests.post(url, params=params, json=payload)
            if response.status_code == 200:
                data = response.json()
                results = data.get("results", [])
                # Map each result to the corresponding station in the batch
                for station, result in zip(batch, results):
                    # Check if any location was found
                    if result.get("locations"):
                        location = result["locations"][0]
                        station.lat = location["latLng"]["lat"]
                        station.lon = location["latLng"]["lng"]
                        station.save()
                        self.stdout.write(self.style.SUCCESS(
                            f"Updated: {station.truckstop_name} with lat: {station.lat}, lon: {station.lon}"
                        ))
                    else:
                        self.stdout.write(self.style.WARNING(
                            f"No location found for: {station.truckstop_name}"
                        ))
            else:
                self.stdout.write(self.style.ERROR(
                    f"Batch geocoding failed with status {response.status_code}"
                ))
            # Optional: Pause briefly between batches to avoid hitting rate limits
            time.sleep(1)
        
        self.stdout.write(self.style.SUCCESS("Finished updating fuel station geolocations."))
