from django.shortcuts import render, get_object_or_404, redirect, render_to_response
from django.utils import timezone
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.db.models import Sum
from django.db.models import Q
from django.http import HttpResponse, Http404, JsonResponse
from django.contrib import messages
from django.core.cache import cache
from django.views import View
from django.views.generic import ListView
from django.utils.decorators import method_decorator
from django.contrib.auth.mixins import LoginRequiredMixin

from datetime import date, timedelta
import json

from .forms import ExpenseForm, SelectDateExpenseForm, SelectDateRangeExpenseForm
from .models import Expense, Remark
from utils import helpers

# Create your views here.


class AddExpense(LoginRequiredMixin, View):
    form_class = ExpenseForm
    template_name = "add_expense.html"
    context = {
        'form': form_class,
        'title': "Add expense"
    }

    def get(self, request, *args, **kwargs):
        last_10_expenses = Expense.objects.all(user=request.user).order_by(
                            '-created_at', '-timestamp',
                        )[:10]
                        
        self.context['objects'] = last_10_expenses
        return render(request, self.template_name, self.context)

    def post(self, request, *args, **kwargs):
        form = self.form_class(request.POST)
        if form.is_valid():
            amount = form.cleaned_data.get('amount')
            remark = form.cleaned_data.get('remark', '').strip()
            timestamp = form.cleaned_data.get('timestamp')

            remark_object = None
            if remark:
                try:
                    remark_object = Remark.objects.get(user=request.user, name__iexact=remark)
                except Remark.DoesNotExist:
                    remark_object = Remark.objects.create(user=request.user, name=remark)

            Expense.objects.create(
                user = request.user,
                amount = amount,
                timestamp = timestamp,
                remark=remark_object,
            )

            return HttpResponse(status=200)
        else:
            return HttpResponse(status=400)


class GetBasicInfo(LoginRequiredMixin, View):

    def get(self, request, *args, **kwargs):
        user = request.user
        data = dict()

        qs = Expense.objects
        today_expense = qs.this_day(user=user).aggregate(Sum('amount'))['amount__sum'] or 0
        this_month_expense = qs.this_month(user=user).aggregate(Sum('amount'))['amount__sum'] or 0

        data['today_expense'] = f"{today_expense:,}"
        data['this_month_expense'] = f"{this_month_expense:,}"
        data['expense_to_income_ratio'] = helpers.expense_to_income_ratio(request.user)

        today = helpers.get_ist_datetime()
        this_month_income = user.incomes.filter\
            (timestamp__year=today.year, timestamp__month=today.month).aggregate(Sum('amount'))['amount__sum'] or 0
        data['this_month_eir'] = helpers.calculate_ratio(this_month_expense, this_month_income)

        data = json.dumps(data)
        return HttpResponse(data, content_type='application/json')


class UpdateExpense(LoginRequiredMixin, View):
    form_class = ExpenseForm
    template_name = "update_expense.html"
    context = {
        "title": "Update expense"
    }

    def get_object(self, request, *args, **kwargs):
        id = int(kwargs['id'])
        instance = Expense.objects.all(user=request.user).filter(id=id).first()

        if not instance:
            raise Http404
        return instance

    def get(self, request, *args, **kwargs):
        instance = self.get_object(request, *args, **kwargs)

        initial_data = {
            'amount': instance.amount,
            'remark': instance.remark,
            'timestamp': instance.timestamp
        }
        form = self.form_class(initial=initial_data)
        self.context['form'] = form
        return render(request, self.template_name, self.context)

    def post(self, request, *args, **kwargs):
        instance = self.get_object(request, *args, **kwargs)

        form = self.form_class(request.POST)
        if form.is_valid():
            amount = form.cleaned_data.get('amount')
            remark = form.cleaned_data.get('remark', '').strip()
            timestamp = form.cleaned_data.get('timestamp')

            instance.amount = amount
            instance.timestamp = timestamp
            rem = None
            if remark:
                try:
                    rem = Remark.objects.get(user=request.user, name__iexact=remark)
                except:
                    rem = Remark.objects.create(user=request.user, name=remark)
            
            instance.remark = rem
            instance.save()

            return HttpResponse(status=200)
        else:
            return HttpResponse(status=400)


class ExpenseList(LoginRequiredMixin, View):
    template_name = "expense_list.html"

    def get(self, request, *args, **kwargs):
        objects_list = Expense.objects.all(user=request.user)
        first_date = None

        if objects_list:
            first_date = objects_list.last().timestamp or None

        q = request.GET.get("q")
        object_total = None
        if q:
            objects_list = objects_list.filter(
                        Q(remark__name__icontains=q) |
                        Q(amount__icontains=q)
                        ).distinct()
            object_total = objects_list.aggregate(Sum('amount'))['amount__sum'] or 0

        order_field = request.GET.get("field")
        if order_field:
            ordering = request.GET.get("order", "") + order_field
            objects_list = objects_list.order_by(ordering)

        objects = helpers.get_paginator_object(request, objects_list, 30)
        total = Expense.objects.amount_sum(user=request.user)

        context = {
            "title": "Expenses",
            "objects": objects,
            "total": total,
            "first_date": first_date,
            "object_total": object_total,
            "expense_to_income_ratio": helpers.expense_to_income_ratio(request.user),
        }

        return render(request, self.template_name, context)


class DayWiseExpense(LoginRequiredMixin, View):
    template_name = "day-expense.html"

    def get(self, request, *args, **kwargs):
        context = {}
        date_str = ""
        expense = Expense.objects.all(user=request.user)

        year = int(request.GET.get('year', 0))
        month = int(request.GET.get('month', 0))
        if year or month:
            if year:
                expense = expense.filter(timestamp__year=year)
                date_str = f": {year}"
            if month:
                expense = expense.filter(timestamp__month=month)
                dt = date(year, month, 1)
                date_str = f": {dt.strftime('%B %Y')}"
            context['total'] = expense.aggregate(Sum('amount'))['amount__sum'] or 0

        days = expense.dates('timestamp', 'day', order='DESC')
        days = helpers.get_paginator_object(request, days, 50)

        data = []
        for day in days:
            sum_day = expense.filter(timestamp=day).aggregate(Sum('amount'))['amount__sum'] or 0
            data.append((day, sum_day))
        
        context['title'] = f'Day-Wise Expense {date_str}'
        context['data'] = data
        context['objects'] = days
        return render(request, self.template_name, context)


class MonthWiseExpense(LoginRequiredMixin, View):
    template_name = "month-expense.html"

    def get(self, request, *args, **kwargs):
        context = {}
        date_str = ""
        user = request.user
        year = request.GET.get('year')
        expenses = Expense.objects.all(user=user)
        if year:
            expenses = expenses.filter(timestamp__year=int(year))
            context['total'] = expenses.aggregate(Sum('amount'))['amount__sum'] or 0
            date_str = f": {year}"

        dates = expenses.dates('timestamp', 'month', order='DESC')
        expense_sum = user.expenses.aggregate(Sum('amount'))['amount__sum'] or 0
        income_sum = user.incomes.aggregate(Sum('amount'))['amount__sum'] or 0

        dates = helpers.get_paginator_object(request, dates, 12)

        data = []
        for date in dates:
            amount = Expense.objects.this_month(
                user=user, year=date.year, month=date.month
                ).aggregate(Sum('amount'))['amount__sum'] or 0
            month_income_sum = user.incomes.filter(timestamp__year=date.year, timestamp__month=date.month)\
                                .aggregate(Sum('amount'))['amount__sum'] or 0

            expense_ratio = helpers.calculate_ratio(amount, expense_sum)
            expense_to_income_ratio = helpers.calculate_ratio(amount, income_sum)
            month_expense_to_income_ratio = helpers.calculate_ratio(amount, month_income_sum)
            data.append((date, amount, expense_ratio, expense_to_income_ratio, month_expense_to_income_ratio))

        context['title'] = f'Monthly Expense {date_str}'
        context['data'] = data
        context['objects'] = dates
        return render(request, self.template_name, context)


class YearWiseExpense(LoginRequiredMixin, View):
    """
    return all the year in which expenses are registered.
    """
    template_name = "year-expense.html"
    context = {
        'title': 'Yearly Expense',
    }

    def get(self, request, *args, **kwargs):
        user = request.user
        years = Expense.objects.all(user=user).dates('timestamp', 'year', order='DESC')
        expense_sum = user.expenses.aggregate(Sum('amount'))['amount__sum'] or 0
        income_sum = user.incomes.aggregate(Sum('amount'))['amount__sum'] or 0

        years = helpers.get_paginator_object(request, years, 5)

        data = []
        for year in [yr.year for yr in years]:
            amount = Expense.objects.this_year(user=user, year=year)\
                        .aggregate(Sum('amount'))['amount__sum'] or 0
            year_income_sum = user.incomes.filter(timestamp__year=year).aggregate(Sum('amount'))['amount__sum'] or 0

            expense_ratio = helpers.calculate_ratio(amount, expense_sum)
            expense_to_income_ratio = helpers.calculate_ratio(amount, income_sum)
            year_expense_to_income_ratio = helpers.calculate_ratio(amount, year_income_sum)
            data.append((year, amount, expense_ratio, expense_to_income_ratio, year_expense_to_income_ratio))

        self.context['data'] = data
        self.context['objects'] = years
        return render(request, self.template_name, self.context)


class DateSearch(LoginRequiredMixin, View):
    date_form_class = SelectDateExpenseForm
    range_form_class = SelectDateRangeExpenseForm
    template_name = "search.html"
    context = {
        "title": "Search"
    }

    def get(self, request, *args, **kwargs):
        context = self.context.copy()
        context['date_form'] = self.date_form_class()
        context['range_form'] = self.range_form_class()

        if request.GET:
            date_form = self.date_form_class(request.GET)
            range_form = self.range_form_class(request.GET)

            objects = None

            if range_form.is_valid():
                remark = range_form.cleaned_data.get('remark', '').strip()
                f_dt = range_form.cleaned_data.get('from_date')
                t_dt = range_form.cleaned_data.get('to_date')
                objects = Expense.objects.all(user=request.user).filter(timestamp__range=(f_dt, t_dt))
                if remark:
                    objects = objects.filter(remark__name__icontains=remark)
            else:
                range_form = self.range_form_class()

            if date_form.is_valid():
                remark = date_form.cleaned_data.get('remark', '').strip()
                dt = date_form.cleaned_data.get('date')
                objects = Expense.objects.all(user=request.user).filter(timestamp=dt)
                if remark:
                    objects = objects.filter(remark__name__icontains=remark)
            else:
                date_form = self.date_form_class()

            if objects:
                object_total = objects.aggregate(Sum('amount'))['amount__sum'] or 0
            else:
                object_total = None

            context['date_form'] = date_form
            context['range_form'] = range_form
            context['objects'] = objects
            context['object_total'] = object_total

        return render(request, self.template_name, context)


class GoToExpense(LoginRequiredMixin, View):
    """
    provides expenses for particular day, month or year.
    """
    template_name = 'goto.html'

    def get(self, request, *args, **kwargs):
        day = int(kwargs.get('day', 0))
        month = int(kwargs.get('month', 0))
        year = int(kwargs.get('year', 0))
        date_str = ""
        
        if day:
            objects = Expense.objects.this_day(user=request.user, year=year, month=month, day=day)
            dt = date(year, month, day)
            date_str = f': {dt.strftime("%d %b %Y")}'
        elif month:
            objects = Expense.objects.this_month(user=request.user, year=year, month=month)
            dt = date(year, month, 1)
            date_str = f': {dt.strftime("%b %Y")}'
        elif year:
            objects = Expense.objects.this_year(user=request.user, year=year)
            date_str = f': {year}'

        total = objects.aggregate(Sum('amount'))['amount__sum'] or 0
        objects = helpers.get_paginator_object(request, objects, 50)

        context = {
            "title": f"Expenses {date_str}",
            "objects": objects,
            "total": total,
        }

        return render(request, self.template_name, context)


class GoToRemarkWiseExpense(LoginRequiredMixin, View):
    """
    provies expenses for particular day, month or year.
    """
    template_name = 'remark-wise-expenses.html'

    def get(self, request, *args, **kwargs):
        user = request.user
        day = int(kwargs.get('day', 0))
        month = int(kwargs.get('month', 0))
        year = int(kwargs.get('year', 0))
        date_str = ""
        
        if day:
            objects = Expense.objects.this_day(user=user, year=year, month=month, day=day)
            _day = date(year, month, day)
            date_str = f': {_day.strftime("%d %b %Y")}'
        elif month:
            objects = Expense.objects.this_month(user=user, year=year, month=month)
            _month = date(year, month, 1)
            date_str = f': {_month.strftime("%b %Y")}'
        elif year:
            objects = Expense.objects.this_year(user=user, year=year)
            date_str = f': {year}'
        else:
            objects = Expense.objects.all(user=user)

        objects = objects.select_related('remark')
        remarks = set()
        for instance in objects:
            remarks.add(instance.remark)

        expense_sum = user.expenses.aggregate(Sum('amount'))['amount__sum'] or 0
        income_sum = user.incomes.aggregate(Sum('amount'))['amount__sum'] or 0

        remark_data = []
        for remark in remarks:
            amount = objects.filter(remark=remark)\
                        .aggregate(Sum('amount'))['amount__sum'] or 0
            expense_ratio = helpers.calculate_ratio(amount, expense_sum)
            expense_to_income_ratio = helpers.calculate_ratio(amount, income_sum)
            remark_data.append((remark, amount, expense_ratio, expense_to_income_ratio))

        remark_data = sorted(remark_data, key=lambda x: x[1], reverse=True)
        total = objects.aggregate(Sum('amount'))['amount__sum'] or 0

        context = {
            "title": f"Remark-Wise Expenses {date_str}",
            "remarks": remark_data,
            "total": total,
        }

        return render(request, self.template_name, context)


class GetRemark(LoginRequiredMixin, View):
    """
    will be used to autocomplete the remarks
    """

    def get(self, request, *args, **kwargs):
        term = request.GET.get('term', '').strip()
        remarks = Remark.objects.filter(user=request.user).filter(name__icontains=term)\
                    .values_list('name', flat=True)
        results = [remark for remark in remarks]
        data = json.dumps(results)

        return HttpResponse(data, content_type='application/json')


class Error404(View):
    def get(self, request, *args, **kwargs):
        return render(request, "404.html", {}, status=404)


def handler500(request):
    response = render(request, "500.html")
    response.status_code = 500
    return response


class Error400(View):
    def get(self, request, *args, **kwargs):
        return render(request, "400.html", {}, status=400)


class Error403(View):
    def get(self, request, *args, **kwargs):
        return render(request, "403.html", {}, status=403)

