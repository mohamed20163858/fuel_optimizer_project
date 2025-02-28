from django.urls import path
from .views import RouteFuelView, FuelPriceListView

urlpatterns = [
    path('fuel-prices/', FuelPriceListView.as_view(), name='fuel-prices'),
    path('route-fuel/', RouteFuelView.as_view(), name='route-fuel'),
]
