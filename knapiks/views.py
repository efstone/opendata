from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

# Create your views here.


@csrf_exempt
def receive_message(request):
    message = {}
    message['From'] = request.POST['From']
    message['Body'] = request.POST['Body']
    with open('/home/opendata/message_request.txt', 'w') as f:
        f.write(f"{message})
    return render(request, "base.html", {'request': request.body})
