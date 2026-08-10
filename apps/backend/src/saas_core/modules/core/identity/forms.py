from django.contrib.auth.forms import UserChangeForm, UserCreationForm

from .models import User


class IdentityUserCreationForm(UserCreationForm):  # type: ignore[type-arg]
    class Meta:
        model = User
        fields = ("email",)


class IdentityUserChangeForm(UserChangeForm):  # type: ignore[type-arg]
    class Meta:
        model = User
        fields = "__all__"
