# -*- coding: UTF-8 -*-
# python 2.7
# coding: UTF-8	#兼容中文字符，如果沒有這句，程序中有中文字符時，運行會報錯

#import http.client, urllib
import requests, json, sys, time, os, traceback, sqlite3
import socket
import pickle
import ntplib
import threading
from datetime import datetime
from sipsimple.threading import ThreadManager
from sipsimple.storage import FileStorage
from sipsimple.configuration.datatypes import List, STUNServerAddress
from sipsimple.configuration import ConfigurationManager, DefaultValue
from sipsimple.application import SIPApplication
from sipsimple.account import Account, AccountManager

from sip_cmd_options import set_options
from sip_dir import account_config
from sip_message import SIPMessageApplication, root_delay
from multiprocessing import Process, Pipe

import config
IoTtalkServer = config.IoTtalkServer
IoTtalkServerPort = config.IoTtalkServerPort

# python SIPHandler_2.py <mac> <df_name>
# python SIPHandler_2.py SIP-G2 RoadAvgSpeed-O

def send(child_conn, devID, content):
	global aiottalkUA
	# myUA = "aiottalk@xxx.xxx.77.84"

	try:
		application = SIPMessageApplication()
		options_dict = {'account': aiottalkUA, 'trace_pjsip': False, 'trace_notifications': False, 'config_directory': None, 
				'trace_sip': False, 'message': content, 'batch_mode': False}
		options = set_options(options_dict)
		application.start(devID, options)
		time.sleep(3)
	except Exception as e:
		traceback.print_exc(file=open('print.txt', "a+"))

def SIPsend(ODG):
	global dbpath
	global webdbpath
	global sendList

  	#global ODG
	while(1):
		if len(sendList) is not 0:
			## [SOCKET] 1. find deviceID in this ODG
			## web.db -- "device" table: "actuator3-device4@xxx.xxx.77.76", "G2"

			webdb = sqlite3.connect(webdbpath)
			dbODList = webdb.execute("SELECT IMEI, devicegroup FROM Device")
			dbODList = list(dbODList)
			print(dbODList)
			webdb.commit()

			ODList = []
			for item in dbODList:
				if item[1] == ODG + ",":
					ODList.append(item[0])

			## e.g. ODG AUA has device3 and device4
			#ODList = ["actuator1-device3@xxx.xxx.77.76", "actuator3-device4@xxx.xxx.77.76"] 

			AUAList = set()
			for OD in ODList:
				AUAtmp = OD.split("-")[1]
				AUAList.add(AUAtmp)

			print(AUAList)
			# AUAList = ["device3@xxx.xxx.77.76", "device4@xxx.xxx.77.76"] 
			for AUA in AUAList:
				parent_conn, child_conn = Pipe()
				p = Process(target=send, args=(child_conn, AUA, str(sendList)))
				p.start()
				p.join()
				p.terminate()

		time.sleep(10)

def pull_value(mac):
	while (1):
		r = requests.get("http://" + IoTtalkServer + ":" + IoTtalkServerPort +"/"+mac+"/"+sys.argv[2])
		print(r.text)
		while "mac_addr not found" in r.text:
			time.sleep(5)
			r = requests.get("http://" + IoTtalkServer + ":" + IoTtalkServerPort +"/"+mac+"/"+sys.argv[2])
			print(r.text)

		# time of pull from IoTtalk
		root_delay = 0
		nowtime = time.time()
		ntp_timestamp = datetime.fromtimestamp(nowtime)

		_date = time.strftime('%Y-%m-%d',time.localtime(time.time()))
		filename = _date+"_SIPHandler2.txt"
		#with open(filename, "a+") as f:
			#f.write("%s,%s,%s,%s,%s,%s\n" % (nowtime, root_delay, ntp_timestamp.hour, ntp_timestamp.minute, ntp_timestamp.second, ntp_timestamp.microsecond))

		string = r.text
		#with open("SIPHandler2Log.txt", "a+") as f:
			#f.write("Msg string: %s\n" % string)
		dic = eval(string)
		if len(dic["samples"]) is not 0:
			Msg = dic["samples"][0][1]
			Msg = str(Msg).replace(' ','')

			with open("SIPHandler2Log.txt", "a+") as f:
				f.write("IoTtalk response: %s\n" % r.text) # 200 OK
				f.write("Msg from IoTtalk: %s\n" % Msg)
		
			# Msg: ['sensor3',54.5556,'device1@xxx.xxx.77.76','G2','2021-07-1021:21:22']
			Msg = eval(Msg)
			From_IMEI = Msg[0] +"-" + Msg[2]

			sendList[From_IMEI] = Msg[1]
			with open("SIPHandler2Log.txt", "a+") as f:
				f.write("sendList: %s\n" % str(sendList))
			# sendList: {'sensor4-device2@xxx.xxx.77.76': 72.75, 'sensor2-device1@xxx.xxx.77.76': 55.1321, 'sensor1-device1@xxx.xxx.77.76': 31.0, 'sensor3-device1@xxx.xxx.77.76': 54.4062, 'sensor5-device2@xxx.xxx.77.76': 73.0588}

			'''
			# NTP
			try:
				c = ntplib.NTPClient() 
				response = c.request('xxx.xxx.89.202') 
				tx_time = response.tx_time 
				ntp_timestamp = datetime.fromtimestamp(tx_time)

				root_delay = response.root_delay
				root_delay = int(root_delay*1000000)

				_date = time.strftime('%Y-%m-%d',time.localtime(time.time()))
				filename = _date+"(send_toAUA)"+".txt"
				with open(filename, "a+") as f:
				f.write("%s,%s,%s,%s,%s,%s\n" % (tx_time, root_delay, ntp_timestamp.hour, ntp_timestamp.minute, ntp_timestamp.second, ntp_timestamp.microsecond))
			except:
				root_delay = 0
				nowtime = time.time()
				ntp_timestamp = datetime.fromtimestamp(nowtime)

				_date = time.strftime('%Y-%m-%d',time.localtime(time.time()))
				filename = _date+"(send_toAUA)"+".txt"
				with open(filename, "a+") as f:
					f.write("%s,%s,%s,%s,%s,%s\n" % (nowtime, root_delay, ntp_timestamp.hour, ntp_timestamp.minute, ntp_timestamp.second, ntp_timestamp.microsecond))
			'''
		time.sleep(2)


if __name__ == "__main__":

	global dbpath
	global webdbpath
	dbpath = "./sqlite/"+ sys.argv[3] + "_SIP.db"
	webdbpath = "./sqlite/web.db"

	if sys.argv[1] == "auto":
		mac = open("/sys/class/net/enp3s0/address").read()
		mac = mac.strip()
	else:
		mac = sys.argv[1]

	global ODG
	ODG = mac.split("-")[1]

	global sendList
	sendList = {}

	global aiottalkUA
	with open("aiottalkUA.txt", "r") as f:
		aiottalkUA = f.readline()

	print("Using aiottalkUA: %s\n" % aiottalkUA)

	pull_value_thread=threading.Thread(target = pull_value, args=(mac,))
	pull_value_thread.daemon = True
	pull_value_thread.start()
	print("pull_value thread starts!\n")

	SIPsend_thread=threading.Thread(target = SIPsend, args=(ODG,))
	SIPsend_thread.daemon = True
	SIPsend_thread.start()
	print("SIPsend thread starts!\n")

	while(1):
		pass
	
