from django.contrib import admin
from matching.models import TaskClaim


class TaskClaimAdmin(admin.ModelAdmin):
    list_display = (
        'task',
        'person',
        'kind',
        'created_at',
    )


# Register your models here.
admin.site.register(TaskClaim, TaskClaimAdmin)
