import os
import math
import polyline
import requests
from urllib.parse import quote
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
            return Response({'error': 'Both start and finish locations are required.'},
                            status=status.HTTP_400_BAD_REQUEST)

        # 1. Get route details using our mapping API integration.
        route_data = self.get_route(start, finish)
        if not route_data:
            return Response({'error': 'Error retrieving route data.'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # 2. Determine optimal fuel stops.
        fuel_stops = self.calculate_fuel_stops(route_data)
        # 3. Calculate the total cost of fuel for the trip.
        total_cost = self.calculate_total_cost(route_data, fuel_stops)
        
        # Build a static map URL using Google Maps with addresses.
        # Fuel stop addresses are built using: truckstop_name, address, city, state.
        fuel_stop_addresses = [stop['location'] for stop in fuel_stops]
        route_data['map_url'] = self.get_static_map_url(start, finish, fuel_stop_addresses)
        
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
                return float(data[0]['lat']), float(data[0]['lon'])
        return None

    def get_route(self, start, finish):
        """Get the route details from the openrouteservice API."""
        start_coords = self.geocode(start)
        finish_coords = self.geocode(finish)
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
        if response.status_code == 200:
            data = response.json()
            routes = data.get('routes', [])
            if routes:
                route_summary = routes[0].get('summary', {})
                geometry = routes[0].get('geometry', '')
                duration_seconds = route_summary.get('duration', 0)
                hours = int(duration_seconds // 3600)
                minutes = int((duration_seconds % 3600) // 60)
                duration_formatted = f"{hours} h {minutes} min"
                distance_meters = route_summary.get('distance', 0)
                distance_km = distance_meters / 1000.0
                distance_miles = distance_meters / 1609.34
                return {
                    'start': start,
                    'finish': finish,
                    'distance_meters': distance_meters,
                    'distance_km': round(distance_km, 2),
                    'distance_miles': round(distance_miles, 2),
                    'duration_seconds': duration_seconds,
                    'duration_formatted': duration_formatted,
                    'geometry': geometry,
                    'map_url': ""  # Will be updated later.
                }
        return None

    def calculate_fuel_stops(self, route_data):
        """
        Determine optimal fuel stops along the route based on a 500-mile range.
        This implementation decodes the encoded polyline from openrouteservice,
        computes cumulative geodesic distances along the route (in meters), and for each required 
        500-mile segment, interpolates the target coordinate along the route.
        It then finds fuel stations near that target point (within ~10 miles, i.e., 16,093.4 m)
        and selects the station with the lowest fuel price.
        Assumes the FuelPrice model includes 'lat' and 'lon' fields.
        """
        total_distance_meters = route_data.get('distance_meters', 0)
        total_distance_miles = total_distance_meters / 1609.34
        if total_distance_miles <= 500:
            return []
        
        num_stops = math.ceil(total_distance_miles / 500) - 1
        encoded_geometry = route_data.get('geometry', '')
        route_coords = polyline.decode(encoded_geometry)  # list of (lat, lon)
        if not route_coords:
            return []
        
        cumulative_distances = [0]
        for i in range(1, len(route_coords)):
            d = geopy_distance(route_coords[i-1], route_coords[i]).meters
            cumulative_distances.append(cumulative_distances[-1] + d)
        polyline_total_distance = cumulative_distances[-1]
        
        stops = []
        for i in range(1, num_stops + 1):
            target_distance_m = 500 * i * 1609.34
            if target_distance_m > polyline_total_distance:
                target_point = route_coords[-1]
            else:
                for j in range(1, len(cumulative_distances)):
                    if cumulative_distances[j] >= target_distance_m:
                        prev_point = route_coords[j-1]
                        curr_point = route_coords[j]
                        segment_dist = cumulative_distances[j] - cumulative_distances[j-1]
                        frac = 0 if segment_dist == 0 else (target_distance_m - cumulative_distances[j-1]) / segment_dist
                        target_lat = prev_point[0] + frac * (curr_point[0] - prev_point[0])
                        target_lon = prev_point[1] + frac * (curr_point[1] - prev_point[1])
                        target_point = (target_lat, target_lon)
                        break
            
            search_radius_m = 16093.4  # 10 miles in meters.
            candidate_stations = []
            for station in FuelPrice.objects.all():
                if station.lat is None or station.lon is None:
                    continue
                dist = geopy_distance(target_point, (station.lat, station.lon)).meters
                if dist <= search_radius_m:
                    candidate_stations.append((station, dist))
            
            if candidate_stations:
                candidate_stations.sort(key=lambda x: x[0].retail_price)
                selected_station = candidate_stations[0][0]
            else:
                selected_station = FuelPrice.objects.order_by('retail_price').first()
            
            # Build full address using truckstop_name, address, city, state.
            full_address = f"{selected_station.truckstop_name.split("#")[0]}, {selected_station.city}, {selected_station.state}"
            print()
            stops.append({
                "location": full_address,
                "lat": selected_station.lat,
                "lon": selected_station.lon,
                "miles_from_start": 500 * i,
                "fuel_price": selected_station.retail_price,
                "recommended_gallons": 500 / 10
            })
        
        return stops

    def calculate_total_cost(self, route_data, fuel_stops):
        """Calculate the total fuel cost based on the route distance."""
        total_distance_miles = route_data.get('distance_meters', 0) / 1609.34
        total_gallons = total_distance_miles / 10
        price = fuel_stops[0].get('fuel_price', 3.50) if fuel_stops else 3.50
        return round(total_gallons * price, 2)

    def get_static_map_url(self, start_address, finish_address, fuel_stop_addresses):
        """
        Construct a Google Maps Directions URL using addresses.
        Uses the following format:
        https://www.google.com/maps/dir/?api=1&origin=<origin>&destination=<destination>&waypoints=<wp1>|<wp2>|...
        """
        base_url = "https://www.google.com/maps/dir/?api=1"
        origin = quote(start_address)
        destination = quote(finish_address)
        waypoints = ""
        if fuel_stop_addresses:
            waypoints = "&waypoints=" + "|".join([quote(addr) for addr in fuel_stop_addresses])
        url = f"{base_url}&origin={origin}&destination={destination}{waypoints}"
        return url
