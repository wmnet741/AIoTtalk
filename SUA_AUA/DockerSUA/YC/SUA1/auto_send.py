# -*- coding: UTF-8 -*-
# python 2.7
# coding: UTF-8	#兼容中文字符，如果沒有這句，程序中有中文字符時，運行會報錯
import time
from datetime import datetime
import sys, traceback
import threading
import ast
import time, random, uuid
import json, atexit, requests, os, signal, sqlite3

from sipsimple.threading import ThreadManager
from sipsimple.storage import FileStorage
from sipsimple.configuration.datatypes import List, STUNServerAddress
from sipsimple.configuration import ConfigurationManager, DefaultValue
from sipsimple.application import SIPApplication

from sip_cmd_options import set_options
from sip_dir import account_config
from sip_message import SIPMessageApplication

from multiprocessing import Process,Pipe
#from test import dev_num, dev_msg

dev1 = 'device@xxx.xxx.xxx.xxx'
target = 'aiottalk@xxx.xxx.xxx.xxx'

def auto_msg(child_conn,dev_num,dev_msg, count):

	try:
		
		application = SIPMessageApplication()
		if dev_num=='1':
			options_dict = {'account': dev1, 'trace_pjsip': False, 
						'trace_notifications': False, 'config_directory': None, 
						'trace_sip': False, 'message': dev_msg, 'batch_mode': False, 'count': count}

		options = set_options(options_dict)
		#with open('print.txt', "a+") as f:
		#	f.write("options: %s\ntarget: %s\n" % (options_dict,target))
		application.start(target, options)
        
        # 這裡設定每封msg傳送的週期
		time.sleep(10)
		'''
		if (count<1000):
			time.sleep(2)
		elif (count<2000):
			if (count==999):
				time.sleep(300)
			time.sleep(4)
		else:
			if (count==1999):
				time.sleep(300)
			time.sleep(5)
		'''
			
	except Exception as e:
		traceback.print_exc(file=open('print.txt','a+'))
