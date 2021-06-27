from django.db import models
from django.contrib.auth import get_user_model
from django.db.models.fields import related

from utils.base_model import BaseModel

User = get_user_model()

# Create your models here.


class Source(BaseModel):
    user = models.ForeignKey(User, related_name='sources', on_delete=models.CASCADE)
    name = models.CharField(max_length=30)

    def __str__(self):
        return self.name

    

class Income(BaseModel):
    user = models.ForeignKey(User, related_name='incomes', on_delete=models.CASCADE)
    amount = models.PositiveIntegerField()
    source = models.ForeignKey(Source, blank=True, null=True, related_name='incomes',
                on_delete=models.SET_NULL)
    timestamp = models.DateField()

    def __str__(self):
        return "{} : {}".format(self.user, self.source)

    class Meta():
        ordering = ('-timestamp', )


class SavingCalculation(BaseModel):
    user = models.OneToOneField(User, related_name='saving_calculation', on_delete=models.CASCADE)
    savings_min_amount = models.PositiveIntegerField(null=True, blank=True, help_text='min amount that must be saved if possible. 0 to ignore')
    savings_max_amount = models.PositiveIntegerField(null=True, blank=True, help_text='max amount that can be saved. 0 to ignore')
    savings_percentage = models.PositiveIntegerField(help_text='in percentage') # of the total amount
    debt_percentage = models.PositiveIntegerField(help_text='in percentage')
    equity_percentage = models.PositiveIntegerField(help_text='in percentage')
    amount_to_keep_in_bank = models.PositiveIntegerField(null=True, blank=True, help_text='Should be less than monthly salary. i.e. <=90% of monthly salary')

    def __str__(self):
        return f'{self.user}'

