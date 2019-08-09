from django.shortcuts import render

# Create your views here.


def receive_message(request):
    with open('/home/opendata/message_request.txt', 'wb') as f:
        f.write(str(request.body))
    return render(request, "base.html", {'request': request.body})
