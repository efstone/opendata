import base64
import ftplib
from Crypto.Cipher import XOR
from django.conf import settings
from knapiks.models import *
import knapiks.mcrcon as mcrcon
import pytz
from django.utils import timezone
from datetime import datetime
import re
from django.db.utils import IntegrityError
from docketdata.celery import app
from twilio.rest import Client
import glob
import os

twilio_client = Client(settings.TWILIO_ACCT_SID, settings.TWILIO_AUTH_TOKEN)
admin_phone = Config.objects.get(mc_key='admin_phone').mc_value
twilio_phone = Config.objects.get(mc_key='twilio_phone').mc_value


class MyFTP_TLS(ftplib.FTP_TLS):
    """Explicit FTPS, with shared TLS session"""

    # special thanks to https://stackoverflow.com/users/448474/hynekcer for this class
    # this was the easy fix for the "session reuse required" error that was happening
    # with Python's native FTP_TLS class

    def ntransfercmd(self, cmd, rest=None):
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p:
            conn = self.context.wrap_socket(conn,
                                            server_hostname=self.host,
                                            session=self.sock.session)
        return conn, size


def mc_encrypt(plaintext, cipher_key):
    cipher = XOR.new(cipher_key)
    return base64.b64encode(cipher.encrypt(plaintext)).decode()


def mc_decrypt(ciphertext, cipher_key):
    cipher = XOR.new(cipher_key)
    return cipher.decrypt(base64.b64decode(ciphertext)).decode()


def get_latest_log():
    mc_key = settings.MC_KEY
    ftp_host = Config.objects.get(mc_key='ftp_host').mc_value
    ftp_login = Config.objects.get(mc_key='ftp_login').mc_value
    ftp_pw_crypt = Config.objects.get(mc_key='ftp_password').mc_value
    mc_ftp = MyFTP_TLS(ftp_host)
    mc_ftp.login(ftp_login, mc_decrypt(ftp_pw_crypt, mc_key))
    mc_ftp.prot_p()
    mc_log = []
    mc_ftp.retrlines('RETR /minecraft/logs/latest.log', mc_log.append)
    return mc_log


def login_and_send(command):
    mc_key = settings.MC_KEY
    rcon_host = Config.objects.get(mc_key='rcon_host').mc_value
    rcon_port = Config.objects.get(mc_key='rcon_port').mc_value
    rcon_pw_crypt = Config.objects.get(mc_key='rcon_password').mc_value
    try:
        mc = mcrcon.login(rcon_host, int(rcon_port), mc_decrypt(rcon_pw_crypt, mc_key))
        cmd = mcrcon.command(mc, command)
        return cmd
    except Exception as e:
        mc.close()
        return e


@app.task
def process_current_log():
    log = get_latest_log()
    rcon_pat = re.compile('Rcon connection from')
    mc_log_pat = re.compile('\[(\d\d:\d\d:\d\d)] \[(.+?)\]: (.*)')
    for line in log:
        log_re = re.match(mc_log_pat, line)
        try:
            msg_time_text = log_re.group(1)
            msg_type = log_re.group(2)
            msg_content = log_re.group(3)
        except Exception as e:
            print(f"{e} on line: {line}")
            continue
        utc_tz = pytz.timezone('UTC')
        msg_time = datetime.combine(timezone.now().date(), datetime.strptime(msg_time_text, "%H:%M:%S").time())
        if re.match(rcon_pat, msg_content) is None:
            new_msg = Log()
            new_msg.msg_time = utc_tz.localize(msg_time)
            new_msg.msg_content = msg_content
            new_msg.msg_type = msg_type
        else:
            continue
        try:
            new_msg.save()
        except IntegrityError:
            continue


@app.task
def check_for_players():
    # this is typically to be run every minute
    # check if anyone is logged in
    result = login_and_send('list')
    players_without_logout_timestamps = []
    all_players = Player.objects.all()
    player_pat = re.compile('[^ ]+')

    # collect list of players in local db who appear to be logged in based on login/logout timestamps
    for player in all_players:
        if player.last_login > player.last_logout:
            players_without_logout_timestamps.append(player)

    # if no one is actually logged in, but the local db indicates someone may be logged in, process the current log
    # and mark them as logged out and send the sysop a message that they're logged out
    if result == 'There are 0 of a max 20 players online: ' and len(players_without_logout_timestamps) > 0:
        process_current_log()
        for player in players_without_logout_timestamps:
            last_logout = Log.objects.filter(msg_content=f'{player.name} left the game').last()
            player.last_logout = last_logout.msg_time
            player.save()
            last_logout.msg_twilled = timezone.now()
            last_logout.save()
            sms = twilio_client.messages.create(
                from_=f'+{twilio_phone}',
                body=f'{player} logged out',
                to=f'+{admin_phone}'
            )

    # if someone is logged in, process the log to  check for chats, logins and logouts--if any are found,
    # send them to sysop in chronological order
    if result != 'There are 0 of a max 20 players online: ':
        process_current_log()
        msg_list = []
        # process logins first and update the player model
        unsent_logins = Log.objects.filter(msg_content__contains='joined the game', msg_twilled=None)
        for msg in unsent_logins:
            player_name = re.match(player_pat, msg.msg_content).group()
            try:
                player = Player.objects.get_or_create(name=player_name)[0]
                player.last_login = msg.msg_time
                player.save()
                msg_list.append(msg.id)
            except Exception as e:
                print(e)
            msg.msg_twilled = timezone.now()
            msg.save()

        # then grab chats and logouts
        unsent_chats = Log.objects.filter(msg_content__startswith='<', msg_twilled=None)
        logouts = Log.objects.filter(msg_content__startswith='left the game', msg_twilled=None)
        unsent_chats_and_logouts = unsent_chats | logouts
        msgs_to_send = unsent_chats_and_logouts

        for msg in msgs_to_send:
            msg_list.append(msg.id)
            msg.msg_twilled = timezone.now()
            msg.save()

        if len(msg_list) > 0:
            messages_to_send = Log.objects.filter(id__in=msg_list)
            messages = '\n'.join([msg_to_send.msg_content for msg_to_send in messages_to_send])
            sms = twilio_client.messages.create(
                from_=f'+{twilio_phone}',
                body=f'{messages}',
                to=f'+{admin_phone}'
            )

    print(result)


def process_mc_log_files(log_dir):
    log_files = glob.glob(f'{log_dir}/*.log')
    date_pat = re.compile('\d{4}-\d{2}-\d{2}')
    rcon_pat = re.compile('Rcon connection from')
    mc_log_pat = re.compile('\[(\d\d:\d\d:\d\d)] \[(.+?)\]: (.*)')
    for log_file in log_files:
        log_date_str_search = re.match(date_pat, os.path.basename(log_file))
        if log_date_str_search is None:
            continue
        else:
            log_date_str = log_date_str_search.group()
            with open(log_file, 'r') as f:
                log_content = f.read()
                log = log_content.split('\n')
        for line in log:
            log_re = re.match(mc_log_pat, line)
            try:
                msg_time_text = log_re.group(1)
                msg_type = log_re.group(2)
                msg_content = log_re.group(3)
            except Exception as e:
                print(f"{e} on line: {line}")
                continue
            utc_tz = pytz.timezone('UTC')
            msg_time = datetime.combine(datetime.strptime(log_date_str, "%Y-%m-%d").date(), datetime.strptime(msg_time_text, "%H:%M:%S").time())
            if re.match(rcon_pat, msg_content) is None:
                new_msg = Log()
                new_msg.msg_time = utc_tz.localize(msg_time)
                new_msg.msg_content = msg_content
                new_msg.msg_type = msg_type
            else:
                continue
            try:
                new_msg.save()
            except IntegrityError:
                continue
