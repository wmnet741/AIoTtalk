
"""System utilities used by the sipclient scripts"""

__all__ = ['IPAddressMonitor']

from application.notification import NotificationCenter, NotificationData
from application.system import host
from eventlib import api

from sipsimple.threading import run_in_twisted_thread
from sipsimple.threading.green import run_in_green_thread


class IPAddressMonitor(object):
    """
    An object which monitors the IP address used for the default route of the
    host and posts a SystemIPAddressDidChange notification when a change is
    detected.
    """

    def __init__(self):
        self.greenlet = None

    @run_in_green_thread
    def start(self):
        notification_center = NotificationCenter()

        if self.greenlet is not None:
            return
        self.greenlet = api.getcurrent()

        current_address = host.default_ip
        while True:
            new_address = host.default_ip
            # make sure the address stabilized
            api.sleep(5)
            if new_address != host.default_ip:
                continue
            if new_address != current_address:
                notification_center.post_notification(name='SystemIPAddressDidChange', sender=self, data=NotificationData(old_ip_address=current_address, new_ip_address=new_address))
                current_address = new_address
            api.sleep(5)

    @run_in_twisted_thread
    def stop(self):
        if self.greenlet is not None:
            api.kill(self.greenlet, api.GreenletExit())
            self.greenlet = None



