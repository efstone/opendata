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
    ftp_host = MCConfig.objects.get(mc_key='ftp_host').mc_value
    ftp_login = MCConfig.objects.get(mc_key='ftp_login').mc_value
    ftp_pw_crypt = MCConfig.objects.get(mc_key='ftp_password').mc_value
    mc_ftp = MyFTP_TLS(ftp_host)
    mc_ftp.login(ftp_login, mc_decrypt(ftp_pw_crypt, mc_key))
    mc_ftp.prot_p()
    mc_log = []
    mc_ftp.retrlines('RETR /minecraft/logs/latest.log', mc_log.append)
    return mc_log


def login_and_send(command):
    mc_key = settings.MC_KEY
    rcon_host = MCConfig.objects.get(mc_key='rcon_host').mc_value
    rcon_port = MCConfig.objects.get(mc_key='rcon_port').mc_value
    rcon_pw_crypt = MCConfig.objects.get(mc_key='rcon_password').mc_value
    try:
        mc = mcrcon.login(rcon_host, int(rcon_port), mc_decrypt(rcon_pw_crypt, mc_key))
        cmd = mcrcon.command(mc, command)
        return cmd
    except Exception as e:
        mc.close()
        return e


def process_current_log():
    log = get_latest_log()
    rcon_pat = re.compile('Rcon connection from')
    mc_log_pat = re.compile('\[(\d\d:\d\d:\d\d)] \[(.+?)\]: (.*)')
    for line in log:
        log_re = re.match(mc_log_pat, line)
        msg_time_text = log_re.group(1)
        msg_type = log_re.group(2)
        msg_content = log_re.group(3)
        utc_tz = pytz.timezone('UTC')
        msg_time = datetime.combine(timezone.now().date(), datetime.strptime(msg_time_text, "%H:%M:%S").time())
        if re.match(rcon_pat, msg_content) is None:
            new_msg = McLog()
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
    to_number = MCConfig.objects.get(mc_key='to_num').mc_value
    from_number = MCConfig.objects.get(mc_key='from_num').mc_value
    player_pat = re.compile('[^ ]+')
    result = login_and_send('list')
    client = Client(settings.TWILIO_ACCT_SID, settings.TWILIO_AUTH_TOKEN)
    if result != 'There are 0 of a max 20 players online: ':
        process_current_log()
        unsent_logins = McLog.objects.filter(msg_content__contains='joined the game', msg_twilled=None)
        for msg in unsent_logins:
            player_name = re.match(player_pat, msg.msg_content).group()
            message = client.messages.create(
                from_=f'+{from_number}',
                body=f'{player_name} logged in.',
                to=f'+{to_number}'
            )
            msg.msg_twilled = timezone.now()
            msg.save()
        unsent_chats = McLog.objects.filter(msg_content__startswith='<', msg_twilled=None)
        logouts = McLog.objects.filter(msg_content__contains='left the game', msg_twilled=None)
        chat_list = []
        msgs_to_send = unsent_chats | logouts
        for chat in msgs_to_send:
            chat_list.append(chat.msg_content)
            chat.msg_twilled = timezone.now()
            chat.save()
        if len(chat_list) > 0:
            chats = '\n'.join(chat_list)
            message = client.messages.create(
                from_=f'+{from_number}',
                body=f'{chats}',
                to=f'+{to_number}'
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
            except:
                print(line)
                continue
            try:
                msg_type = log_re.group(2)
            except:
                print(line)
                continue
            try:
                msg_content = log_re.group(3)
            except:
                print(line)
                continue
            utc_tz = pytz.timezone('UTC')
            msg_time = datetime.combine(datetime.strptime(log_date_str, "%Y-%m-%d").date(), datetime.strptime(msg_time_text, "%H:%M:%S").time())
            if re.match(rcon_pat, msg_content) is None:
                new_msg = McLog()
                new_msg.msg_time = utc_tz.localize(msg_time)
                new_msg.msg_content = msg_content
                new_msg.msg_type = msg_type
            else:
                continue
            try:
                new_msg.save()
            except IntegrityError:
                continue
