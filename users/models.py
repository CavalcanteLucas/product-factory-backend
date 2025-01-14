import re
import uuid

from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser, PermissionsMixin
from django.core.validators import RegexValidator
from django.db import models
from polymorphic.managers import PolymorphicManager
from django.contrib.auth.models import AbstractBaseUser

from backend.mixins import TimeStampMixin, UUIDMixin
from commercial.models import Organisation

from django.contrib import auth

class BlacklistedUsernames(models.Model):
    username = models.CharField(max_length=30, unique=True, blank=False)

    def __str__(self):
        return self.username

    class Meta:
        db_table = "black_listed_usernames"


class UserManager(BaseUserManager):
    """
    Manager for a custom User model
    """

    def create_user(self, username, email, password=None):
        if not username:
            raise ValueError("Username should be provided!")
        elif BlacklistedUsernames.objects.filter(username=username).exists():
            raise ValueError("Username is not valid!")
        elif Organisation.objects.filter(username=username).exists():
            raise ValueError("You can't have the same username as organisation name!")
        elif not re.match(r'^[a-z0-9]*$', username):
            raise ValueError("Username may only contain letters and numbers")
        user = self.model(username=username, email=email)
        if password:
            user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, email, password=None):
        user = self.create_user(username, email, password)
        user.is_superuser = True
        user.is_staff = True
        user.save()
        return user


class User(AbstractBaseUser):
    id = models.UUIDField(default=uuid.uuid4, primary_key=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)
    is_logged = models.BooleanField(default=False)
    email = models.EmailField()
    username = models.CharField(max_length=39,
                                unique=True,
                                default='',
                                validators=[
                                    RegexValidator(
                                        regex="^[a-z0-9]*$",
                                        message="Username may only contain letters and numbers",
                                        code="invalid_username"
                                    )
                                ])

    def has_perm(self, perm, obj=None):
        # this only needed for django admin
        return self.is_active and self.is_staff and self.is_superuser

    def has_module_perms(self, app_label):
        # this only needed for django admin
        return self.is_active and self.is_staff and self.is_superuser

    def get_all_permissions(self, obj=None):
        return _user_get_permissions(self, obj, 'all') 

    USERNAME_FIELD = 'username'

    objects = UserManager()

    def __str__(self):
        return self.username

    class Meta:
        db_table = 'users_user'


# A few helper functions for common logic between User and AnonymousUser.
def _user_get_permissions(user, obj, from_name):
    permissions = set()
    name = 'get_%s_permissions' % from_name
    for backend in auth.get_backends():
        if hasattr(backend, name):
            permissions.update(getattr(backend, name)(user, obj))
    return permissions