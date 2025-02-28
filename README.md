# Fuel Optimizer API

This Django application provides an API to calculate the most cost-effective fuel stops along a route between a start and finish location within the USA. The API returns a route map URL along with optimal fuel stop recommendations based on fuel prices, a 10 miles per gallon consumption rate, and a maximum vehicle range of 500 miles.

## Demo Video
[Demo link](https://www.loom.com/share/d1044c59f4424b6881272a96cdd560fb)

## Features

- **Route Calculation:** Uses [openrouteservice](https://openrouteservice.org/) for mapping and routing.
- **Geocoding:** Uses [Nominatim](https://nominatim.org/) for converting addresses to coordinates.
- **Fuel Stop Optimization:** Uses a graph-based approach (Dijkstra's algorithm) to select the best fuel stops based on fuel prices, route distance, and detour costs.
- **Fuel Cost Estimation:** Calculates total fuel cost based on consumption (10 MPG) and stops' fuel prices.
- **Google Maps Integration:** Returns a Google Maps Directions URL for visualizing the route and stops.

## Prerequisites

- Python 3.8 or later
- [Django 3.2.23](https://docs.djangoproject.com/en/3.2/releases/3.2.23/)
- PostgreSQL (or another database configured in your Django project)
- A free API key from [openrouteservice](https://openrouteservice.org/)

## Installation

1. **Clone the repository:**

   ```bash
   git clone https://github.com/mohamed20163858/fuel_optimizer_project.git
   cd fuel_optimizer_project
   ```
2. **Create a virtual environment and activate it:**
   
     ```bash
     python -m venv env
     source env/bin/activate   # On Windows use: env\Scripts\activate
     ```
3. **Install dependencies:**

    ```bash
    pip install -r requirements.txt
    ```

4. **Configure Environment Variables:**
     Create a `.env` file and paste the following lines inside it
     ```bash
     OPENROUTESERVICE_API_KEY="Enter_your_OPENROUTESERVICE_API_KEY"
     MAPQUEST_API_KEY="Enter_your_MAPQUEST_API_KEY"
     DEBUG=True
     ```
 - You can get the `OPENROUTESERVICE_API_KEY`  by creating an account on the [this link](https://account.heigit.org/login) and then navigating to this [link](https://account.heigit.org/manage/key) to get the key
 - You can get the ` MAPQUEST_API_KEY` by creating an account on the [this link](https://developer.mapquest.com/account/user/login) after that visit this [link](https://developer.mapquest.com/account/user/me/apps) click create new key and get it.
5. **Apply Migrations:**
     ```bash
     python manage.py migrate
     ```
6. **Load Fuel Price Data:**
     run the following commands to load the fuel price data into your app database:-
     first, run this:- 
     ```bash
     python manage.py import_fuel_prices.py
     ```
     then run this:-
   
     ```bash
     python manage.py bulk_update_fuel_stations_geo.py
     ```
  You must run them in order, otherwise, you will get errors inside your terminal

## Running the Application
Start the Django development server:
  ```bash
  python manage.py runserver
  ```
  The API will be available at http://localhost:8000/ (or the port you specify).

## API Endpoints
1. Fuel Price List
   
 - Endpoint: /api/fuelprices/
 - Method: GET
 - Description: Returns a list of fuel price records from the database.
    
3. Route Fuel Optimization
  - Endpoint: /api/routefuel/
  - Method: POST
  - Payload:
    ```json
    {
      "start": "Los Angeles, CA",
      "finish": "New York, NY"
    }
    ```
### Response:
The API returns a JSON response containing:
  - Route details (distance, duration, and a Google Maps URL)
  - Optimal fuel stops along the route (with updated fuel recommendations)
  - Total estimated fuel cost

### Testing with Postman
You can use Postman or any other API client to test the endpoints. Here are example requests:

#### Example Request for Route Fuel Optimization:

- Method: POST

- URL: http://localhost:8000/api/routefuel/

- Headers: Content-Type: application/json

- Body:

```json
{
  "start": "Los Angeles, CA",
  "finish": "New York, NY"
}
```



   
   
