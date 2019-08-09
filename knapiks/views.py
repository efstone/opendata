from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from knapiks.mcchat import *
from twilio.twiml.messaging_response import MessagingResponse


# Create your views here.


@csrf_exempt
def receive_message(request):
    if request.POST['From'] == '+19405947406':
        login_and_send(request.POST['Body'])
        return
    else:
        resp = MessagingResponse()
        resp.message("This number cannot receive messages at this time.")
    return f"{resp}"
