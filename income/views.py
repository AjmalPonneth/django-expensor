from datetime import date, timedelta
import statistics
import markdown
from contextlib import suppress
import json
import calendar

from django.contrib import messages
from django.shortcuts import render, get_object_or_404
from django.views.generic import (
    ListView,
    CreateView,
    UpdateView,
    DeleteView,
)
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.http import HttpResponse, Http404
from django.urls import reverse_lazy
from django.db.models import Sum

from .models import (
    Income,
    Source,
    SavingCalculation,
    InvestmentEntity,
)
from .forms import (
    IncomeForm,
    SelectDateRangeIncomeForm,
    SavingCalculatorForm,
    SavingCalculationModelForm,
    InvestmentEntityForm,
)
from utils import helpers
from utils.helpers import (
    aggregate_sum,
    get_ist_datetime,
    default_date_format,
)
from utils.constants import (
    BANK_AMOUNT_PCT,
    FIXED_SAVINGS_PCT,
    AVG_MONTH_DAYS,
    SHOW_INCOME_CALCULATOR_HOUR,
    DEFAULT_AMOUNT_IN_MULTIPLES_OF,
)
# Create your views here.


class IncomeList(LoginRequiredMixin, ListView):
    template_name = 'income_list.html'
    paginate_by = 15
    context_object_name = 'objects'

    def get_queryset(self, *args, **kwargs):
        qs = Income.objects.filter(user=self.request.user)\
                .order_by('-timestamp', '-created_at',)
        return qs

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        context['objects'] = context['page_obj']
        context['title'] = 'Income List'
        return context


class IncomeAdd(LoginRequiredMixin, View):
    template_name = 'add_income.html'
    form_class = IncomeForm

    def get(self, request, *args, **kwargs):
        context = {
            'income_form': self.form_class,
            'title' : 'Add Income',
        }
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        form = self.form_class(request.POST)
        if form.is_valid():
            amount = form.cleaned_data.get('amount')
            timestamp = form.cleaned_data.get('timestamp')
            source_name = form.cleaned_data.get('source', '').strip()

            source = None
            if source_name:
                source, _ = Source.objects.get_or_create(user=request.user, name=source_name)

            Income.objects.create(
                    user=request.user,
                    amount=amount,
                    timestamp=timestamp,
                    source=source,
                )
            messages.success(request, "Income added successfully!")
            return HttpResponse(status=201)
        else:
            return HttpResponse(status=400)


class IncomeUpdateView(LoginRequiredMixin, View):
    template_name = 'update_income.html'
    form_class = IncomeForm
    context = {
        'title': 'Update Income',
    }

    def get(self, request, *args, **kwargs):
        pk = int(kwargs['pk'])
        income = get_object_or_404(Income, id=pk, user=request.user)

        #checking if user own the object
        if income.user != request.user:
            raise Http404

        initial_data = {
            'amount': income.amount,
            'source': income.source,
            'timestamp': helpers.default_date_format(income.timestamp),
        }
        
        self.context['income_form'] = self.form_class(initial=initial_data)
        return render(request, self.template_name, self.context)

    def post(self, request, *args, **kwargs):
        pk = int(kwargs['pk'])
        income = get_object_or_404(Income, id=pk, user=request.user)

        #checking if user own the object
        if income.user != request.user:
            raise Http404

        form = self.form_class(request.POST)

        if form.is_valid():
            amount = form.cleaned_data['amount']
            timestamp = form.cleaned_data['timestamp']
            source_name = form.cleaned_data.get('source', '').strip()
            if source_name:
                try:
                    source = Source.objects.get(user=request.user, name=source_name)
                except Source.DoesNotExist:
                    source = Source.objects.create(user=request.user, name=source_name)
                income.source = source

            income.amount = amount
            income.timestamp = timestamp
            income.save()

            return HttpResponse(status=200)
        else:
            return HttpResponse(status=400)


class YearWiseIncome(LoginRequiredMixin, View):
    template_name = "year-income.html"
    context = {
        'title': 'Yearly Income',
    }

    def get(self, request, *args, **kwargs):
        page_size = int(request.GET.get('page_size', 5))
        user = request.user
        now = get_ist_datetime()
        incomes = Income.objects.filter(user=user)
        
        latest_date = now.date().replace(month=1, day=1)
        first_date = incomes.dates('timestamp', 'year', order='ASC').first() or latest_date
        dates = helpers.get_dates_list(first_date, latest_date, month=1, day=1)    
        dates = helpers.get_paginator_object(request, dates, page_size)

        data = []
        monthly_averages = []
        for dt in dates:
            total_months = now.month if dt.year == now.year else 12
            amount = aggregate_sum(incomes.filter(timestamp__year=dt.year))
            avg_income = amount // total_months
            data.append((dt, amount, avg_income))
            monthly_averages.append(avg_income)
        
        self.context['data'] = data
        self.context['objects'] = dates
        return render(request, self.template_name, self.context)


class YearlyIncomeExpenseReport(LoginRequiredMixin, View):
    template_name = "report.html"

    def get(self, request, *args, **kwargs):
        user = request.user
        incomes = user.incomes
        expenses = user.expenses
        
        now = helpers.get_ist_datetime()
        latest_date = now.date().replace(month=1, day=1)
        first_income_date = incomes.dates('timestamp', 'year', order='ASC').first() or latest_date
        first_expense_date = expenses.dates('timestamp', 'year', order='ASC').first() or latest_date
        first_date = min(first_income_date, first_expense_date)
        dates = helpers.get_dates_list(first_date, latest_date, month=1, day=1)
        
        dates = helpers.get_paginator_object(request, dates, 5)

        data = []
        for date in dates:
            income_sum = aggregate_sum(incomes.filter(timestamp__year=date.year))
            expense_sum = aggregate_sum(expenses.filter(timestamp__year=date.year))
            expense_ratio = helpers.calculate_ratio(expense_sum, income_sum)

            data.append({
                'date': date,
                'income_sum': income_sum,
                'expense_sum': expense_sum,
                'saved': income_sum - expense_sum,
                'expense_ratio': expense_ratio,
            })

        context = {
            'title': 'Report Card',
            'now': helpers.get_ist_datetime(),
            'eir': helpers.expense_to_income_ratio(user),
            'data': data,
            'objects': dates,
        }
        return render(request, self.template_name, context)


class MonthlyIncomeExpenseReport(LoginRequiredMixin, View):
    template_name = "report.html"

    def get(self, request, *args, **kwargs):
        user = request.user
        year = int(kwargs['year'])
        incomes = user.incomes.filter(timestamp__year=year)
        expenses = user.expenses.filter(timestamp__year=year)
        
        now = get_ist_datetime()
        if year == now.year:
            last_month = now.month
        else:
            last_month = 12
        latest_date = date(year, last_month, 1)
        first_date = date(year, 1, 1)
        dates = helpers.get_dates_list(first_date, latest_date, day=1)

        data = []
        for dt in dates:
            income_sum = aggregate_sum(incomes.filter(timestamp__month=dt.month))
            expense_sum = aggregate_sum(expenses.filter(timestamp__month=dt.month))
            expense_ratio = helpers.calculate_ratio(expense_sum, income_sum)

            data.append({
                'date': dt,
                'income_sum': income_sum,
                'expense_sum': expense_sum,
                'saved': income_sum - expense_sum,
                'expense_ratio': expense_ratio,
            })
            
        incomes_total = aggregate_sum(incomes)
        expenses_total = aggregate_sum(expenses)
        saved_total = incomes_total - expenses_total
        eir = helpers.calculate_ratio(expenses_total, incomes_total)
        
        total = {
            'income_sum': incomes_total,
            'expense_sum': expenses_total,
            'saved': saved_total,
            'expense_ratio': eir,
        }
        
        monthly_average = {
            'income_sum': int(incomes_total / last_month),
            'expense_sum': int(expenses_total / last_month),
            'saved': int(saved_total / last_month),
            'expense_ratio': eir,
        }

        context = {
            'title': f'Report Card: {year}',
            'year': year,
            'now': now,
            'eir': eir,
            'data': data,
            'total': total,
            'monthly_average': monthly_average,
        }
        return render(request, self.template_name, context)


class MonthWiseIncome(LoginRequiredMixin, View):
    template_name = "month-income.html"
    context = {
        'title': 'Monthly Income',
    }

    def get(self, request, *args, **kwargs):
        user = request.user
        context = self.context.copy()
        now = helpers.get_ist_datetime()
        
        incomes = Income.objects.filter(user=user)
        year = request.GET.get('year')
        if year:
            year = int(year)
            total_months = now.month if year == now.year else 12
            incomes = incomes.filter(timestamp__year=year)
            context['title'] = f"{context['title']}: {year}"
            context['total'] = aggregate_sum(incomes)
            context['monthly_average'] = context['total'] // total_months
            alt_first_date = date(year, 1, 1)
            if year == now.year:
                latest_date = date(year, now.month, 1)
            else:
                latest_date = date(year, 12, 1)
        else:
            alt_first_date = now.date().replace(month=1, day=1)
            latest_date = now.date().replace(day=1)

        # doing this way to maintain continuity of months
        first_date = incomes.dates('timestamp', 'month', order='ASC').first() or alt_first_date
        dates = helpers.get_dates_list(first_date, latest_date, day=1)
        dates = helpers.get_paginator_object(request, dates, 12)
        
        data = []
        for dt in dates:
            amount = incomes.filter(
                timestamp__year=dt.year,
                timestamp__month=dt.month,
            ).aggregate(Sum('amount'))['amount__sum'] or 0
            data.append({
                'date': dt,
                'amount': amount,
            })

        context['data'] = data
        context['objects'] = dates
        return render(request, self.template_name, context)


class GoToIncome(LoginRequiredMixin, View):
    """
    provides income for particular day, month or year.
    """
    template_name = 'income_list.html'

    def get(self, request, *args, **kwargs):
        year = int(kwargs.get('year'))
        month = int(kwargs.get('month'))
        dt = date(year, month, 1)
        date_str = dt.strftime("%B %Y")
        
        from_date = default_date_format(dt)
        to_date = default_date_format(
            date(year, month, calendar.monthrange(year, month)[1])
        )
        
        incomes = request.user.incomes
        incomes = incomes.filter(timestamp__year=year, timestamp__month=month)

        context = {
            "title": f"Income: {date_str}",
            "objects": incomes,
            "total": aggregate_sum(incomes),
            "count": incomes.count(),
            "year": year,
            "month": month,
            "from_date": from_date,
            "to_date": to_date,
        }
        return render(request, self.template_name, context)


class SourceView(LoginRequiredMixin, View):

    def get(self, request, *args, **kwargs):
        term = request.GET.get('term', '').strip()
        sources = Source.objects.filter(user=request.user, name__icontains=term)\
                    .values_list('name', flat=True)

        result = [source for source in sources]
        data = json.dumps(result)
        
        return HttpResponse(data, content_type='application/json')


class SourceWiseIncome(LoginRequiredMixin, View):
    template_name = 'source-wise-income.html'
    date_form_class = SelectDateRangeIncomeForm

    def get(self, request, *args, **kwargs):
        user = request.user
        month = int(request.GET.get('month', 0))
        year = int(request.GET.get('year', 0))
        from_date = to_date = None
        date_str = ""
        
        date_form = self.date_form_class(request.GET or None)
        incomes = user.incomes
        
        if month and year:
            objects = incomes.filter(timestamp__year=year, timestamp__month=month)
            _month = date(year, month, 1)
            date_str = f': {_month.strftime("%b %Y")}'
            from_date = default_date_format(_month)
            to_date = default_date_format(
                date(year, month, calendar.monthrange(year, month)[1])
            )
        elif year:
            objects = incomes.filter(timestamp__year=year)
            date_str = f': {year}'
            from_date = default_date_format(date(year, 1, 1))
            to_date = default_date_format(date(year, 12, 31))
        elif date_form.is_valid():
            source_name_search = date_form.cleaned_data.get('source')
            _from_date = date_form.cleaned_data.get('from_date')
            _to_date = date_form.cleaned_data.get('to_date')
            objects = incomes
            if _from_date and _to_date:
                objects = objects.filter(timestamp__range=(_from_date, _to_date))
                from_date = default_date_format(_from_date)
                to_date = default_date_format(_to_date)
                date_str = f': {from_date} to {to_date}'
            if source_name_search:
                objects = objects.filter(source__name=source_name_search)
        else:
            objects = incomes

        objects = objects.select_related('source')
        sources = set()
        for instance in objects:
            sources.add(instance.source)

        income_sum = aggregate_sum(objects)

        source_data = []
        for source in sources:
            source_filter = objects.filter(source=source)
            amount = aggregate_sum(source_filter)
            source_data.append({
                'source': source,
                'source_count': source_filter.count(),
                'amount': amount,
            })

        source_data = sorted(source_data, key=lambda x: x['amount'], reverse=True)

        context = {
            "title": f"Source-Wise Income{date_str}",
            "sources": source_data,
            "total": income_sum,
            "count": len(source_data),
            "from_date": from_date,
            "to_date": to_date,
        }

        return render(request, self.template_name, context)


class IncomeDateSearch(LoginRequiredMixin, View):
    form_class = SelectDateRangeIncomeForm
    template_name = "income-search.html"

    def get(self, request, *args, **kwargs):
        context = dict()
        date_str = ""
        from_date_str = to_date_str = None
        objects = Income.objects.filter(user=request.user)
        
        initial = dict()
        first_income = objects.exclude(amount=0).order_by('timestamp', 'created_at').first()
        if first_income:
            initial['from_date'] = default_date_format(first_income.timestamp)
        form = self.form_class(request.GET or None, initial=initial)

        if form.is_valid():
            source = form.cleaned_data.get('source').strip()
            from_date = form.cleaned_data.get('from_date')
            to_date = form.cleaned_data.get('to_date')

            if from_date and to_date:
                objects = objects.filter(timestamp__range=(from_date, to_date))
                from_date_str = default_date_format(from_date)
                to_date_str = default_date_format(to_date)
                date_str = f': {from_date_str} to {to_date_str}'
            elif from_date or to_date:
                the_date = from_date or to_date
                objects = objects.filter(timestamp=the_date)
                from_date_str = to_date_str = default_date_format(the_date)
                date_str = f': {from_date_str}'

            if source == '""':
                objects = objects.filter(source__isnull=True)
            elif source:
                objects = objects.filter(source__name=source)

            total = aggregate_sum(objects)
            count = objects.count()
            try:
                days = (to_date - from_date).days
                months = days / AVG_MONTH_DAYS
                if months > 1:
                    context['monthly_average'] = int(total/months)
            except:
                pass

            context['objects'] = helpers.get_paginator_object(request, objects, 15)
            context['total'] = total
            context['count'] = count

        context['title'] = f'Income Search{date_str}'
        context['form'] = form
        context['from_date'] = from_date_str
        context['to_date'] = to_date_str
        return render(request, self.template_name, context)


class SavingCalculationDetailView(LoginRequiredMixin, View):
    form_class = SavingCalculationModelForm
    inv_form_class = InvestmentEntityForm
    template_name = "savings-calculation-detail.html"
    context = {
        'title': 'Saving Calculation Detail',
    }

    def get(self, request, *args, **kwargs):
        try:
            instance = request.user.saving_calculation
        except SavingCalculation.DoesNotExist:
            instance = None

        context = self.context.copy()
        context['form'] = self.form_class(instance=instance)
        context['inv_form'] = self.inv_form_class(user=request.user)
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        try:
            instance = request.user.saving_calculation
        except SavingCalculation.DoesNotExist:
            instance = None
        
        form = self.form_class(instance=instance, data=request.POST)
        inv_form = self.inv_form_class(user=request.user, data=request.POST)

        if form.is_valid() and inv_form.is_valid():
            cleaned_data = form.cleaned_data
            inv_cleaned_data = inv_form.cleaned_data
            # updating savings instance
            if instance is None:
                instance = SavingCalculation.objects.create(user=request.user, **cleaned_data)
            else:
                SavingCalculation.objects.filter(user=request.user).update(**cleaned_data)

            # updating investment entity
            for name, pct in inv_cleaned_data.items():
                InvestmentEntity.objects.filter(saving_calculation=instance, name=name)\
                    .update(percentage=pct)
            messages.success(request, "Savings settings saved successfully!")
        else:
            messages.warning(request, "There is some error, please check fields below")

        context = self.context.copy()
        context['form'] = form
        context['inv_form'] = inv_form
        return render(request, self.template_name, context)


class InvestmentEntityCreateView(SuccessMessageMixin, LoginRequiredMixin, CreateView):
    template_name = "investment-entity-create.html"
    model = InvestmentEntity
    fields = ['name',]
    success_url = reverse_lazy('income:investment-entity-list')
    success_message = "Investment Entity Created"
    extra_context = {
        'title': 'Add Investment Entity',
    }

    def form_valid(self, form):
        obj = form.save(commit=False)
        obj.saving_calculation = self.request.user.saving_calculation
        obj.save()
        return super().form_valid(form)


class InvestmentEntityListView(LoginRequiredMixin, ListView):
    template_name = "investment-entity-list.html"
    model = InvestmentEntity
    extra_context = {
        'title': 'Investments List',
    }

    def get_queryset(self):
        return self.model.objects.filter(
            saving_calculation=self.request.user.saving_calculation,
        )


class InvestmentEntityUpdateView(SuccessMessageMixin, LoginRequiredMixin, UpdateView):
    model = InvestmentEntity
    fields = ['name',]
    template_name = "investment-entity-create.html"
    extra_context = {
        'title': 'Update Investment Entity',
    }
    success_url = reverse_lazy('income:investment-entity-list')
    success_message = "Updated successfully!"

    def get_queryset(self):
        return self.model.objects.filter(
            saving_calculation=self.request.user.saving_calculation,
        )


class InvestmentEntityDeleteView(LoginRequiredMixin, DeleteView):
    model = InvestmentEntity
    success_url = reverse_lazy('income:investment-entity-list')
    template_name = "entity-delete.html"
    extra_context = {
        'title': 'Confirm Delete',
        'success_url': success_url,
    }

    def get_queryset(self):
        return self.model.objects.filter(
            percentage=0,
            saving_calculation=self.request.user.saving_calculation,
        )


class SavingsCalculatorView(LoginRequiredMixin, View):
    form_class = SavingCalculatorForm
    inv_form_class = InvestmentEntityForm
    template_name = "savings-calculator.html"
    context = {
        'title': 'Savings Calculator',
    }

    def return_in_multiples(self, amount):
        multiples_of = DEFAULT_AMOUNT_IN_MULTIPLES_OF
        with suppress(SavingCalculation.DoesNotExist):
            multiples_of = self.request.user.saving_calculation.amount_in_multiples_of
            
        amount = int(round(amount, 0))
        final_amount = (amount // multiples_of) * multiples_of
        return final_amount

    def gen_bank_amount(self):
        MONTHS = 3
        amounts = []
        incomes = self.request.user.incomes

        days_offset = 31 * MONTHS
        today = helpers.get_ist_datetime().date()
        past = today - timedelta(days=days_offset)
        months_list = helpers.get_dates_list(past, today, day=1)
        
        for dt in months_list[:MONTHS]:
            month_income = incomes.filter(timestamp__year=dt.year, timestamp__month=dt.month)
            amounts.append(aggregate_sum(month_income))
            
        if amounts:
            return int(max(statistics.mean(amounts), *amounts[:2]))
        else:
            return 0

    def get_income(self):
        try:
            income = self.kwargs.get('income') or self.request.GET.get('income')
            return int(income.replace(',', ''))
        except (ValueError, AttributeError):
            return None

    def get(self, request, *args, **kwargs):
        user = request.user
        now = helpers.get_ist_datetime()
        initial_data = {}
        defaults_message = []
        message = ""
        
        income = self.get_income()
        if income:
            defaults_message.append(f'Income: <span class="amount">{income:,}</span>')
        
        calculator_timedelta = now - timedelta(hours=SHOW_INCOME_CALCULATOR_HOUR)
        recent_incomes = Income.objects.filter(created_at__gte=calculator_timedelta).exclude(amount=0)
        if recent_incomes.count() > 1 or (not income and recent_incomes.exists()):
            defaults_message.append(f'Recent Income: <span class="amount">{aggregate_sum(recent_incomes):,}</span>')
        
        month_income = user.incomes.filter(timestamp__year=now.year, timestamp__month=now.month)
        month_income_sum = aggregate_sum(month_income)
        defaults_message.append(f'This month\'s total income: <span class="amount">{month_income_sum:,}</span>')

        avg_expense = helpers.cal_avg_expense(user)
        if avg_expense:
            quarterly_expense = self.return_in_multiples(avg_expense/4)
            defaults_message.append(f'Average Quarterly Expense: <span class="amount">{quarterly_expense:,}</span>')

        try:
            savings = user.saving_calculation
            message = markdown.markdown(savings.message if savings.message else "")
            initial_data['savings_fixed_amount'] = savings.savings_fixed_amount
            initial_data['savings_percentage'] = savings.savings_percentage
            initial_data['amount_to_keep_in_bank'] = savings.amount_to_keep_in_bank

            BANK_AMOUNT = self.gen_bank_amount()

            if BANK_AMOUNT and not savings.amount_to_keep_in_bank:
                amount_to_keep_in_bank = self.return_in_multiples(BANK_AMOUNT * BANK_AMOUNT_PCT/100)
                if savings.auto_fill_amount_to_keep_in_bank:
                    initial_data['amount_to_keep_in_bank'] = amount_to_keep_in_bank
                    defaults_message.append(
                        f'Amount to keep in bank is <span id="bank_amount_pct">{BANK_AMOUNT_PCT}</span>%'
                        f' of <span id="bank_amount">{BANK_AMOUNT:,}</span>'
                    )
                else:
                    defaults_message.append(
                        f'[Auto] Amount to keep in bank:'
                        f' <span id="auto_amount_to_keep_in_bank">{amount_to_keep_in_bank:,}</span>'
                    )

            if income:
                savings_fixed_amount = self.return_in_multiples(income * (FIXED_SAVINGS_PCT/100))
                if not savings.savings_fixed_amount and savings.auto_fill_savings_fixed_amount:
                    initial_data['savings_fixed_amount'] = savings_fixed_amount
                    defaults_message.append(f"Savings fixed amount is {FIXED_SAVINGS_PCT}% of {income:,}")
                else:
                    defaults_message.append(
                        f'[Auto] Savings fixed amount:'
                        f' <span id="auto_savings_fixed_amount">{savings_fixed_amount:,}</span>'
                    )

        except SavingCalculation.DoesNotExist:
            pass

        context = self.context.copy()
        context['form'] = self.form_class(initial=initial_data)
        context['inv_form'] = self.inv_form_class(user=user)
        context['message'] = message
        context['defaults_message'] = defaults_message
        context['income'] = income
        return render(request, self.template_name, context)
    
    def post(self, request, *args, **kwargs):
        context = self.context.copy()
        form = self.form_class(data=request.POST)
        inv_form = self.inv_form_class(user=request.user, data=request.POST)

        if form.is_valid() and inv_form.is_valid():
            savings_fixed_amount = form.cleaned_data['savings_fixed_amount']
            savings_percentage = form.cleaned_data['savings_percentage']/100
            amount_to_keep_in_bank = form.cleaned_data['amount_to_keep_in_bank']
            bank_balance = form.cleaned_data['bank_balance']
            investment_data = inv_form.cleaned_data

            cal_amount = max(bank_balance - amount_to_keep_in_bank, 0)

            # savings calculation
            savings = savings_fixed_amount
            cal_amount -= savings
            if cal_amount < 0:
                savings += cal_amount
                cal_amount = 0
            else:
                savings_percentage_amount = cal_amount * savings_percentage
                savings += savings_percentage_amount
                cal_amount -= savings_percentage_amount

            data = {
                'savings': self.return_in_multiples(savings),
                'investment': {},
            }

            # investment calculation from here
            investment_total = 0
            for inv_name, inv_pct in investment_data.items():
                if inv_pct:
                    inv_amount = self.return_in_multiples(
                        cal_amount * (inv_pct/100)
                    )
                    data['investment'][inv_name] = inv_amount
                    investment_total += inv_amount

            context['data'] = data
            context['investment_total'] = investment_total
            context['total'] = data['savings'] + investment_total
        else:
            messages.warning(request, "There is some error, please check fields below")

        context['form'] = form
        context['inv_form'] = inv_form
        context['income'] = self.get_income()
        
        return render(request, self.template_name, context)




