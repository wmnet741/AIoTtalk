# -*- coding: UTF-8 -*-
# python 2.7
# coding: UTF-8	#兼容中文字符，如果沒有這句，程序中有中文字符時，運行會報錯

global messagelist
messagelist = {}


# to AUA
# senderlist: [[u'868333030154875', 24.795977, 120.992361, u'0831_B', u'868333030154872', u'2020-08-31 17:53:50'], ...]
global senderlist
senderlist = []

# 1212 ADD
# for SIoT and MIoT
global buffer_msg
buffer_msg = []
global buffer_df
buffer_df = []

# 0111 ADD
global buffer_audio
buffer_audio = []

# 0225 ADD
global last_msglist
#last_msglist = []
# size = 5
last_msglist = [
    [u'1', [0.0, 0.0, u'1', u'1', u'0'], [0.0, 0.0, u'1', u'1', u'0']],
    [u'1', [0.0, 0.0, u'1', u'1', u'0'], [0.0, 0.0, u'1', u'1', u'0']],
    [u'1', [0.0, 0.0, u'1', u'1', u'0'], [0.0, 0.0, u'1', u'1', u'0']],
    [u'1', [0.0, 0.0, u'1', u'1', u'0'], [0.0, 0.0, u'1', u'1', u'0']],
    [u'1', [0.0, 0.0, u'1', u'1', u'0'], [0.0, 0.0, u'1', u'1', u'0']]
    ]