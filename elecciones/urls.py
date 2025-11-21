from django.urls import path
from . import views

urlpatterns = [
    # ...existing code...
    path('check-vote-status/<int:vote_id>/', views.check_vote_status, name='check_vote_status'),
]