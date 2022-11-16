
# -*- coding: UTF-8 -*-
# coding: UTF-8 

__all__ = ['InputThread', 'SIPMessageApplication']

import atexit
import os
import select
import signal
import sys
import termios
import ntplib
from openpyxl import Workbook, load_workbook

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

import msg_list
from collections import deque

import time
global root_delay
root_delay=0

'''
class InputThread(Thread):
	
	__init__
	start()
	run() -> if not self.batch_mode
	_getchars -> if os.isatty(fd):
	>>> Using account aiottalk@xxx.xxx.77.85
	>>> Press Ctrl+D to stop the program.
	>>> 註冊訊息(...Registered contact....)
	>>> 收到訊息(Got MESSAGE from....)
	>>> 印出訊息
	>>> 輸入ctrl+D
	_termios_restore() [getchar後都會配一次restore]
	while chars (in run().)
	_getchars
	>>> 2020-01-17 02:24:34 Registration ended.
	stop()
	_termios_restore()
	
	def __init__(self, read_message, batch_mode):
		Thread.__init__(self)
		#print "1"
		self.setDaemon(True)
		self.read_message = read_message
		self.batch_mode = batch_mode
		self._old_terminal_settings = None

	def start(self):
		#print "2"
		atexit.register(self._termios_restore)
		Thread.start(self)

	def run(self):
		#print "3"
		notification_center = NotificationCenter()
		
		if self.read_message:
			#print "4"
			lines = []
			try:
				while True:
					lines.append(raw_input())
			except EOFError:
				message = '\n'.join(lines)
				notification_center.post_notification('SIPApplicationGotInputMessage', sender=self, data=NotificationData(message=message))

		if not self.batch_mode:
			#print "5"
			while True:
				chars = list(self._getchars())
				while chars:
					#print "6"
					char = chars.pop(0)
					if char == '\x1b': # escape , \x1b is the ASCII for ESCAPE (literally the ESC key on your keyboard).
						#print "7"
						if len(chars) >= 2 and chars[0] == '[' and chars[1] in ('A', 'B', 'C', 'D'): # one of the arrow keys(方向鍵)
							char = char + chars.pop(0) + chars.pop(0)
					notification_center.post_notification('SIPApplicationGotInput', sender=self, data=NotificationData(input=char))

	def stop(self):
		#print "8"
		self._termios_restore()

	def _termios_restore(self):
		#print "9"
		if self._old_terminal_settings is not None:
			termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self._old_terminal_settings) # 改回原本的設定

	def _getchars(self):
		fd = sys.stdin.fileno()
		if os.isatty(fd):
			#print "11"
			self._old_terminal_settings = termios.tcgetattr(fd) # 先把原本的設定記住
			new = termios.tcgetattr(fd)
			# ICANON:
			# Enable canonical mode. 
			# This enables the special characters EOF, EOL, EOL2, ERASE, KILL, LNEXT, REPRINT, STATUS, 
			# and WERASE, and buffers by lines.
			# ECHO:
			# Echo input characters.
			# 3 is lflag
			# c_lflag用來控制串列埠如何處理輸入字元
			new[3] = new[3] & ~termios.ICANON & ~termios.ECHO # here is not
			new[6][termios.VMIN] = '\000' # VMIN: Minimum number of characters for non-canonical read.
			try:
				# TCSADRAIN	當目前輸出完成時，將值改變
				termios.tcsetattr(fd, termios.TCSADRAIN, new) # 改為new 新的設定
				if select.select([fd], [], [], None)[0]:
					return sys.stdin.read(4192)
			finally:
				self._termios_restore()
		else:
			#print "12"
			return os.read(fd, 4192)
'''

class SIPMessageApplication(SIPApplication):
	

	def __init__(self):
		self.account = None
		self.options = None
		self.target = None
		
		self.routes = []
		self.registration_succeeded = False
		
		#self.input =  None
		#self.output = None
		self.ip_address_monitor = IPAddressMonitor()

	def _write(self, message):
		if isinstance(message, unicode):
			message = message.encode(sys.getfilesystemencoding())
		sys.stdout.write(message)
		sys.stdout.flush()

	def start(self, target, options):
		notification_center = NotificationCenter()
		
		self.options = options
		self.message = options.message
		# send msg to "whom", whom IS target
		self.target = target
		# 這邊是read_message=none
		#self.input = InputThread(read_message=(self.target is not None and options.message is None), batch_mode=options.batch_mode)
		# put _write function into the eventqueue 
		#self.output = EventQueue(self._write)
		
		notification_center.add_observer(self, sender=self) # 作為observer接收來自這個class的所有種類通知
		#notification_center.add_observer(self, sender=self.input) # 作為observer接收來自這個class.input的所有種類通知
		notification_center.add_observer(self, name='SIPEngineGotMessage') # 作為observer接收所有人的'SIPEngineGotMessage'種類通知

		#if self.input:
		#	self.input.start()
		#self.output.start()

		log.level.current = log.level.WARNING # get rid of twisted messages

		try:
			SIPApplication.start(self, FileStorage(account_config))
		except ConfigurationError, e:
			#self.output.put("Failed to load sipclient's configuration: %s\n" % str(e))
			#self.output.put("If an old configuration file is in place, delete it or move it and recreate the configuration using the sip_settings script.\n")
			#self.output.stop()
			with open('debug.txt', "a+") as f:
				f.write("Failed to load sipclient's configuration: %s\n" % str(e))
			
	'''
	_NH_SIPApplicationWillStart
	>>> Using account aiottalk@xxx.xxx.77.85
	_NH_SIPApplicationDidStart
	>>> Press Ctrl+D to stop the program.
	_NH_SIPAccountRegistrationDidSucceed
	>>> 註冊訊息(...Registered contact....)
	_NH_SIPEngineGotMessage  : 由application.py call '_run_reactor' -> '_initialize_core' -> engine.start(在core._engine.py) -> _handle_event
	>>> 收到訊息(Got MESSAGE from....)
	>>> 印出訊息
	>>> 輸入ctrl+D
	_NH_SIPApplicationGotInput : 由application handle_notification觸發
	_NH_SIPApplicationWillEnd
	_NH_SIPAccountRegistrationDidEnd
	>>> 2020-01-17 02:24:34 Registration ended.
	_NH_SIPApplicationDidEnd
	'''
	def _NH_SIPApplicationWillStart(self, notification):
		#print "1"
		account_manager = AccountManager()
		notification_center = NotificationCenter()
		settings = SIPSimpleSettings()

		for account in account_manager.iter_accounts():
			# The isinstance() function returns True if the specified object is of the specified type, otherwise False.
			# isinstance(object, type)
			if isinstance(account, Account):
				account.sip.register = False
		if self.options.account is None: #yes
			self.account = account_manager.default_account
		else:
			possible_accounts = [account for account in account_manager.iter_accounts() if self.options.account in account.id and account.enabled]
			if len(possible_accounts) > 1:
				#self.output.put('More than one account exists which matches %s: %s\n' % (self.options.account, ', '.join(sorted(account.id for account in possible_accounts))))
				#self.output.stop()
				#self.stop()
				return
			elif len(possible_accounts) == 0:
				#self.output.put('No enabled account that matches %s was found. Available and enabled accounts: %s\n' % (self.options.account, ', '.join(sorted(account.id for account in account_manager.get_accounts() if account.enabled))))
				#self.output.stop()
				#self.stop()
				return
			else:
				self.account = possible_accounts[0]
		#print type(self.account) >>>> <class 'sipsimple.account.Account'>
		#print self.account >>>> Account('device@xxx.xxx.77.76')
		# 由class Account() 中的__repr__ 印出 "return '%s(%r)' % (self.__class__.__name__, self.id)"
		if isinstance(self.account, Account) and self.target is None: #yes
			self.account.sip.register = True
			notification_center.add_observer(self, sender=self.account)
		with open('print.txt', "a+") as f:
			f.write('Using account %s\n' % self.account.id)
		#self.output.put('Using account %s\n' % self.account.id)

	def _NH_SIPApplicationDidStart(self, notification):
		#print "2"
		notification_center = NotificationCenter()
		settings = SIPSimpleSettings()

		self.ip_address_monitor.start()

		if isinstance(self.account, BonjourAccount) and self.target is None: #yes
			for transport in settings.sip.transport_list:
				try:
					with open('print.txt', "a+") as f:
						f.write('Listening on: %s\n' % self.account.contact[transport])
				except KeyError:
					pass

		if self.target is not None: #no
			if '@' not in self.target:
				self.target = '%s@%s' % (self.target, self.account.id.domain)
			if not self.target.startswith('sip:') and not self.target.startswith('sips:'):
				self.target = 'sip:' + self.target
			try:
				self.target = SIPURI.parse(self.target)
			except SIPCoreError:
				#self.output.put('Illegal SIP URI: %s\n' % self.target)
				self.stop()
			if self.message is None:
				with open('print.txt', "a+") as f:
					f.write('Press Ctrl+D on an empty line to end input and send the MESSAGE request.\n')
				#self.output.put('Press Ctrl+D on an empty line to end input and send the MESSAGE request.\n')
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
			with open('print.txt', "a+") as f:
				f.write('Message will be saved in text file. Press Ctrl+D to stop saving.\n')
			#self.output.put('Message will be saved in text file. Press Ctrl+D to stop saving.\n')

	def _NH_SIPApplicationWillEnd(self, notification):
		#print "3"
		self.ip_address_monitor.stop()

	def _NH_SIPApplicationDidEnd(self, notification):
		#print "4"
		#if self.input:
		#	self.input.stop()
		#self.output.stop()
		#self.output.join()
		with open('print.txt', "a+") as f:
			f.write("SIPApplicationDidEnd")

	def _NH_SIPApplicationGotInput(self, notification):
		#print "5"
		#data.input是指本地使用者的輸入
		if notification.data.input == '\x04': # ctrl D
			self.stop()

	def _NH_SIPApplicationGotInputMessage(self, notification):
		#print "6"
		#data.message 是給傳送方用的
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
		#print "7"
		with open('debug.txt', "a+") as f:
			f.write('An exception occured within the SIP core:\n%s\n' % notification.data.traceback)
		#self.output.put('An exception occured within the SIP core:\n%s\n' % notification.data.traceback)

	def _NH_SIPAccountRegistrationDidSucceed(self, notification):
		#print "8"
		if self.registration_succeeded:
			return
		contact_header = notification.data.contact_header
		contact_header_list = notification.data.contact_header_list
		expires = notification.data.expires
		registrar = notification.data.registrar
		message = '%s Registered contact "%s" for sip:%s at %s:%d;transport=%s (expires in %d seconds).\n' % (datetime.now().replace(microsecond=0), contact_header.uri, self.account.id, 
					registrar.address, registrar.port, registrar.transport, expires)
		if len(contact_header_list) > 1:
			message += 'Other registered contacts:\n%s\n' % '\n'.join(['  %s (expires in %s seconds)' % (str(other_contact_header.uri), other_contact_header.expires) for other_contact_header in contact_header_list if other_contact_header.uri != notification.data.contact_header.uri])
		#self.output.put(message)
		with open('print.txt', "a+") as f:
			f.write(message)
		self.registration_succeeded = True

	def _NH_SIPAccountRegistrationDidFail(self, notification):
		#print "9"
		#self.output.put('%s Failed to register contact for sip:%s: %s (retrying in %.2f seconds)\n' % (datetime.now().replace(microsecond=0), self.account.id, notification.data.error, notification.data.retry_after))
		self.registration_succeeded = False

	def _NH_SIPAccountRegistrationDidEnd(self, notification):
		#print "10"
		with open('print.txt', "a+") as f:
			f.write('%s Registration ended.\n' % datetime.now().replace(microsecond=0))
		#self.output.put('%s Registration ended.\n' % datetime.now().replace(microsecond=0))

	def _NH_DNSLookupDidSucceed(self, notification):
		#print "11"
		self.routes = notification.data.result
		self._send_message()

	def _NH_DNSLookupDidFail(self, notification):
		#print "12"
		#self.output.put('DNS lookup failed: %s\n' % notification.data.error)
		self.stop()

	def _NH_SIPEngineGotMessage(self, notification):
		#print "13"

		content_type = notification.data.content_type
		if content_type not in ('text/plain', 'text/html'):
			return
		
		from_header = FromHeader.new(notification.data.from_header)
		from_header.parameters = {}
		from_header.uri.parameters = {}
		identity = str(from_header.uri)
		
		# NTP
		try:
			c = ntplib.NTPClient() 
			response = c.request('xxx.xxx.77.76') 
			tx_time = response.tx_time 
			ntp_timestamp = datetime.fromtimestamp(tx_time)
		
			root_delay = response.root_delay
			root_delay = int(root_delay*1000000)
			
			_date = time.strftime('%Y-%m-%d',time.localtime(time.time()))
			sub_device_tmp = identity.split(":")
			sub_device = sub_device_tmp[1].split("@")
			#filename = _date+"(recv_fromSUA)"+"_"+sub_device[0]+".txt"
			filename = _date+"(recv_fromSUA)"+".txt"
			with open(filename, "a+") as f:
				f.write("%s,%s,%s,%s,%s,%s\n" % (tx_time, root_delay, ntp_timestamp.hour, ntp_timestamp.minute, ntp_timestamp.second, ntp_timestamp.microsecond))
		except:
			root_delay = 0
			nowtime = time.time()
			ntp_timestamp = datetime.fromtimestamp(nowtime)

			_date = time.strftime('%Y-%m-%d',time.localtime(time.time()))
			sub_device_tmp = identity.split(":")
			sub_device = sub_device_tmp[1].split("@")
			#filename = _date+"(recv_fromSUA)"+"_"+sub_device[0]+".txt"
			filename = _date+"(recv_fromSUA)"+".txt"
			with open(filename, "a+") as f:
				f.write("%s,%s,%s,%s,%s,%s\n" % (nowtime, root_delay, ntp_timestamp.hour, ntp_timestamp.minute, ntp_timestamp.second, ntp_timestamp.microsecond))

		# Here, we used "w" letter in our argument, which indicates write and will create a file if it does not exist in library
		# Plus sign indicates both read and write.
		# The available option beside "w" are, "r" for read, and "a" for append
		with open("from.txt", "w") as f:
			f.write("%s" % identity)

		if from_header.display_name:
			identity2 = '"%s" <%s>' % (from_header.display_name, identity)
		# data.body是收到的訊息
		body = notification.data.body
		
		msgqueue = deque(msg_list.messagelist)
		msgqueue.append(body)
		msg_list.messagelist = list(msgqueue)
		with open("print.txt", "a+") as f:
			f.write("messagelist: %s\n" % msg_list.messagelist)

		#with open("body.txt", "a+") as f:
		#	f.write("%s\n" % body)
		
		#f = open("body.txt", "a+")
		#f.write("%s\n" % body)
		with open('print.txt', "a+") as f:
			f.write("Got MESSAGE from '%s', Content-Type: %s\n%s\n" % (identity2, content_type, body))
		#self.output.put("Got MESSAGE from '%s', Content-Type: %s\n%s\n" % (identity, content_type, body))

	def _NH_SIPMessageDidSucceed(self, notification):
		#print "14"
		with open('print.txt', "a+") as f:
			f.write("MESSAGE was accepted by remote party\n" )
		#self.output.put('MESSAGE was accepted by remote party\n')
		self.stop()

	def _NH_SIPMessageDidFail(self, notification):
		#print "15"
		notification_center = NotificationCenter()
		notification_center.remove_observer(self, sender=notification.sender)
		#self.output.put('Could not deliver MESSAGE: %d %s\n' % (notification.data.code, notification.data.reason))
		self._send_message()

	def _send_message(self):
		#print "16"
		notification_center = NotificationCenter()
		if self.routes:
			route = self.routes.pop(0)
			identity = str(self.account.uri)
			if self.account.display_name:
				identity = '"%s" <%s>' % (self.account.display_name, identity)
			#self.output.put("Sending MESSAGE from '%s' to '%s' using proxy %s\n" % (identity, self.target, route))
			#self.output.put('Press Ctrl+D to stop the program.\n')

			#with open('print.txt', "a+") as f:
			#	f.write("Sending MESSAGE from '%s' to '%s' using proxy %s\n" % (identity, self.target, route))
			# Sending MESSAGE from 'sip:aiottalk@xxx.xxx.77.72' to 'sip:device5@xxx.xxx.77.76' using proxy sip:xxx.xxx.77.73:5566

			#with open('debug.txt', "a+") as f:
			#	f.write('Press Ctrl+D to stop the program.\n')
			#with open('print.txt', "a+") as f:
			#	f.write('%s\n' % self.message)
			'''
			# 0306 ADD NTP
			try:
				c = ntplib.NTPClient() 
				with open('print.txt', "a+") as f:
					f.write("---NTPClient1---\n")
				#response = c.request('xxx.xxx.89.202') 
				response = c.request('xxx.xxx.89.202') 
				tx_time = response.tx_time 
				#tx_time = time.time()
				with open('print.txt', "a+") as f:
					f.write("---NTPClient1---%s\n" % tx_time)
				ntp_timestamp = datetime.fromtimestamp(tx_time)
				with open('print.txt', "a+") as f:
					f.write("---NTPClient1---%s\n" % ntp_timestamp)
				root_delay = response.root_delay
				root_delay = int(root_delay*1000000)
				
				_date = time.strftime('%Y-%m-%d',time.localtime(time.time()))
				#sub_device_tmp = identity.split(":")
				#sub_device = sub_device_tmp[1].split("@")
				#filename = _date+"(send_toAUA)"+"_"+sub_device[0]+".txt"
				filename = _date+"(send_toAUA)"+"_"+"device"+".txt"
				with open(filename, "a+") as f:
					f.write("%s,%s,%s,%s,%s,%s\n" % (tx_time, root_delay, ntp_timestamp.hour, ntp_timestamp.minute, ntp_timestamp.second, ntp_timestamp.microsecond))
			except:
				traceback.print_exc(file=open('print.txt','a+'))

				with open('print.txt', "a+") as f:
					f.write("---NTPClient2---\n")
				root_delay = 0
				nowtime = time.time()
				ntp_timestamp = datetime.fromtimestamp(nowtime)

				_date = time.strftime('%Y-%m-%d',time.localtime(time.time()))
				#sub_device_tmp = identity.split(":")
				#sub_device = sub_device_tmp[1].split("@")
				#filename = _date+"(send_toAUA)"+"_"+sub_device[0]+".txt"
				filename = _date+"(send_toAUA)"+"_"+"device"+".txt"
				with open(filename, "a+") as f:
					f.write("%s,%s,%s,%s,%s,%s\n" % (nowtime, root_delay, ntp_timestamp.hour, ntp_timestamp.minute, ntp_timestamp.second, ntp_timestamp.microsecond))
			#---------------------
			
			_date = time.strftime('%Y-%m-%d',time.localtime(time.time()))
			#filename = _date+"(send_toAUA)"+"_"+sub_device[0]+".txt"
			filename = _date+"(send_toAUA)"+"_"+"device"+".txt"
			with open(filename, "a+") as f:
					f.write("HIHIHI\n")
			'''
			message_request = Message(FromHeader(self.account.uri, self.account.display_name), ToHeader(self.target), RouteHeader(route.uri), 'text/plain', self.message, credentials=self.account.credentials)
			notification_center.add_observer(self, sender=message_request)
			message_request.send()
		else:
			#self.output.put('No more routes to try. Aborting.\n')
			with open('print.txt', "a+") as f:
				f.write('No more routes to try. Aborting.\n')
			self.stop()
