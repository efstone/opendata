import base64
import ftplib
from Crypto.Cipher import AES
from django.conf import settings
from knapiks.models import *
import knapiks.mcrcon as mcrcon
import pytz
from django.utils import timezone
from datetime import datetime, timedelta
import re
from django.db.utils import IntegrityError
from docketdata.celery import app
from twilio.rest import Client
import glob
import os

TWILIO_CLIENT = Client(settings.TWILIO_ACCT_SID, settings.TWILIO_AUTH_TOKEN)
ADMIN_PHONE = Config.objects.get(mc_key='admin_phone').mc_value
TWILIO_PHONE = Config.objects.get(mc_key='twilio_phone').mc_value
CRYPT_KEY = settings.CRYPT_KEY
RCON_HOST = Config.objects.get(mc_key='rcon_host').mc_value
RCON_PORT = Config.objects.get(mc_key='rcon_port').mc_value
RCON_PW_CRYPT = Config.objects.get(mc_key='rcon_password').mc_value


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


# def mc_encrypt(plaintext):
#     cipher = AES.new(DECRYPT_KEY, AES.MODE_EAX)
#     return base64.b64encode(cipher.encrypt(plaintext)).decode()


def mc_encrypt(text, sec_key):
    pad = 16 - len(text) % 16
    text = text + chr(8) * pad
    encryptor = AES.new(sec_key.encode('utf-8'), AES.MODE_CBC, b'0102030405060708')
    cipher_text = encryptor.encrypt(text.encode('utf-8'))
    cipher_text = base64.b64encode(cipher_text).decode('utf-8')
    return cipher_text


def mc_decrypt(text, sec_key):
    encryptor = AES.new(sec_key.encode('utf-8'), AES.MODE_CBC, b'0102030405060708')
    cipher_text = base64.b64decode(text.encode('utf-8'))
    cipher_text = encryptor.decrypt(cipher_text).strip(b'\x08').decode('utf-8')
    return cipher_text


# def mc_decrypt(ciphertext, cipher_key):
#     cipher = strxor.new(cipher_key)
#     return cipher.decrypt(base64.b64decode(ciphertext)).decode()


def get_latest_log():
    ftp_host = Config.objects.get(mc_key='ftp_host').mc_value
    ftp_login = Config.objects.get(mc_key='ftp_login').mc_value
    ftp_pw_crypt = Config.objects.get(mc_key='ftp_password').mc_value
    try:
        with MyFTP_TLS(ftp_host, timeout=30) as mc_ftp:
            try:
                retrieve_start = timezone.now()
                mc_ftp.login(ftp_login, mc_decrypt(ftp_pw_crypt, CRYPT_KEY))
                mc_ftp.prot_p()
                mc_log = []
                mc_ftp.retrlines('RETR /minecraft/logs/latest.log', mc_log.append)
                retrieve_end = timezone.now()
                print(f"ftp_retrieval_time: {retrieve_end - retrieve_start}")
                return mc_log
            except Exception as login_error:
                print(f"Login/download failed with error: {login_error}")
    except Exception as connection_error:
        print(f"Connection failed with error: {connection_error}")


def login_and_send(command):
    try:
        mc = mcrcon.login(RCON_HOST, int(RCON_PORT), mc_decrypt(RCON_PW_CRYPT, CRYPT_KEY))
        cmd = mcrcon.command(mc, command)
        return cmd
    except Exception as e:
        try:
            mc.close()
        except Exception as e:
            pass
        return e


@app.task
def process_current_log():
    log = get_latest_log()
    msgs_to_omit_pat = re.compile('(Rcon connection from|Sav.{2,3} the game|Can\'t keep up!)')
    mc_log_pat = re.compile('\[(\d\d:\d\d:\d\d)] \[(.+?)\]: (.*)')
    utc_tz = pytz.timezone('UTC')
    for line in log:
        known_bad_lines_pat = re.compile('(^Botania|^Chameleon|^Storage)')
        if re.match(known_bad_lines_pat, line) is not None:
            continue
        log_re = re.match(mc_log_pat, line)
        try:
            msg_time_text = log_re.group(1)
            msg_type = log_re.group(2)
            msg_content = log_re.group(3)
        except Exception as e:
            print(f"{e} on line: {line}")
            continue
        msg_time = datetime.combine(timezone.now().date(), datetime.strptime(msg_time_text, "%H:%M:%S").time())
        if re.match(msgs_to_omit_pat, msg_content) is None:
            new_msg = Log()
            new_msg.msg_time = utc_tz.localize(msg_time)
            new_msg.msg_content = msg_content
            new_msg.msg_type = msg_type
            try:
                new_msg.save()
            except IntegrityError:
                continue
        else:
            continue


@app.task
def check_for_players():
    # this is typically to be run every minute
    # check if anyone is logged in
    result = login_and_send('list')
    players_without_logout_timestamps = []
    all_players = Player.objects.all()
    player_pat = re.compile('[^ ]+')
    player_dialog_pat = re.compile('^(?:<)([^>]+)')

    # collect list of players in local db who appear to be logged in based on login/logout timestamps
    for player in all_players.exclude(last_logout=None):
        if player.last_login > player.last_logout:
            players_without_logout_timestamps.append(player)

    for player in all_players.filter(last_logout=None):
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
            sms = TWILIO_CLIENT.messages.create(
                from_=f'+{TWILIO_PHONE}',
                body=f'{player} logged out',
                to=f'+{ADMIN_PHONE}'
            )

    # if someone is logged in, process the log to check for chats, logins and logouts--if any are found,
    # send them to sysop in chronological order
    if result != 'There are 0 of a max 20 players online: ':
        process_current_log()
        msg_list = []
        teleport_pat = re.compile('jarvis[, ]+(teleport|tp) (\w+) to (\d+)+ (\d+)+ (\d+)+', re.IGNORECASE)
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
        logouts = Log.objects.filter(msg_content__endswith='left the game', msg_twilled=None)
        unsent_chats_and_logouts = unsent_chats | logouts
        msgs_to_send = unsent_chats_and_logouts

        for msg in msgs_to_send:
            msg_list.append(msg.id)
            msg.msg_twilled = timezone.now()
            msg.save()

            teleport_search = re.search(teleport_pat, msg.msg_content)
            if teleport_search is not None:
                try:
                    if teleport_search.group(2) == 'me':
                        character = re.match(player_dialog_pat, msg.msg_content).group(1)
                    login_and_send(f'teleport {character} {teleport_search.group(3)} {teleport_search.group(4)} {teleport_search.group(5)}')
                except Exception as E:
                    print(E)

        if len(msg_list) > 0:
            messages_to_send = Log.objects.filter(id__in=msg_list)
            messages = '\n'.join([msg_to_send.msg_content for msg_to_send in messages_to_send])
            sms = TWILIO_CLIENT.messages.create(
                from_=f'+{TWILIO_PHONE}',
                body=f'{messages[:1550]}',
                to=f'+{ADMIN_PHONE}'
            )

    print(result)


def process_mc_log_files(log_dir):
    log_files = glob.glob(f'{log_dir}/*.log')
    date_pat = re.compile('\d{4}-\d{2}-\d{2}')
    msgs_to_omit_pat = re.compile('(Rcon connection from|Sav.{2,3} the game|Can\'t keep up!)')
    mc_log_pat = re.compile('\[(\d\d:\d\d:\d\d)] \[(.+?)\]: (.*)')
    utc_tz = pytz.timezone('UTC')
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
            known_bad_lines_pat = re.compile('(^Botania|^Chameleon|^Storage)')
            if re.match(known_bad_lines_pat, line) is not None:
                continue
            log_re = re.match(mc_log_pat, line)
            try:
                msg_time_text = log_re.group(1)
                msg_type = log_re.group(2)
                msg_content = log_re.group(3)
            except Exception as e:
                print(f"{e} on line: {line}")
                continue
            msg_time = datetime.combine(datetime.strptime(log_date_str, "%Y-%m-%d").date(), datetime.strptime(msg_time_text, "%H:%M:%S").time())
            if re.match(msgs_to_omit_pat, msg_content) is None:
                new_msg = Log()
                new_msg.msg_time = utc_tz.localize(msg_time)
                new_msg.msg_content = msg_content
                new_msg.msg_type = msg_type
                try:
                    new_msg.save()
                except IntegrityError:
                    continue
            else:
                continue
