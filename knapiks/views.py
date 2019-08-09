from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from knapiks.mcchat import *
from twilio.twiml.messaging_response import MessagingResponse
from django.http import HttpResponse

# Create your views here.


@csrf_exempt
def receive_message(request):
    try:
        if request.POST['From'] == '+19405947406':
            cmd_response = login_and_send(request.POST['Body'])
            resp = MessagingResponse()
            resp.message(f"{cmd_response}")
            return HttpResponse(f"{resp}")
        else:
            resp = MessagingResponse()
            resp.message("This number cannot receive messages at this time.")
            return HttpResponse(f"{resp}")
    except Exception as e:
        return render(request, "base.html", {'error': e})
