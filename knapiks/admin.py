from django.contrib import admin
from knapiks.models import *

# Register your models here.


@admin.register(MCConfig)
class ConfigAdmin(admin.ModelAdmin):
    list_display = ['mc_key', 'mc_value']


@admin.register(McLog)
class LogAdmin(admin.ModelAdmin):
    list_display = ['msg_time', 'msg_type', 'msg_content', 'msg_twilled']
    search_fields = ['msg_content']
