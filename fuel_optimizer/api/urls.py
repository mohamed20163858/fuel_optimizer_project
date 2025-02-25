from django.urls import path
from .views import RouteFuelView

urlpatterns = [
    path('route-fuel/', RouteFuelView.as_view(), name='route-fuel'),
]
