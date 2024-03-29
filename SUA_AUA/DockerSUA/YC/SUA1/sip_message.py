
# -*- coding: UTF-8 -*-
# coding: UTF-8 

__all__ = ['InputThread', 'SIPMessageApplication']

import atexit
import os
import select
import signal
import sys, traceback
import termios

from datetime import datetime
from optparse import OptionParser
from threading import Thread
from time import sleep

from application import log
from application.notification import NotificationCenter, NotificationData
from application.python.queue import EventQueue

from sipsimple.core import FromHeader, Message, RouteHeader, SIPCoreError, SIPURI, ToHeader

from sipsimple.account import Account, AccountManager, BonjourAccount
from sipsimple.application import SIPApplication
from sipsimple.configuration import ConfigurationError
from sipsimple.configuration.settings import SIPSimpleSettings
from sipsimple.lookup import DNSLookup
from sipsimple.storage import FileStorage

from sip_dir import account_config
from sip_log import Logger
from sip_system import IPAddressMonitor

import ntplib 
import time

class InputThread(Thread):
	def __init__(self, read_message, batch_mode):
		Thread.__init__(self)
		self.setDaemon(True)
		self.read_message = read_message
		self.batch_mode = batch_mode
		self._old_terminal_settings = None

	def start(self):
		atexit.register(self._termios_restore)
		Thread.start(self)

	def run(self):
		notification_center = NotificationCenter()
		
		if self.read_message:
			lines = []
			try:
				while True:
					lines.append(raw_input())
			except EOFError:
				message = '\n'.join(lines)
				notification_center.post_notification('SIPApplicationGotInputMessage', sender=self, data=NotificationData(message=message))

		if not self.batch_mode:
			while True:
				chars = list(self._getchars())
				while chars:
					char = chars.pop(0)
					if char == '\x1b': # escape
						if len(chars) >= 2 and chars[0] == '[' and chars[1] in ('A', 'B', 'C', 'D'): # one of the arrow keys
							char = char + chars.pop(0) + chars.pop(0)
					notification_center.post_notification('SIPApplicationGotInput', sender=self, data=NotificationData(input=char))

	def stop(self):
		self._termios_restore()

	def _termios_restore(self):
		if self._old_terminal_settings is not None:
			termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self._old_terminal_settings)

	def _getchars(self):
		fd = sys.stdin.fileno()
		if os.isatty(fd):
			self._old_terminal_settings = termios.tcgetattr(fd)
			new = termios.tcgetattr(fd)
			new[3] = new[3] & ~termios.ICANON & ~termios.ECHO
			new[6][termios.VMIN] = '\000'
			try:
				termios.tcsetattr(fd, termios.TCSADRAIN, new)
				if select.select([fd], [], [], None)[0]:
					return sys.stdin.read(4192)
			finally:
				self._termios_restore()
		else:
			return os.read(fd, 4192)


class SIPMessageApplication(SIPApplication):
	def __init__(self):
		self.account = None
		self.options = None
		self.target = None
		
		self.routes = []
		self.registration_succeeded = False
		
		self.input =  None
		self.output = None
		self.ip_address_monitor = IPAddressMonitor()
		self.logger = None
		#self.count =0

	def _write(self, message):
		if isinstance(message, unicode):
			message = message.encode(sys.getfilesystemencoding())
		sys.stdout.write(message)
		sys.stdout.flush()

	def start(self, target, options):
		notification_center = NotificationCenter()
		
		self.options = options
		self.message = options.message
		self.target = target
		self.input = InputThread(read_message=self.target is not None and options.message is None, batch_mode=options.batch_mode)
		self.output = EventQueue(self._write)
		self.logger = Logger(sip_to_stdout=options.trace_sip, pjsip_to_stdout=options.trace_pjsip, notifications_to_stdout=options.trace_notifications)
		#self.book = options.book
		#self.sheet = options.sheet
		#self.count = options.count

		#with open('print.txt', "a+") as f:
		#	f.write("message: %s\n" % (self.message))

		notification_center.add_observer(self, sender=self)
		notification_center.add_observer(self, sender=self.input)
		notification_center.add_observer(self, name='SIPEngineGotMessage')

		if self.input:
			self.input.start()
		self.output.start()

		log.level.current = log.level.WARNING # get rid of twisted messages

		try:
			SIPApplication.start(self, FileStorage(account_config))
		except ConfigurationError, e:
			with open('print.txt', "a+") as f:
				f.write("Failed to load sipclient's configuration: %s\n" % str(e))
			#self.output.put("Failed to load sipclient's configuration: %s\n" % str(e))
			#self.output.put("If an old configuration file is in place, delete it or move it and recreate the configuration using the sip_settings script.\n")
			self.output.stop()

	def _NH_SIPApplicationWillStart(self, notification):
		account_manager = AccountManager()
		notification_center = NotificationCenter()
		settings = SIPSimpleSettings()

		for account in account_manager.iter_accounts():
			if isinstance(account, Account):
				account.sip.register = False
		if self.options.account is None:
			self.account = account_manager.default_account
		else:
			possible_accounts = [account for account in account_manager.iter_accounts() if self.options.account in account.id and account.enabled]
			if len(possible_accounts) > 1:
				self.output.put('More than one account exists which matches %s: %s\n' % (self.options.account, ', '.join(sorted(account.id for account in possible_accounts))))
				self.output.stop()
				self.stop()
				return
			elif len(possible_accounts) == 0:
				self.output.put('No enabled account that matches %s was found. Available and enabled accounts: %s\n' % (self.options.account, ', '.join(sorted(account.id for account in account_manager.get_accounts() if account.enabled))))
				self.output.stop()
				self.stop()
				return
			else:
				self.account = possible_accounts[0]
		if isinstance(self.account, Account) and self.target is None:
			self.account.sip.register = True
			notification_center.add_observer(self, sender=self.account)
		with open('print.txt', "a+") as f:
			f.write('Using account %s\n' % self.account.id)
		#self.output.put('Using account %s\n' % self.account.id)

	def _NH_SIPApplicationDidStart(self, notification):
		notification_center = NotificationCenter()
		settings = SIPSimpleSettings()

		self.ip_address_monitor.start()

		if isinstance(self.account, BonjourAccount) and self.target is None:
			for transport in settings.sip.transport_list:
				try:
					self.output.put('Listening on: %s\n' % self.account.contact[transport])
				except KeyError:
					pass

		if self.target is not None:
			if '@' not in self.target:
				self.target = '%s@%s' % (self.target, self.account.id.domain)
			if not self.target.startswith('sip:') and not self.target.startswith('sips:'):
				self.target = 'sip:' + self.target
			try:
				self.target = SIPURI.parse(self.target)
			except SIPCoreError:
				self.output.put('Illegal SIP URI: %s\n' % self.target)
				self.stop()
			if self.message is None:
				self.output.put('Press Ctrl+D on an empty line to end input and send the MESSAGE request.\n')
			else:
				settings = SIPSimpleSettings()
				lookup = DNSLookup()
				notification_center.add_observer(self, sender=lookup)
				if isinstance(self.account, Account) and self.account.sip.outbound_proxy is not None:
					uri = SIPURI(host=self.account.sip.outbound_proxy.host, port=self.account.sip.outbound_proxy.port, parameters={'transport': self.account.sip.outbound_proxy.transport})
				elif isinstance(self.account, Account) and self.account.sip.always_use_my_proxy:
					uri = SIPURI(host=self.account.id.domain)
				else:
					uri = self.target
				lookup.lookup_sip_proxy(uri, settings.sip.transport_list)
		else:
			self.output.put('Press Ctrl+D to stop the program.\n')

	def _NH_SIPApplicationWillEnd(self, notification):
		self.ip_address_monitor.stop()

	def _NH_SIPApplicationDidEnd(self, notification):
		if self.input:
			self.input.stop()
		self.output.stop()
		self.output.join()

	def _NH_SIPApplicationGotInput(self, notification):
		if notification.data.input == '\x04':
			self.stop()

	def _NH_SIPApplicationGotInputMessage(self, notification):
		if not notification.data.message:
			self.stop()
		else:
			notification_center = NotificationCenter()
			settings = SIPSimpleSettings()
			self.message = notification.data.message
			lookup = DNSLookup()
			notification_center.add_observer(self, sender=lookup)
			if isinstance(self.account, Account) and self.account.sip.outbound_proxy is not None:
				uri = SIPURI(host=self.account.sip.outbound_proxy.host, port=self.account.sip.outbound_proxy.port, parameters={'transport': self.account.sip.outbound_proxy.transport})
			elif isinstance(self.account, Account) and self.account.sip.always_use_my_proxy:
				uri = SIPURI(host=self.account.id.domain)
			else:
				uri = self.target
			lookup.lookup_sip_proxy(uri, settings.sip.transport_list)

	def _NH_SIPEngineGotException(self, notification):
		self.output.put('An exception occured within the SIP core:\n%s\n' % notification.data.traceback)

	def _NH_SIPAccountRegistrationDidSucceed(self, notification):
		if self.registration_succeeded:
			return
		contact_header = notification.data.contact_header
		contact_header_list = notification.data.contact_header_list
		expires = notification.data.expires
		registrar = notification.data.registrar
		message = '%s Registered contact "%s" for sip:%s at %s:%d;transport=%s (expires in %d seconds).\n' % (datetime.now().replace(microsecond=0), contact_header.uri, self.account.id, registrar.address, registrar.port, registrar.transport, expires)
		if len(contact_header_list) > 1:
			message += 'Other registered contacts:\n%s\n' % '\n'.join(['  %s (expires in %s seconds)' % (str(other_contact_header.uri), other_contact_header.expires) for other_contact_header in contact_header_list if other_contact_header.uri != notification.data.contact_header.uri])
		self.output.put(message)
		
		self.registration_succeeded = True

	def _NH_SIPAccountRegistrationDidFail(self, notification):
		self.output.put('%s Failed to register contact for sip:%s: %s (retrying in %.2f seconds)\n' % (datetime.now().replace(microsecond=0), self.account.id, notification.data.error, notification.data.retry_after))
		self.registration_succeeded = False

	def _NH_SIPAccountRegistrationDidEnd(self, notification):
		self.output.put('%s Registration ended.\n' % datetime.now().replace(microsecond=0))

	def _NH_DNSLookupDidSucceed(self, notification):
		self.routes = notification.data.result
		self._send_message()

	def _NH_DNSLookupDidFail(self, notification):
		self.output.put('DNS lookup failed: %s\n' % notification.data.error)
		self.stop()

	def _NH_SIPEngineGotMessage(self, notification):
		content_type = notification.data.content_type
		if content_type not in ('text/plain', 'text/html'):
			return
		from_header = FromHeader.new(notification.data.from_header)
		from_header.parameters = {}
		from_header.uri.parameters = {}
		identity = str(from_header.uri)
		if from_header.display_name:
			identity = '"%s" <%s>' % (from_header.display_name, identity)
		body = notification.data.body
		self.output.put("Got MESSAGE from '%s', Content-Type: %s\n%s\n" % (identity, content_type, body))

	def _NH_SIPMessageDidSucceed(self, notification):
		
		with open('print.txt', "a+") as f:
			f.write('MESSAGE was accepted by remote party\n')
			
		#self.output.put('MESSAGE was accepted by remote party\n')
		self.stop()

	def _NH_SIPMessageDidFail(self, notification):
		notification_center = NotificationCenter()
		notification_center.remove_observer(self, sender=notification.sender)
		self.output.put('Could not deliver MESSAGE: %d %s\n' % (notification.data.code, notification.data.reason))
		self._send_message()

	def _send_message(self):
		notification_center = NotificationCenter()
		if self.routes:
			route = self.routes.pop(0)
			identity = str(self.account.uri)
			if self.account.display_name:
				identity = '"%s" <%s>' % (self.account.display_name, identity)
			
            # NTP
			try:	
				c = ntplib.NTPClient() 
				#response = c.request('xxx.xxx.xxx.xxx') 
				response = c.request('xxx.xxx.xxx.xxx') 
				tx_time = response.tx_time 
				ntp_timestamp = datetime.fromtimestamp(tx_time)

				root_delay = response.root_delay
				root_delay = int(root_delay*1000000)
				
				_date = time.strftime('%Y-%m-%d',time.localtime(time.time()))
				filename = _date+".txt"
				with open(filename, "a+") as f:
					f.write("%s,%s,%s,%s,%s,%s\n" % (tx_time, root_delay, ntp_timestamp.hour, ntp_timestamp.minute, ntp_timestamp.second, ntp_timestamp.microsecond))
			except:
				traceback.print_exc(file=open('print.txt','a+'))
				root_delay = 0
				nowtime = time.time()
				ntp_timestamp = datetime.fromtimestamp(nowtime)

				_date = time.strftime('%Y-%m-%d',time.localtime(time.time()))
				filename = _date+".txt"
				with open(filename, "a+") as f:
					f.write("%s,%s,%s,%s,%s,%s\n" % (nowtime, root_delay, ntp_timestamp.hour, ntp_timestamp.minute, ntp_timestamp.second, ntp_timestamp.microsecond))
			

			with open('print.txt', "a+") as f:
				f.write("Sending MESSAGE from '%s' to '%s' using proxy %s\n" % (identity, self.target, route))
			with open('print.txt', "a+") as f:
				f.write('Press Ctrl+D to stop the program.\n')
			with open('print.txt', "a+") as f:
				f.write('%s\n' % self.message)
			#self.output.put("Sending MESSAGE from '%s' to '%s' using proxy %s\n" % (identity, self.target, route))
			#self.output.put('Press Ctrl+D to stop the program.\n')
			message_request = Message(FromHeader(self.account.uri, self.account.display_name), ToHeader(self.target), RouteHeader(route.uri), 'text/plain', self.message, credentials=self.account.credentials)
			notification_center.add_observer(self, sender=message_request)
			message_request.send()
			
		else:
			self.output.put('No more routes to try. Aborting.\n')
			self.stop()
