# -*- coding: UTF-8 -*-
# python 2.7
# coding: UTF-8	#兼容中文字符，如果沒有這句，程序中有中文字符時，運行會報錯
from sip_message import SIPMessageApplication
from sip_cmd_options import set_options
import time

from multiprocessing import Process, Queue, Pipe
import json, sqlite3

import msg_list
import SIP_IDA
import ntplib
from datetime import datetime

def sendMsg(child_conn, MsgContent, target):
	application_aiottalk2 = SIPMessageApplication() #for send
	# print "Msg send"
	#with open('print.txt', "a+") as f:
		#f.write("Msg send\n")
	#target = 'device3@192.168.164.133'

	account = 'aiottalk@xxx.xxx.77.84'
	MsgSend = MsgContent
	
	options_dict = {'account': account, 'trace_pjsip': False, 
			'trace_notifications': False, 'config_directory': None, 
			'trace_sip': False, 'message': MsgSend, 'batch_mode': False}
	
	options = set_options(options_dict)
	
	
	# 0306 ADD NTP
	try:
		c = ntplib.NTPClient() 
		response = c.request('xxx.xxx.89.202') 
		tx_time = response.tx_time 
		ntp_timestamp = datetime.fromtimestamp(tx_time)
	
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
	application_aiottalk2.start(target, options)
	
	#time.sleep(0.5)

if __name__ == "__main__":
	### send Msg
	# MsgContent = ['I am aiottalk2: (1)','I am aiottalk2: (2)','I am aiottalk2: (3)']
	# senderlist: [[u'868333030154874', 24.795977, 120.992361, u'0902_B', u'868333030154872', u'2020-09-03 10:05:51'], [u'868333030154875', 24.795977, 120.992361, u'0902_B', u'868333030154872', u'2020-09-03 10:05:51'], [u'868333030154874', 24.795977, 120.992361, u'0902_B', u'868333030154872', u'2020-09-03 10:05:51'], [u'868333030154875', 24.795977, 120.992361, u'0902_B', u'868333030154872', u'2020-09-03 10:05:51']]
	# MsgContent = {}
	global sendmsglist
	sendmsglist = []
	dbpath = "./sqlite/" + "jenny" + "_" + "SIP" + ".db"
	

	while True:
		'''
		devicedb = sqlite3.connect(dbpath)
		sendmsg = devicedb.execute("SELECT MSG FROM SendMsg")
		with open('debug.txt', "a+") as f:
			f.write("sendmsg: %s\n" % sendmsg)

		devicedb.execute("DELETE FROM SendMsg")
		devicedb.commit()
		devicedb.close()
		'''
		f = open('sendMsg.txt', "a+")
		# 從文件第一行開始讀取
		cur_msg = f.readline()

		while cur_msg:
			
			cur_msg = eval(cur_msg)
			# msg_list.senderlist.pop(0)
			# cur_msg: [u'868333030154874', 24.795977, 120.992361, u'0902_B', u'868333030154872', u'2020-09-03 10:05:51']
			# parse senderlist中的資訊
			target_uri = cur_msg[0]
			value = cur_msg[1:2]
			IDG = cur_msg[3]
			FROM = cur_msg[4]
			#TIME = cur_msg[5]
			target = None

			if target_uri == '868333030154874':
				target = 'device4@xxx.xxx.77.76'
			elif target_uri == '868333030154875':
				target = 'device5@xxx.xxx.77.76'

			MsgContent = cur_msg

			parent_conn, child_conn = Pipe()
			p = Process(target=sendMsg, args=(child_conn, str(MsgContent), target))
			p.start()
			p.join()
			p.terminate()

			# 逐行讀取
			# 若到文件最後，則先停
			while True:
				cur_msg = f.readline()
				time.sleep(0.5)
				if  cur_msg:
					break
				else:
					#with open('debug_send.txt', "a+") as fp:
					#	fp.write("last line\n")
					continue
		time.sleep(0.5)

	#devicedb.commit()
	#devicedb.close()




