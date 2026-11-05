from django.contrib.auth import views as auth_views
from django.urls import path

from .views import SignUpView

app_name = "accounts"

urlpatterns = [
    path("inscription/", SignUpView.as_view(), name="signup"),
    path("connexion/", auth_views.LoginView.as_view(), name="login"),
    path("deconnexion/", auth_views.LogoutView.as_view(), name="logout"),
]
