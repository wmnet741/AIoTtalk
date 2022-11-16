# -*- coding: UTF-8 -*-
# python 2.7
# coding: UTF-8	#兼容中文字符，如果沒有這句，程序中有中文字符時，運行會報錯
import socket
import time
from datetime import datetime
import sys, traceback
import threading
import ast
import time, requests, random, uuid
import json, atexit, sys, requests, os, signal, sqlite3
import ntplib
from openpyxl import Workbook, load_workbook
from sqlalchemy.dialects.mssql.information_schema import key_constraints

# mac測試要註解
from sipsimple.threading import ThreadManager
from sipsimple.storage import FileStorage
from sipsimple.configuration.datatypes import List, STUNServerAddress
from sipsimple.configuration import ConfigurationManager, DefaultValue
from sipsimple.application import SIPApplication
from sipsimple.account import Account, AccountManager

from sip_cmd_options import set_options
from sip_dir import account_config
from sip_message import SIPMessageApplication, root_delay
from sip_audio_session import SIPAudioApplication, RTPStatisticsThread, CancelThread

import config
import msg_list
import collections 
from collections import deque

IoTtalkServer = config.IoTtalkServer
IoTtalkServerPort = config.IoTtalkServerPort

def sip_add(SIPAddr, SIPPassword):
	# 此function是為了將user加入sip client名冊中
	# 先設定manager
	configuration_manager = ConfigurationManager()
	configuration_manager.start()

	global account_manager
	account_manager = AccountManager()
	account_manager.load()

	if account_manager.has_account(SIPAddr):
		with open('SIPHandlerLog.txt', "a+") as f:
			f.write('Account %s already exists\n' % (SIPAddr))
	else:
		try:
			account = Account(SIPAddr)
		except ValueError as e:
			traceback.print_exc(file=open('debug.txt','a+'))
			with open('debug.txt', "a+") as f:
				f.write("Cannot add SIP account : %s\n" % SIPAddr)
			exitbool = True

		account.auth.password = SIPPassword
		account.enabled = True
		account.save()
		with open('SIPHandlerLog.txt', "a+") as f:
			f.write("Account added\n")
	time.sleep(0.5)
	default(SIPAddr)
	time.sleep(0.5)

def default(SIPAddr):
	# 設定user為預設帳號
	# 找出符合的帳號
	possible_accounts = [account for account in account_manager.iter_accounts() if SIPAddr in account.id]
	if len(possible_accounts) > 1:
		with open('SIPHandlerLog.txt', "a+") as f:
			f.write("More than one account exists which matches %s: %s" % (
			SIPAddr, ", ".join(sorted(account.id for account in possible_accounts))))
		exitbool = True
	elif len(possible_accounts) == 0:
		with open('SIPHandlerLog.txt', "a+") as f:
			f.write('Account %s does not exist' % (SIPAddr))
		exitbool = True
	else:
		account = possible_accounts[0]

		try:
			account_manager.default_account = account
		except ValueError as e:
			traceback.print_exc(file=open('debug.txt','a+'))
			
		with open('SIPHandlerLog.txt', "a+") as f:
			f.write('Account %s is now default account\n' % (account.id))

def sip_setproxy(SIPAddr, SIPPassword, SIPProxy):
	# 設定outbound sip proxy
	# 找出符合的帳號
	# 原指令：sip-settings -a set aiottalk@xxx.xxx.77.85 sip.outbound_proxy=xxx.xxx.77.73:5566
	possible_accounts = [account for account in account_manager.iter_accounts() if SIPAddr in account.id]
	arg = 'sip.outbound_proxy=' + SIPProxy
	
	if len(possible_accounts) > 1:
		with open('SIPHandlerLog.txt', "a+") as f:
			f.write("More than one account exists which matches %s: %s" % (
			SIPAddr, ", ".join(sorted(account.id for account in possible_accounts))))
		exitbool = True
	elif len(possible_accounts) == 0:
		with open('SIPHandlerLog.txt', "a+") as f:
			f.write('No accounts which match %s' % (SIPAddr))
		exitbool = True
	else:
		settings_str = "{'sip.outbound_proxy':'" + SIPProxy + "'}"
		settings = ast.literal_eval(settings_str)  # 轉換成dictionary

		account = possible_accounts[0]
		for attrname, value in settings.iteritems():
			# attrname = sip.outbound_proxy
			# value = xxx.xxx.77.73:5566
			account_tmp = account
			attrname_tmp = attrname
			while '.' in attrname_tmp:
				local_name, attrname_tmp = attrname_tmp.split('.', 1)
				# local_name = sip
				# attrname_tmp = outbound_proxy
				try:
					# getattr(object, name[, default])
					# 取得參數 (parameter) object 的屬性值， name 為屬性名稱，必須為字串
					# 這邊屬性名稱為sip, 屬性值為outbound_proxy
					attr_converted = getattr(account_tmp, local_name)
				except AttributeError:
					traceback.print_exc(file=open('debug.txt','a+'))
					attr_converted = None
					exitbool = True
					break
			if attr_converted is not None:
				try:
					attribute = getattr(type(attr_converted), attrname_tmp)
					# 轉換value至正確的sip proxy addr.格式
					value = parse_SIPProxyAddress(attribute.type, value)
					setattr(attr_converted, attrname_tmp, value)
				except AttributeError:
					traceback.print_exc(file=open('debug.txt','a+'))
					exitbool = True
				except ValueError as e:
					traceback.print_exc(file=open('debug.txt','a+'))
					exitbool = True

		account.save()
		with open('SIPHandlerLog.txt', "a+") as f:
			f.write('Account %s updated\n' % account)
		regproxybool = True

def parse_SIPProxyAddress(type, value):
	# 轉換SIP proxy address為正確型態
	# print type = <class 'sipsimple.configuration.datatypes.SIPProxyAddress'>
	return type.from_description(value)

def sip_msg():
	target = None
	# option's dictionary
	options_dict = {'account': None, 'trace_pjsip': False, 
			'trace_notifications': False, 'config_directory': None, 
			'trace_sip': False, 'message': None, 'batch_mode': False}
	options = set_options(options_dict)

	application = SIPMessageApplication()
	application.start(target, options)

	time.sleep(1)

def msg_parser():
	# 處理來自SIP的資料
	global dbpath
	global webdbpath

	# 將packet content取出並做相對應處理
	while True:
		while True:
			if (len(msg_list.messagelist)==0):
				continue
			msgqueue = deque(msg_list.messagelist)
			contents = msgqueue.popleft()
			msg_list.messagelist = list(msgqueue)
			
			if contents != "":
				break
		with open('SIPHandlerLog.txt', "a+") as f:
			f.write("%s\n" % contents)
		try:
			msgparser = eval(contents)
			print(msgparser)

			SIPURI = msgparser.get("DEVID") # device1@xxx.xxx.77.76
			timestamp = msgparser.get("TIME")
			IDs_list = msgparser.get("DATA")
			for ID in IDs_list:
				IDName = ID[0]
				IDValue = ID[1]
				print("IDName: %s, IDValue: %s" % (str(IDName), str(IDValue)))

				#################################################################
				# [SOCKET] 2. find device group/device feature
				# msg: {"DEVID": "device1@xxx.xxx.77.76", "DATA": [["sensor1", [54.5556]], ["sensor2", [54.5556]], ["sensor3", [54.5556]]], "TIME":"2021-07-09 11:10:21"}
				# e.g. device group = "G2", device feature = "RoadAvgSpeed-I"
				# web.db -- "device" table: "sensor1-device1@xxx.xxx.77.76", "G1"
				# jenny_SIP.db -- "DeviceProfile" table: "sensor1-device1@xxx.xxx.77.76", "RoadAvgSpeed-I"

				target = IDName + "-" + SIPURI # sensor1-device1@xxx.xxx.77.76

				webdb = sqlite3.connect(webdbpath)
				deviceList = webdb.execute("SELECT IMEI, devicegroup FROM Device")
				deviceList = list(deviceList)
				webdb.commit()

				for item in deviceList:
					if item[0] == target:
						group = item[1]
						group = group.split(",")
						group = group[0]

				devicedb = sqlite3.connect(dbpath)
				deviceprofileList = devicedb.execute("SELECT IMEI, devicefeature FROM DeviceProfile")
				deviceprofileList = list(deviceprofileList)
				devicedb.commit()

				for item in deviceprofileList:
					if item[0] == target:
						df = item[1]

				# group = "G1"
				mac = "SIP-" + group
				# df = "RoadAvgSpeed-I"
				#################################################################

				data_array = [IDName, IDValue, SIPURI, group, timestamp]
				params={"data": data_array}
				print(params)
				body=json.dumps(params)
				headers={"Content-Type": "application/json"}
				r = requests.put("http://" + IoTtalkServer + ":" + IoTtalkServerPort +"/" +mac+"/"+df, headers = headers, data = body)
				print(r.status_code)
				time.sleep(2)
					
		except Exception as e:
			stre = str(e)
			traceback.print_exc(file=open('debug.txt','a+'))

def lookupODGODF():
	global dbpath
	global webdbpath

	ODGName = ""
	devicedb = sqlite3.connect(dbpath)
	dbcursor = devicedb.cursor()

	#get the count of tables with the name
	dbcursor.execute("SELECT count(*) FROM sqlite_master WHERE type = \'table\' AND name = \'GroupMapping\'")

	#if the count is 1, then table exists
	if dbcursor.fetchone()[0]!=1 :
		while True:
			print("Table GroupMapping doesn't exist")
			time.sleep(5)
			dbcursor.execute("SELECT count(*) FROM sqlite_master WHERE type = \'table\' AND name = \'GroupMapping\'")
			if dbcursor.fetchone()[0]==1 :
				break

	groupmappingList = devicedb.execute("SELECT DGName, DG FROM GroupMapping")
	groupmappingList = list(groupmappingList)
	devicedb.commit()

	for item in groupmappingList:
		if item[1] == "ODG":
			ODGName = item[0]
			devicegroup = item[0] + ","
	while ODGName == "":
		print("ODG doesn't exist")
		time.sleep(5)
		groupmappingList = devicedb.execute("SELECT DGName, DG FROM GroupMapping")
		groupmappingList = list(groupmappingList)
		devicedb.commit()

		for item in groupmappingList:
			if item[1] == "ODG":
				ODGName = item[0]
				devicegroup = item[0] + ","

	webdb = sqlite3.connect(webdbpath)
	deviceList = webdb.execute("SELECT devicemodel, devicegroup FROM Device")
	deviceList = list(deviceList)
	webdb.commit()

	for item in deviceList:
		if item[1] == devicegroup:
			devicemodel = item[0]
			break

	devicedb = sqlite3.connect(dbpath)
	deviceprofileList = devicedb.execute("SELECT devicemodel, devicefeature FROM DeviceProfile")
	deviceprofileList = list(deviceprofileList)
	devicedb.commit()

	for item in deviceprofileList:
		if item[0] == devicemodel:
			ODF = item[1]
			break

	return ODGName, ODF

def exit_check():
	#隨時檢查是否有收到程式終止的要求，有就正常終止自己
	try:
		while 1:
		    pass
	except KeyboardInterrupt:
		with open('print.txt', "a+") as f:
			f.write("exit\n")
		sys.exit()

if __name__ == "__main__":

	global dbpath
	global webdbpath
	dbpath = "./sqlite/"+ sys.argv[5] + "_SIP.db"
	webdbpath = "./sqlite/web.db"

	# retrieve data from IM or LBM (using socket)	
	## [SOCKET] 1. receive socket_content from SIP_IDA.py
	
	# e.g. 0 aiottalk@10.0.20.207 123123 xxx.xxx.77.73:5566 jenny

	#cmd = raw_input("Please input msg:")
	cmd = [sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]]

	if cmd[0] == '0':
		# 要先設定帳戶儲存位置，才能加入使用者
		SIPApplication.storage = FileStorage(account_config)

		time.sleep(2)
		
		sip_add(cmd[1], cmd[2])
		sip_setproxy(cmd[1], cmd[2], cmd[3])
		print("SIP account is added successfully!\n")

		sip_msg() # start SIPMessageApplication
		msg_parser_thread=threading.Thread(target = msg_parser)
		msg_parser_thread.daemon = True
		msg_parser_thread.start()
		print("SIP Handler start!\n")
		
		time.sleep(2)

		with open('aiottalkUA.txt', "w") as f:
			f.write("%s" % cmd[1])

		## [SOCKET] 3. find AUA group name and ODF
		## jenny_SIP.db -- "GroupMapping" table: "G2", "ODG"
		## web.db -- "device" table: "ElecMap", "G2"
		## jenny_SIP.db -- "DeviceProfile" table: "RoadAvgSpeed-O", "ElecMap"
		## "G2">> AUA group, "RoadAvgSpeed-O" >> ODF

		ODGName, ODF = lookupODGODF()
		#ODGName = "G2"
		#ODF = "RoadAvgSpeed-O"
		cmd = "python SIPHandler_2.py SIP-" + ODGName + " " + ODF + " " + sys.argv[5]
		os.system(cmd)

	#隨時檢查是否有收到程式終止的要求
	exit_check();
