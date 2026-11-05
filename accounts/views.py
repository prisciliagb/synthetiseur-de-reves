from django.contrib.auth import login
from django.contrib.auth.decorators import login_not_required
from django.http import HttpResponse
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.generic import CreateView

from .forms import SignUpForm


@method_decorator(login_not_required, name="dispatch")
class SignUpView(CreateView):
    """Page d'inscription, accessible sans être connecté."""

    form_class = SignUpForm
    template_name = "registration/signup.html"
    success_url = reverse_lazy("dreams:list")

    def form_valid(self, form: SignUpForm) -> HttpResponse:
        """Crée le compte puis connecte directement l'utilisateur.

        Args:
            form: Le formulaire d'inscription validé.

        Returns:
            Une redirection vers la liste des rêves.
        """
        response = super().form_valid(form)
        login(self.request, self.object)
        return response
