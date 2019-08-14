from django.db import models

# Create your models here.


class Config(models.Model):
    mc_key = models.CharField(max_length=150, default='', unique=True)
    mc_value = models.CharField(max_length=350, default='')

    def __str__(self):
        return f"{self.mc_key}"

    class Meta:
        verbose_name = 'Config'
        verbose_name_plural = 'Configs'


class Log(models.Model):
    msg_time = models.DateTimeField(null=True, default=None)
    msg_content = models.CharField(max_length=2000, default='')
    msg_type = models.CharField(max_length=150, default='')
    msg_twilled = models.DateTimeField(null=True, blank=True, default=None)

    def __str__(self):
        return f"{self.msg_content}"

    class Meta:
        unique_together = ['msg_time', 'msg_content']
        verbose_name = 'Log Msg'
        verbose_name_plural = 'Log Messages'
        ordering = ['msg_time']


class Player(models.Model):
    name = models.CharField(max_length=100, default='', unique=True)
    last_login = models.DateTimeField(null=True, default=None)
    last_logout = models.DateTimeField(null=True, default=None)

    def __str__(self):
        return f"{self.name}"

    class Meta:
        ordering = ['-last_login']