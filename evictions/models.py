from django.db import models

# Create your models here.

class Disposition(models.Model):
    name = models.CharField(max_length=100)
    judge_decided = models.NullBooleanField(default=None)

    def __str__(self):
        return f"{self.name}"

    class Meta:
        db_table = 'denton_docket_disposition'
        ordering = ['name']


class Case(models.Model):
    case_num = models.CharField(max_length=30, unique=True)
    filing_date = models.DateTimeField(default=None, null=True)
    page_source = models.TextField()
    disposition = models.ForeignKey(Disposition, db_constraint=False, null=True, default=None, on_delete=models.DO_NOTHING)
    court = models.CharField(max_length=30)
    judge = models.CharField(max_length=50)
    case_type = models.CharField(max_length=120, default='')
    judgment_amount = models.DecimalField(max_digits=20, decimal_places=2, default=None, null=True)
    awarded_to = models.CharField(max_length=500, default='', null=True)
    landlord_tenant_case = models.NullBooleanField(default=None)
    is_apartment = models.NullBooleanField(default=None)
    address = models.CharField(max_length=400, default='')
    parse_time = models.DateTimeField(default=None, null=True, blank=True)
    first_charge = models.CharField(max_length=300, default='', blank=True)

    def __str__(self):
        return self.case_num

    def parties(self):
        return f"{'; '.join([p.name for p in self.party_set.all()])}"

    class Meta:
        db_table = 'denton_docket_case'
        ordering = ['filing_date']


class Party(models.Model):
    cases = models.ManyToManyField(Case, through='Appearance')
    name = models.CharField(max_length=600, unique=True)
    is_landlord = models.NullBooleanField(default=None)

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'denton_docket_party'
        ordering = ['name']
        verbose_name_plural = 'Parties'


class Appearance(models.Model):
    case = models.ForeignKey(Case, on_delete=models.CASCADE)
    party = models.ForeignKey(Party, on_delete=models.CASCADE)
    party_type = models.CharField(max_length=80)

    def __str__(self):
        return f"{self.party_type}"

    class Meta:
        db_table = 'denton_docket_appearance'
        unique_together = ['case', 'party', 'party_type']


class Attorney(models.Model):
    appearance = models.ManyToManyField(Appearance)
    name = models.CharField(max_length=600)

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'denton_docket_attorney'


class CaseConfig(models.Model):
    key = models.CharField(max_length=150, default='', unique=True)
    value = models.CharField(max_length=350, default='')

    def __str__(self):
        return f"{self.key}: {self.value}"

    class Meta:
        verbose_name = 'Config'
        verbose_name_plural = 'Configs'
