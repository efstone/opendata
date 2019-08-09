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


class MyFTP_TLS(ftplib.FTP_TLS):
    """Explicit FTPS, with shared TLS session"""

    def ntransfercmd(self, cmd, rest=None):
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p:
            conn = self.context.wrap_socket(conn,
                                            server_hostname=self.host,
                                            session=self.sock.session)  # this is the fix
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
    mc_log_pat = re.compile('\[(\d\d:\d\d:\d\d)] \[(.+?)\]: (.*)')
    for line in log:
        log_re = re.match(mc_log_pat, line)
        msg_time_text = log_re.group(1)
        msg_type = log_re.group(2)
        msg_content = log_re.group(3)
        utc_tz = pytz.timezone('UTC')
        msg_time = datetime.combine(timezone.now().date(), datetime.strptime(msg_time_text, "%H:%M:%S").time())
        new_msg = McLog()
        new_msg.msg_time = utc_tz.localize(msg_time)
        new_msg.msg_content = msg_content
        new_msg.msg_type = msg_type
        try:
            new_msg.save()
        except IntegrityError:
            continue
