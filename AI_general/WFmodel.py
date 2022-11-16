from tensorflow.keras.models import load_model
import numpy as np
import sys, traceback
import os
import socket
import pickle
import config
import requests, json, sys, time, os

IoTtalkServer = config.IoTtalkServer
IoTtalkServerPort = config.IoTtalkServerPort

if __name__ == "__main__":
	try:	
		# get current folder
		cur_folder = os.path.abspath(os.getcwd())
		# print(cur_folder) # /home/wmnet/YiChun/aiottalk_EP/ModelExec
		model = load_model(cur_folder + '/speed_model.h5')
		X = eval(sys.argv[1])
		IDName = sys.argv[2]
		SUAName = sys.argv[3]
		IDGName = sys.argv[4]
		timestamp = sys.argv[5]

		mac = sys.argv[6]
		IDF = sys.argv[7]

		#X = [[[13.89]*1 for i in range(6)]]
		#with open('debug.txt', "a+") as f:
		#	f.write("%s\n" % X)
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
