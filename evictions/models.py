from django.db import models

# Create your models here.

class Disposition(models.Model):
    name = models.CharField(max_length=100)
    judge_decided = models.NullBooleanField(default=None)


class Case(models.Model):
    case_num = models.CharField(max_length=17, unique=True)
    filing_date = models.DateTimeField(default=None, null=True)
    page_source = models.TextField()
    disposition = models.ForeignKey(Disposition, db_constraint=False, null=True, default=None)
    court = models.CharField(max_length=30)
    judge = models.CharField(max_length=50)
    case_type = models.CharField(max_length=120, default='')
    judgment_amount = models.DecimalField(max_digits=20, decimal_places=2, default=None, null=True)
    awarded_to = models.CharField(max_length=500, default='', null=True)
    landlord_tenant_case = models.NullBooleanField(default=None)
    is_apartment = models.NullBooleanField(default=None)
    address = models.CharField(max_length=400, default='')

    def __str__(self):
        return self.case_num


class Party(models.Model):
    cases = models.ManyToManyField(Case, through='Appearance')
    name = models.CharField(max_length=600, unique=True)
    is_landlord = models.NullBooleanField(default=None)

    def __str__(self):
        return self.name


class Appearance(models.Model):
    case = models.ForeignKey(Case, on_delete=models.CASCADE)
    party = models.ForeignKey(Party, on_delete=models.CASCADE)
    party_type = models.CharField(max_length=80)


class Attorney(models.Model):
    parties = models.ManyToManyField(Party)
    cases = models.ManyToManyField(Case)
    name = models.CharField(max_length=600)

    def __str__(self):
        return self.name
