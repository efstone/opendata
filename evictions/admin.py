from django.contrib import admin
from evictions.models import *
# Register your models here.


@admin.register(Case)
class CaseAdmin(admin.ModelAdmin):
    list_display = ['case_num', 'filing_date', 'court', 'judge', 'case_type', 'judgment_amount', 'awarded_to', 'parties']


@admin.register(Party)
class PartyAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_landlord']


@admin.register(Disposition)
class DispositionAdmin(admin.ModelAdmin):
    list_display = ['name']
