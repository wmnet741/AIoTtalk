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

from multiprocessing import Process,Queue,Pipe
from auto_send import auto_msg

#import xlwt, xlrd

if __name__ == "__main__":

	count =0
	# Opening file 
	with open('docDev.txt', "r") as f:
		for index, line in enumerate(f): 
			strtmp = line.strip()
			if (strtmp[1]=='0'):
				dev_num = strtmp[0:2]
				dev_msg = strtmp[4:]
			else:
				dev_num = strtmp[0]
				dev_msg = strtmp[3:]
			
			if (dev_num=='0'):
				continue
			
			timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))
			dev_msg = dev_msg + '"' + timestamp + '"}'
			#print "%s" % dev_msg

			parent_conn,child_conn = Pipe()
			p = Process(target=auto_msg, args=(child_conn,dev_num,dev_msg,count))
			count = count +1			
			p.start()
			p.join()
			p.terminate()
			print "%s" % dev_msg
			#time.sleep(5)

	
