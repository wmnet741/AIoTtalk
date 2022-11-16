# -*- coding: UTF-8 -*-
# coding: UTF-8 #兼容中文字符，如果沒有這句，程序中有中文字符時，運行會報錯

from tensorflow.keras.models import load_model
import sys, traceback
import threading, time, os
import socket
import pickle
import config
import requests, json, sys, time, os

IoTtalkServer = config.IoTtalkServer
IoTtalkServerPort = config.IoTtalkServerPort

# python3 /home/wmnet/YiChun/aiottalk_EP/ModelPre/pred.py [[[13.89],[13.89],[13.89],[13.89],[13.89],[13.89]]] sensor3 device1@xxx.xxx.77.76 G2 2021-07-1021:21:22 AI_LSTM PredictedSpeed-I

def predict_send(SpeedList, IDName, SUAName, IDGName, timestamp, mac, IDF):
	try:	
		# get current folder
		cur_folder = os.path.abspath(os.getcwd())
		model = load_model(cur_folder + '/speed_model.h5')

		X = eval(SpeedList)
		prediction = model.predict(X)
		newMsg = [IDName, prediction[0][0], SUAName, IDGName, timestamp]

		with open('model_result.txt', "a+") as f:
			f.write("[%s] predictedSpeed: %s\n" % (IDName, prediction[0][0]))
			f.write("newMsg: %s\n" % newMsg)

	        # data_array = ['sensor3', 15.379114, 'device1@xxx.xxx.77.76', 'G2', '2021-07-1021:21:22']

		data_array = []
		for value in newMsg:
			#print(type(value))
			if isinstance(value, str):
			#print(type(str(value)))
				data_array.append(str(value))
			else:
				#print(type(float(str(value))))
				data_array.append(float(str(value)))

		params = {"data": data_array}
		body = json.dumps(params)
		headers = {"Content-Type": "application/json"}
		r = requests.put("http://"+IoTtalkServer + ":" + IoTtalkServerPort + "/"+mac+"/"+IDF, headers = headers, data = body)
		with open("print.txt", "a+") as f:
			f.write("Push to IoTtalk response: %s\n" % r.status_code) # 200 OK

	except Exception as e:
		stre = str(e)
		traceback.print_exc(file=open('debug.txt','a+'))

if __name__ == "__main__":

	SpeedList = sys.argv[1]
	IDName = sys.argv[2]
	SUAName = sys.argv[3]
	IDGName = sys.argv[4]
	timestamp = sys.argv[5]

	mac = sys.argv[6]
	IDF = sys.argv[7]

	#SpeedList = "[[[13.89], [13.89], [13.89], [13.89], [13.89], [13.89]]]"
	#IDName = "sensor3"
	#SUAName = "device1@xxx.xxx.77.76"
	#IDGName = "G2"
	#timestamp = "2021-07-1021:21:22"

	print(SpeedList)
	str1 = str(SpeedList).replace(' ','')

	try:
		predict_send(SpeedList, IDName, SUAName, IDGName, timestamp, mac, IDF)

	except Exception as e:
		stre = str(e)
		traceback.print_exc(file=open('debug.txt','a+'))

