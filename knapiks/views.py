from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from knapiks.mcchat import *
from twilio.twiml.messaging_response import MessagingResponse
from django.http import HttpResponse

# Create your views here.


@csrf_exempt
def receive_message(request):
    from_number = MCConfig.objects.get(mc_key='from_num').mc_value
    cmds_pat = re.compile(
        '(advancement|ban|ban-ip|banlist|bossbar|clear|clone|data|datapack|debug|defaultgamemode|deop|difficulty|effect|enchant|execute|experience|fill|forceload|function|gamemode|gamerule|give|help|kick|kill|list|locate|loot|me|msg|op|pardon|particle|playsound|publish|recipe|reload|replaceitem|save-all|save-off|save-on|schedule|scoreboard|seed|setblock|setidletimeout|setworldspawn|spawnpoint|spreadplayers|stop|stopsound|summon|tag|team|teleport|teammsg|tell|tellraw|time|title|tp|trigger|weather|whitelist|worldborder|xp)')
    try:
        if request.POST['From'] == f'+{from_number}':
            if re.match(cmds_pat, request.POST['Body']) is None:
                cmd_response = login_and_send(f"say {request.POST['Body']}")
            else:
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
