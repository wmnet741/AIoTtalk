from sip_message import SIPMessageApplication
from sip_cmd_options import set_options
from sip_dir import account_config
import time, msg_list

def sip_msg():

	#target = "device5@xxx.xxx.xxx.xxx"
	target = None
	# option's dictionary
	options_dict = {'account': None, 'trace_pjsip': False, 
			'trace_notifications': False, 'config_directory': None, 
			'trace_sip': False, 'message': None, 'batch_mode': False}
	options = set_options(options_dict)

	application = SIPMessageApplication()
	application.start(target, options)

def on_press(key):
    if key == keyboard.Key.esc:
        # Stop listener
        return False

if __name__ == "__main__":
    
    sip_msg()
    while True:
        time.sleep(5)




