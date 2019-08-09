from django.shortcuts import render

# Create your views here.


def receive_message(request):
    with open('/home/opendata/message_request.txt', 'w') as f:
        body = request.values.get('Body', None)
        f.write(body)
