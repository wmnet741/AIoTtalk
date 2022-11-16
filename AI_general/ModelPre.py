# -*- coding: UTF-8 -*-
# python 2.7
# coding: UTF-8	#兼容中文字符，如果沒有這句，程序中有中文字符時，運行會報錯

import requests, json, sys, time, os
import threading
import config
import socket
import pickle

## python ModelPre.py AI_LSTM AI_LSTM AI_LSTM PredictedSpeed-I SensedSpeed-O

IoTtalkServer = config.IoTtalkServer
IoTtalkServerPort = config.IoTtalkServerPort

def pull_value(mac,dfList):
	while (1):
	   r = requests.get("http://"+IoTtalkServer + ":" + IoTtalkServerPort + "/"+mac+"/"+dfList[1])
	   string = r.text
	   print("Msg string: %s\n" % string)
	   dic = eval(string)
	   if len(dic["samples"]) is not 0:
		   Msg = dic["samples"][0][1]
		   Msg = str(Msg).replace(' ','')

		   with open("print.txt", "a+") as f:
			   f.write("Pull from IoTtalk response: %s\n" % r.status_code) # 200 OK
			   f.write("Msg from IoTtalk: %s\n" % Msg)
		
		   # Msg: ['sensor3',54.5556,'device1@xxx.xxx.77.76','G2','2021-07-1021:21:22']
		   Msg = eval(Msg)

		   ## extract"sensor3" and vlaue --> ID 3, and call road_prediction_model(speed, r)
		   RoadID = filter(str.isdigit, Msg[0])
		   Speed = int(Msg[1])
		   IDName = Msg[0]
		   SUAName = Msg[2]
		   IDGName = Msg[3]
		   timestamp = Msg[4]
		   print(Msg[4])
		   road_prediction_model(Speed, RoadID, IDName, SUAName, IDGName, timestamp)
		   
	   time.sleep(5)

def road_prediction_model(Speed, RoadID, IDName, SUAName, IDGName, timestamp):
	global history_speed
	global pos_idx
	road = int(RoadID)
	# history_speed[i] = [[[13.89], [13.89], [13.89], [13.89], [13.89], [13.89]]]
	with open('print.txt', "a+") as f:
		f.write("history_speed: %s\n" % history_speed)

	history_speed[road-1][0][pos_idx[road-1]]=[Speed]
	pos_idx[road-1] = (pos_idx[road-1] + 1) % 6

	# str1 = str(history_speed[road-1]).replace(' ','')
	
	print("Road[%s] SpeedList: %s" % (RoadID, history_speed[road-1]))
	print("IDName: %s, SUAName: %s, IDGName: %s, timestamp: %s" % (str(IDName), str(SUAName), str(IDGName), str(timestamp)))

	## for general version
	global cmd
	cur_folder = os.path.abspath(os.getcwd())
	cmd = 'python3 ' + cur_folder + '/pred.py' + " " + str(history_speed[road-1]).replace(' ','') + " " + str(IDName) + " " + str(SUAName) + " " + str(IDGName) + " " + str(timestamp) + " " + sys.argv[1] + " " + sys.argv[4]

	try:
		os.system(cmd)
		# python3 /home/wmnet/YiChun/AI_general/pred.py [[[13.89],[13.89],[13.89],[13.89],[13.89],[13.89]]] sensor3 device1@xxx.xxx.77.76 G2 2021-07-1021:21:22 AI_LSTM PredictedSpeed-I
	except Exception as e:
		stre = str(e)
		traceback.print_exc(file=open('debug.txt','a+'))
	

if __name__ == "__main__":
	# AI device registration to IoTtalk
	mac = sys.argv[1]
	dfList = sys.argv[:]
	del dfList[0]
	del dfList[0]
	del dfList[0]
	del dfList[0]

	params={"profile": {"d_name": str(sys.argv[2]),
			"dm_name": str(sys.argv[3]), 
			"u_name": "yb",
			"is_sim": False,
			"df_list": dfList}}
	print(params)
	body=json.dumps(params)
	headers={"Content-Type": "application/json"}
	r = requests.post("http://"+IoTtalkServer + ":" + IoTtalkServerPort + "/" +mac, headers = headers, data = body)
	print(r.status_code)

	# WF_model initialization
	global history_speed
	global pos_idx
	history_speed = [
				[[[1.1],[1.1],[1.1],[1.1],[1.1],[1.1]]],
				[[[2.2],[2.2],[2.2],[2.2],[2.2],[2.2]]],
				[[[3.3],[3.3],[3.3],[3.3],[3.3],[3.3]]],
				[[[4.4],[4.4],[4.4],[4.4],[4.4],[4.4]]],
				[[[5.5],[5.5],[5.5],[5.5],[5.5],[5.5]]]
			]
	pos_idx = [0,0,0,0,0]

	# start pull_value thread
	pull_value_thread=threading.Thread(target = pull_value, args=(mac,dfList))
	pull_value_thread.daemon = True
	pull_value_thread.start()
	print("pull_value thread starts!\n")

	while(1):
		pass
