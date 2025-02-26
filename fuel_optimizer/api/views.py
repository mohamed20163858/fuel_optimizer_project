import os
import math
import polyline
import requests
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, generics
from shapely.geometry import LineString
from geopy.distance import distance as geopy_distance
from .models import FuelPrice
from .serializers import FuelPriceSerializer

class FuelPriceListView(generics.ListAPIView):
    queryset = FuelPrice.objects.all()
    serializer_class = FuelPriceSerializer

class RouteFuelView(APIView):
    def post(self, request, *args, **kwargs):
        start = request.data.get('start')
        finish = request.data.get('finish')

        if not start or not finish:
            return Response({'error': 'Both start and finish locations are required.'}, status=status.HTTP_400_BAD_REQUEST)

        # 1. Get route details using our mapping API integration
        route_data = self.get_route(start, finish)
        if not route_data:
            return Response({'error': 'Error retrieving route data.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # 2. Determine optimal fuel stops (dummy implementation for now)
        fuel_stops = self.calculate_fuel_stops(route_data)
        # 3. Calculate the total cost of fuel for the trip
        total_cost = self.calculate_total_cost(route_data, fuel_stops)

        response_data = {
            'route': route_data,
            'fuel_stops': fuel_stops,
            'total_fuel_cost': total_cost,
        }
        return Response(response_data)

    def geocode(self, address):
        """Use Nominatim to convert an address into coordinates."""
        url = "https://nominatim.openstreetmap.org/search"
        params = {'q': address, 'format': 'json'}
        headers = {'User-Agent': 'fuel_optimizer/1.0 mohamed20163858@gmail.com'}  # Replace with your info
        response = requests.get(url, params=params, headers=headers)
        if response.status_code == 200:
            data = response.json()
            if data:
                # Return (latitude, longitude)
                return float(data[0]['lat']), float(data[0]['lon'])
        return None

    def get_route(self, start, finish):
        """Get the route details from the openrouteservice API."""
        start_coords = self.geocode(start)
        finish_coords = self.geocode(finish)
        # print("Start Coords:", start_coords, "Finish Coords:", finish_coords)
        if not start_coords or not finish_coords:
            return None

        ors_api_key = os.getenv("OPENROUTESERVICE_API_KEY")
        if not ors_api_key:
            return None

        url = "https://api.openrouteservice.org/v2/directions/driving-car"
        headers = {
            'Authorization': ors_api_key,
            'Content-Type': 'application/json'
        }
        # openrouteservice expects coordinates in [longitude, latitude] order.
        body = {
            "coordinates": [
                [start_coords[1], start_coords[0]],
                [finish_coords[1], finish_coords[0]]
            ]
        }
        response = requests.post(url, headers=headers, json=body)
        # print("Openrouteservice API Status:", response.status_code)
        # print("Openrouteservice API Response:", response.text)
        if response.status_code == 200:
            data = response.json()
            routes = data.get('routes', [])
            if routes:
                route_summary = routes[0].get('summary', {})
                # Extract geometry if available (it might be an encoded polyline or GeoJSON if requested)
                geometry = routes[0].get('geometry', {})
                return {
                    'start': start,
                    'finish': finish,
                    'distance_meters': route_summary.get('distance', 0),
                    'duration_seconds': route_summary.get('duration', 0),
                    'geometry': geometry,
                    'map_url': f"https://maps.openrouteservice.org/directions?n1={start_coords[0]}&n2={start_coords[1]}&n3=14&route={finish}"
                }
        return None

    def calculate_fuel_stops(self, route_data):
        """
        Determine optimal fuel stops along the route based on vehicle range (500 miles).
        This implementation decodes the route's encoded polyline, creates a LineString,
        and for each required 500-mile segment finds fuel stations near the target point (within ~10 miles).
        It then selects the station with the lowest fuel price from among those candidates.
        Assumes FuelPrice model includes 'lat' and 'lon' fields.
        """
        total_distance_meters = route_data.get('distance_meters', 0)
        total_distance_miles = total_distance_meters / 1609.34
        # If the total route is within one tank (500 miles), no stops are needed.
        if total_distance_miles <= 500:
            return []
        
        # Determine how many stops are needed.
        num_stops = math.ceil(total_distance_miles / 500) - 1

        # Decode the route geometry (assuming it's an encoded polyline string).
        encoded_geometry = route_data.get('geometry', '')
        route_coords = polyline.decode(encoded_geometry)
        if not route_coords:
            return []
        
        # Create a LineString (note: Shapely expects coordinates in (lon, lat) order).
        route_line = LineString([(lon, lat) for lat, lon in route_coords])
        
        stops = []
        # For each required stop, find the ideal point along the route.
        for i in range(1, num_stops + 1):
            # Target distance along the route in meters (500 miles * i converted to meters).
            target_distance_m = 500 * i * 1609.34
            # Ensure we do not exceed the route's length.
            if target_distance_m > route_line.length:
                target_distance_m = route_line.length
            target_point = route_line.interpolate(target_distance_m)
            target_lat = target_point.y
            target_lon = target_point.x
            
            # Define a search radius (10 miles ≈ 16,093.4 meters).
            search_radius_m = 16093.4
            
            candidate_stations = []
            for station in FuelPrice.objects.all():
                # Ensure the station has latitude and longitude.
                if station.lat is None or station.lon is None:
                    continue
                station_coords = (station.lat, station.lon)
                target_coords = (target_lat, target_lon)
                dist = geopy_distance(target_coords, station_coords).meters
                if dist <= search_radius_m:
                    candidate_stations.append((station, dist))
            
            # Select the station with the lowest retail price from the candidates.
            if candidate_stations:
                candidate_stations.sort(key=lambda x: x[0].retail_price)
                selected_station = candidate_stations[0][0]
            else:
                # If no station is nearby, fallback to the overall cheapest station.
                selected_station = FuelPrice.objects.order_by('retail_price').first()
            
            stops.append({
                "location": f"{selected_station.truckstop_name}, {selected_station.city}, {selected_station.state}",
                "miles_from_start": 500 * i,
                "fuel_price": selected_station.retail_price,
                "recommended_gallons": 500 / 10  # since vehicle achieves 10 mpg
            })
        
        return stops

    def calculate_total_cost(self, route_data, fuel_stops):
        """Calculate the total fuel cost based on the route distance."""
        total_distance_miles = route_data.get('distance_meters', 0) / 1609.34  # convert meters to miles
        total_gallons = total_distance_miles / 10  # vehicle achieves 10 miles per gallon
        # For simplicity, use the fuel price from the first fuel stop if available.
        price = fuel_stops[0].get('fuel_price', 3.50) if fuel_stops else 3.50
        return round(total_gallons * price, 2)