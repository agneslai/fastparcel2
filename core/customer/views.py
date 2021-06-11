import firebase_admin
from firebase_admin import credentials, auth, messaging
import stripe
import requests

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.urls import reverse

from django.contrib import messages
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash
from django.conf import settings

from core.customer import forms
from core.models import *

cred = credentials.Certificate(settings.FIREBASE_ADMIN_CREDENTIAL)
firebase_admin.initialize_app(cred)

stripe.api_key = settings.STRIPE_API_SECRET_KEY

@login_required()
def home(request):
    return redirect(reverse('customer:profile'))

@login_required(login_url="/sign-in/?next=/customer/")
def profile_page(request):
    user_form = forms.BasicUserForm(instance=request.user)
    customer_form = forms.BasicCustomerForm(instance=request.user.customer)
    password_form = PasswordChangeForm(request.user)

    if request.method == "POST":

        if request.POST.get('action') == 'update_profile':
            user_form = forms.BasicUserForm(request.POST, instance=request.user)
            customer_form = forms.BasicCustomerForm(request.POST, request.FILES, instance=request.user.customer)

            if user_form.is_valid() and customer_form.is_valid():
                user_form.save()
                customer_form.save()

                messages.success(request, 'Your profile has been updated')

                return redirect(reverse('customer:profile'))

        elif request.POST.get('action') == 'update_password':
            password_form = PasswordChangeForm(request.user, request.POST)
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                messages.success(request, 'Your password has been updated')

                return redirect(reverse('customer:profile'))

        elif request.POST.get('action') == 'update_phone':
            firebase_user = auth.verify_id_token(request.POST.get('id_token'))  

            request.user.customer.phone_number = firebase_user['phone_number']
            request.user.customer.save()
            return redirect(reverse('customer:profile')) 

    return render(request, 'customer/profile.html', {
        "user_form": user_form,
        "customer_form": customer_form,
        "password_form": password_form,
    })

@login_required(login_url="/sign-in/?next=/customer/")
def payment_method_page(request):
    current_customer = request.user.customer

    # Remove existing card
    if request.method == "POST":
        stripe.PaymentMethod.detach(current_customer.stripe_payment_method_id)
        current_customer.stripe_payment_method_id = ""
        current_customer.stripe_card_last4 = ""
        current_customer.save()
        return redirect(reverse('customer:payment_method'))


    # Save stripe customer info
    if not current_customer.stripe_customer_id:
        customer = stripe.Customer.create()
        current_customer.stripe_customer_id = customer['id']
        current_customer.save()

    #Get Stripe payment method
    stripe_payment_methods = stripe.PaymentMethod.list(
        customer = current_customer.stripe_customer_id,
        type = "card",
    )

    print(stripe_payment_methods)

    if stripe_payment_methods and len(stripe_payment_methods.data) >0:
        payment_method = stripe_payment_methods.data[0]
        current_customer.stripe_payment_method_id = payment_method.id
        current_customer.stripe_card_last4 = payment_method.card.last4
        current_customer.save()
    else:
        current_customer.stripe_payment_method_id = ""
        current_customer.stripe_card_last4 = ""
        current_customer.save()

    if not current_customer.stripe_payment_method_id:
        intent = stripe.SetupIntent.create(
            customer = current_customer.stripe_customer_id
        )

        return render(request, 'customer/payment_method.html', {
            "client_secret": intent.client_secret,
            "STRIPE_API_PUBLIC_KEY": settings.STRIPE_API_PUBLIC_KEY,
        })
    else:
        return render(request, 'customer/payment_method.html')

@login_required(login_url="/sign-in/?next=/customer/")
def create_job_page(request):
    current_customer = request.user.customer

    if not current_customer.stripe_payment_method_id:
        return redirect(reverse('customer:payment_method'))

    has_current_job = Job.objects.filter(
        customer = current_customer,
        status__in = [
            Job.PROCESSING_STATUS,
            Job.PICKING_STATUS,
            Job.DELIVERING_STATUS,
        ]
    ).exists()

    if has_current_job:
        messages.warning(request, "You currently have a processing job")
        return redirect(reverse('customer:current_jobs'))

    creating_job = Job.objects.filter(customer=current_customer, status=Job.CREATING_STATUS).last()
    step1_form = forms.JobCreateStep1Form(instance=creating_job)
    step2_form = forms.JobCreateStep2Form(instance=creating_job)
    step3_form = forms.JobCreateStep3Form(instance=creating_job)

    if request.method == 'POST':
        if request.POST.get('step') == '1':
            step1_form = forms.JobCreateStep1Form(request.POST, request.FILES, instance=creating_job)
            if step1_form.is_valid():
                creating_job = step1_form.save(commit=False)
                creating_job.customer = current_customer
                creating_job.save()
                return redirect(reverse('customer:create_job'))
        elif request.POST.get('step') == '2':
            step2_form = forms.JobCreateStep2Form(request.POST, instance=creating_job)
            if step2_form.is_valid():
                creating_job = step2_form.save()
                return redirect(reverse('customer:create_job'))
        elif request.POST.get('step') == '3':
            step3_form = forms.JobCreateStep3Form(request.POST, instance=creating_job)
            creating_job = step3_form.save()
            
            if step3_form.is_valid():
                # Get distance using Google API "Distance Matrix"
                try:
                    r = requests.get("https://maps.googleapis.com/maps/api/distancematrix/json?origins={}&destinations={}&mode=transit&key={}".format(
                        creating_job.pickup_address,
                        creating_job.delivery_address,
                        settings.GOOGLE_MAP_API_KEY
                    ))

                    print(r.json()['rows'])
                    # =>[{'elements': [{'distance': {'text': '29.3 km', 'value': 29318}, 'duration': {'text': '1 hour 7 mins', 'value': 4008}, 'status': 'OK'}]}]
                    
                    result = r.json()['rows']

                    distance = result[0]['elements'][0]['distance']['value']
                    duration = result[0]['elements'][0]['duration']['value']
                    creating_job.distance = round(distance/1000, 2)
                    creating_job.duration = int(duration/60)
                    creating_job.price = creating_job.distance * 1 # $1 per km
                    creating_job.save()

                except Exception as e:
                    print(e)
                    messages.error(request, "Unfotunately, we do not support shipping at this distance")

                # creating_job = step3_form.save()
                return redirect(reverse('customer:create_job'))
        elif request.POST.get('step') == '4':
            if creating_job.price:
                try:

                    # Step 1: create payment intent
                    payment_intent = stripe.PaymentIntent.create(
                            amount=int(creating_job.price * 100),
                            currency='hkd',
                            customer=current_customer.stripe_customer_id,
                            payment_method=current_customer.stripe_payment_method_id,
                            off_session=True,
                            confirm=True,
                        )

                    # Step 2: Create transaction
                    Transaction.objects.create(
                            stripe_payment_intent_id = payment_intent['id'],
                            job = creating_job,
                            amount = creating_job.price,
                        )

                    # Step 3: Update job status
                    creating_job.status = Job.PROCESSING_STATUS
                    creating_job.save()

                    # Step 4: Send Push Notification to All Courier
                    couriers = Courier.objects.all()
                    registration_tokens = [i.fcm_token for i in couriers if i.fcm_token]

                    message = messaging.MulticastMessage(
                        notification = messaging.Notification(
                            title = creating_job.name,
                            body = creating_job.description
                        ),
                        webpush = messaging.WebpushConfig(
                            notification = messaging.WebpushNotification(
                                icon = creating_job.photo.url,
                            ),
                            fcm_options = messaging.WebpushFCMOptions(
                                link = settings.NOTIFICATION_URL + reverse('courier:available_jobs'),
                            ),
                        ),
                        tokens = registration_tokens
                    )
                    response = messaging.send_multicast(message)
                    print('{0} messages were sent successfully'.format(response.success_count))

                    return redirect(reverse('customer:home'))

                except stripe.error.CardError as e:
                    err = e.error
                    # Error code will be authentication_required if authentication is needed
                    print("Code is: %s" % err.code)
                    payment_intent_id = err.payment_intent['id']
                    payment_intent = stripe.PaymentIntent.retrieve(payment_intent_id)



    # Determine the current step 
    if not creating_job:
        current_step = 1
    elif creating_job.delivery_name:
        current_step = 4
    elif creating_job.pickup_name:
        current_step = 3
    else:
        current_step = 2

    return render(request, 'customer/create_job.html', {
        "job": creating_job,
        "step": current_step,
        "step1_form": step1_form,
        "step2_form": step2_form,
        "step3_form": step3_form,
        "GOOGLE_MAP_API_KEY": settings.GOOGLE_MAP_API_KEY,
    })

@login_required(login_url="/sign-in/?next=/customer/")
def current_jobs_page(request):
    jobs = Job.objects.filter(
        customer = request.user.customer,
        status__in=[
            Job.PROCESSING_STATUS,
            Job.PICKING_STATUS,
            Job.DELIVERING_STATUS,
        ]
    )
    return render(request, 'customer/jobs.html', {
        "jobs": jobs
    })

@login_required(login_url="/sign-in/?next=/customer/")
def archived_jobs_page(request):
    jobs = Job.objects.filter(
        customer = request.user.customer,
        status__in=[
            Job.COMPLETED_STATUS,
            Job.CANCELED_STATUS,
        ]
    )

    return render(request, 'customer/jobs.html', {
        "jobs": jobs
    })

@login_required(login_url="/sign-in/?next=/customer/")
def job_page(request, job_id):
    job = Job.objects.get(id=job_id)

    if request.method == 'POST' and job.status == Job.PROCESSING_STATUS:
        job.status = Job.CANCELED_STATUS
        job.save()
        return redirect(reverse('customer:archived_jobs'))

    return render(request, 'customer/job.html', {
        "job": job,
        'GOOGLE_MAP_API_KEY': settings.GOOGLE_MAP_API_KEY,
    })
