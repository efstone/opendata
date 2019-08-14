from django.contrib import admin
from knapiks.models import *

# Register your models here.


class LogFilter(admin.SimpleListFilter):
    title = 'Message Types'
    parameter_name = 'entry_type'

    def lookups(self, request, model_admin):
        return (
            ('chats', 'In-game chats'),
            ('logins', 'User log-ins'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'chats':
            return queryset.filter(msg_content__startswith='<')
        elif self.value() == 'logins':
            return queryset.filter(msg_content__contains='joined the game')
        else:
            return queryset.filter()


@admin.register(Config)
class ConfigAdmin(admin.ModelAdmin):
    list_display = ['mc_key', 'mc_value']


@admin.register(Log)
class LogAdmin(admin.ModelAdmin):
    list_display = ['msg_time', 'msg_content', 'msg_twilled']
    search_fields = ['msg_content']
    list_filter = [LogFilter]


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ['name', 'last_login', 'last_logout']