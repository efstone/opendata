from django.shortcuts import render

# Create your views here.


def receive_message(request):
    with open('/home/opendata/message_request.txt', 'w') as f:
        f.write(request.POST)
    return render(request, "base.html", {'request': request.POST})
