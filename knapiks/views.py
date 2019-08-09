from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

# Create your views here.


@csrf_exempt
def receive_message(request):
    with open('/home/opendata/message_request.txt', 'wb') as f:
        f.write(request.body)
    return render(request, "base.html", {'request': request.body})
