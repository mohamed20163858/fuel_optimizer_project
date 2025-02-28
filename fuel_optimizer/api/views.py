import os
import math
import polyline
import requests
from urllib.parse import quote
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, generics
from shapely.geometry import LineString, Point
from geopy.distance import distance as geopy_distance
from pyproj import Transformer
from ortools.linear_solver import pywraplp
from .models import FuelPrice
from .serializers import FuelPriceSerializer

# Transformer for spatial projection: WGS84 to Web Mercator (EPSG:3857)
transformer = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)

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

        # 1. Get route details from openrouteservice.
        route_data = self.get_route(start, finish)
        if not route_data:
            return Response({'error': 'Error retrieving route data.'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # 2. Get all candidate fuel stations along the route.
        candidate_stops = self.get_candidate_stations(route_data)
        
        # 3. Optimize refueling stops using graph-based optimization.
        total_miles = route_data['distance_miles']
        opt_plan, opt_cost = optimize_refueling_graph(total_miles, candidate_stops)
        if opt_plan is not None:
            fuel_stops = opt_plan
            total_cost = opt_cost
        else:
            fuel_stops = candidate_stops
            total_cost = self.calculate_total_cost(route_data, candidate_stops)
        
        # 4. Build a Google Maps Directions URL using full addresses.
        fuel_stop_addresses = [stop['location'] for stop in fuel_stops]
        route_data['map_url'] = self.get_static_map_url(start, finish, fuel_stop_addresses)
        
        # Remove the geometry field before returning the response.
        route_data.pop('geometry', None)
        
        response_data = {
            'route': route_data,
            'fuel_stops': fuel_stops,
            'total_fuel_cost': total_cost,
        }
        return Response(response_data)

    def geocode(self, address):
        """Use Nominatim to convert an address into coordinates (lat, lon)."""
        url = "https://nominatim.openstreetmap.org/search"
        params = {'q': address, 'format': 'json'}
        headers = {'User-Agent': 'fuel_optimizer/1.0 mohamed20163858@gmail.com'}
        response = requests.get(url, params=params, headers=headers)
        if response.status_code == 200:
            data = response.json()
            if data:
                return float(data[0]['lat']), float(data[0]['lon'])
        return None

    def get_route(self, start, finish):
        """Get route details from openrouteservice."""
        start_coords = self.geocode(start)
        finish_coords = self.geocode(finish)
        if not start_coords or not finish_coords:
            return None

        ors_api_key = os.getenv("OPENROUTESERVICE_API_KEY")
        if not ors_api_key:
            return None

        url = "https://api.openrouteservice.org/v2/directions/driving-car"
        headers = {'Authorization': ors_api_key, 'Content-Type': 'application/json'}
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
                    'map_url': ""
                }
        return None

    def get_candidate_stations(self, route_data, threshold_m=20*1609.34, mpg=10):
        """
        For each fuel station in the DB, compute its minimum distance to the route and projected mile marker,
        using spatial projection for speed.
        Returns candidate stops with:
           - location: "truckstop_name, address, city, state"
           - lat, lon
           - miles_from_start (miles)
           - fuel_price
           - extra_detour_gallons: (2 * (min_distance in miles)) / mpg
           - recommended_gallons: 50 + extra_detour_gallons
        """
        encoded_geometry = route_data.get('geometry', '')
        route_coords = polyline.decode(encoded_geometry)  # List of (lat, lon)
        if not route_coords:
            return []
        
        # Create a Shapely LineString from route coordinates in EPSG:4326, then project to EPSG:3857.
        route_line_wgs84 = LineString([(lon, lat) for lat, lon in route_coords])
        projected_points = [Point(*transformer.transform(lon, lat)) for lat, lon in route_coords]
        route_line = LineString(projected_points)
        
        # Compute cumulative distances along the route (in meters) using projected coordinates.
        cumulative = [0]
        for i in range(1, len(projected_points)):
            d = projected_points[i-1].distance(projected_points[i])
            cumulative.append(cumulative[-1] + d)
        
        candidate_list = []
        tank_capacity = 50
        # Compute bounding box of projected route.
        xs = [pt.x for pt in projected_points]
        ys = [pt.y for pt in projected_points]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        # Expand bounding box by threshold.
        min_x -= threshold_m
        max_x += threshold_m
        min_y -= threshold_m
        max_y += threshold_m
        # Transform bounding box back to WGS84.
        inv_transformer = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
        box_min_lon, box_min_lat = inv_transformer.transform(min_x, min_y)
        box_max_lon, box_max_lat = inv_transformer.transform(max_x, max_y)
        fuel_stations = FuelPrice.objects.filter(lat__gte=box_min_lat, lat__lte=box_max_lat,
                                                   lon__gte=box_min_lon, lon__lte=box_max_lon)
        
        for station in fuel_stations:
            if station.lat is None or station.lon is None:
                continue
            # Project station point.
            station_point = Point(*transformer.transform(station.lon, station.lat))
            dist_m = route_line.distance(station_point)
            if dist_m <= threshold_m:
                # Compute projected mile marker using route_line.project()
                proj_distance = route_line.project(station_point)
                mile_marker = proj_distance / 1609.34
                extra_gallons = (2 * (dist_m / 1609.34)) / mpg
                candidate_list.append({
                    "location": f"{station.truckstop_name}, {station.address}, {station.city}, {station.state}",
                    "lat": station.lat,
                    "lon": station.lon,
                    "miles_from_start": round(mile_marker, 2),
                    "fuel_price": station.retail_price,
                    "extra_detour_gallons": round(extra_gallons, 2),
                    "recommended_gallons": round(tank_capacity + extra_gallons, 2)
                })
        candidate_list.sort(key=lambda s: s["miles_from_start"])
        return candidate_list

    def calculate_total_cost(self, route_data, fuel_stops):
        """Calculate total fuel cost based on overall fuel consumption."""
        total_distance_miles = route_data.get('distance_meters', 0) / 1609.34
        total_gallons = total_distance_miles / 10
        price = fuel_stops[0].get('fuel_price', 3.50) if fuel_stops else 3.50
        return round(total_gallons * price, 2)

    def get_static_map_url(self, start_address, finish_address, fuel_stop_addresses):
        """
        Construct a Google Maps Directions URL using addresses.
        Format:\n
        https://www.google.com/maps/dir/?api=1&origin=<origin>&destination=<destination>&waypoints=<wp1>|<wp2>|...
        """
        base_url = "https://www.google.com/maps/dir/?api=1"
        origin = quote(start_address)
        destination = quote(finish_address)
        waypoints = ""
        if fuel_stop_addresses:
            waypoints = "&waypoints=" + "|".join([quote(addr) for addr in fuel_stop_addresses])
        return f"{base_url}&origin={origin}&destination={destination}{waypoints}"

# --- Graph-based Optimization for Refueling ---
def optimize_refueling_graph(total_distance_miles, candidate_stops, tank_capacity=50, mpg=10):
    """
    Use a graph-based approach to select an optimal subset of candidate stops.
    
    Nodes:
      - Node 0: start at mile 0.
      - Nodes 1..N: candidate stops (from candidate_stops, sorted by miles_from_start).
      - Node N+1: destination at total_distance_miles.
    
    An edge from node i to j exists if d[j]-d[i] <= 500 (the truck's range).
    The cost of an edge to candidate node j is defined as:\n
         cost = recommended_gallons_j * fuel_price_j\n
    (For destination, cost is 0.)
    Dijkstra's algorithm finds the minimum-cost path.
    
    Returns (plan, total_cost) where plan is a list of candidate stops on the optimal path.
    """
    candidate_stops = sorted(candidate_stops, key=lambda s: s["miles_from_start"])
    N = len(candidate_stops)
    d = [0]  # mile marker at start.
    costs = [0]  # cost for start is 0.
    addresses = ["Start"]
    for stop in candidate_stops:
        d.append(stop["miles_from_start"])
        costs.append(stop["recommended_gallons"] * stop["fuel_price"])
        addresses.append(stop["location"])
    d.append(total_distance_miles)
    addresses.append("Destination")
    costs.append(0)
    
    num_nodes = N + 2
    edges = {i: [] for i in range(num_nodes)}
    for i in range(num_nodes):
        for j in range(i+1, num_nodes):
            if d[j] - d[i] <= 500:
                edge_cost = 0 if j == num_nodes-1 else costs[j]
                edges[i].append((j, edge_cost))
    
    dist = [float('inf')] * num_nodes
    prev = [-1] * num_nodes
    dist[0] = 0
    unvisited = set(range(num_nodes))
    while unvisited:
        u = min(unvisited, key=lambda x: dist[x])
        unvisited.remove(u)
        for (v, w) in edges[u]:
            if v in unvisited and dist[u] + w < dist[v]:
                dist[v] = dist[u] + w
                prev[v] = u
    
    path = []
    u = num_nodes - 1
    while u != -1:
        path.append(u)
        u = prev[u]
    path.reverse()
    
    plan = []
    for node in path[1:-1]:
        plan.append(candidate_stops[node - 1])
    total_cost = dist[num_nodes - 1]
    return plan, total_cost
