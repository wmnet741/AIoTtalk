#!/usr/bin/python2
# -*- coding: UTF-8 -*-
import atexit
import os
import platform
import select
import shutil
import signal
import sys
import termios
import uuid
import threading
import time

from datetime import datetime
from itertools import chain
from optparse import OptionParser
from threading import Thread
from time import sleep

from application import log
from application.notification import NotificationCenter, NotificationData
from application.process import process
from application.python.queue import EventQueue
from application.system import makedirs
from twisted.internet import reactor

from sipsimple.account import Account, AccountManager, BonjourAccount
from sipsimple.audio import WavePlayer
from sipsimple.application import SIPApplication
from sipsimple.configuration import ConfigurationError
from sipsimple.configuration.settings import SIPSimpleSettings
from sipsimple.core import Engine, SIPCoreError, SIPURI, ToHeader
from sipsimple.lookup import DNSLookup
from sipsimple.session import Session
from sipsimple.streams import MediaStreamRegistry
from sipsimple.storage import FileStorage

from pyaudio_recorder import *


#from sipclient.configuration import config_directory
#from sipclient.configuration.account import AccountExtension
#from sipclient.configuration.datatypes import ResourcePath
#from sipclient.configuration.settings import SIPSimpleSettingsExtension
#from sipclient.log import Logger
#from sipclient.system import IPAddressMonitor

from sip_dir import account_config
from sip_account import AccountExtension
from sip_datatypes import ResourcePath
from sip_settings import SIPSimpleSettingsExtension
from sip_log import Logger
from sip_system import IPAddressMonitor

import msg_list

'''
class BonjourNeighbour(object):
    def __init__(self, neighbour, uri, display_name, host):
        self.display_name = display_name
        self.host = host
        self.neighbour = neighbour
        self.uri = uri


class InputThread(Thread):
    def __init__(self):
        Thread.__init__(self)
        self.setDaemon(True)
        self._old_terminal_settings = None

    def start(self):
        atexit.register(self._termios_restore)
        Thread.start(self)

    def run(self):
        notification_center = NotificationCenter()
        while True:
            chars = list(self._getchars())
            while chars:
                char = chars.pop(0)
                if char == '\x1b': # escape
                    if len(chars) >= 2 and chars[0] == '[' and chars[1] in ('A', 'B', 'C', 'D'): # one of the arrow keys
                        char = char + chars.pop(0) + chars.pop(0)
                notification_center.post_notification('SIPApplicationGotInput', sender=self, data=NotificationData(input=char))

    def stop(self):
        self._termios_restore()

    def _termios_restore(self):
        if self._old_terminal_settings is not None:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self._old_terminal_settings)

    def _getchars(self):
        fd = sys.stdin.fileno()
        if os.isatty(fd):
            self._old_terminal_settings = termios.tcgetattr(fd)
            new = termios.tcgetattr(fd)
            new[3] = new[3] & ~termios.ICANON & ~termios.ECHO
            new[6][termios.VMIN] = '\000'
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, new)
                if select.select([fd], [], [], None)[0]:
                    return sys.stdin.read(4192)
            finally:
                self._termios_restore()
        else:
            return os.read(fd, 4192)
'''

class RTPStatisticsThread(Thread):
    def __init__(self, application):
        Thread.__init__(self)
        self.setDaemon(True)
        self.application = application
        self.stopped = False

    def run(self):
        while not self.stopped:
            if self.application.active_session is not None and self.application.active_session.streams:
                audio_stream = self.application.active_session.streams[0]
                stats = audio_stream.statistics
                if stats is not None:
                    self.application.output.put('%s RTP audio statistics: RTT=%d ms, packet loss=%.1f%%, jitter RX/TX=%d/%d ms\n' % 
                            (datetime.now().replace(microsecond=0),
                            stats['rtt']['avg'] / 1000,
                            100.0 * stats['rx']['packets_lost'] / stats['rx']['packets'] if stats['rx']['packets'] else 0,
                            stats['rx']['jitter']['avg'] / 1000,
                            stats['tx']['jitter']['avg'] / 1000))
                
                try:
                    video_stream = self.application.active_session.streams[1]
                except IndexError:
                    pass
                else:
                    stats = video_stream.statistics
                    if stats is not None:
                        self.application.output.put('%s RTP video statistics: RTT=%d ms, packet loss=%.1f%%, jitter RX/TX=%d/%d ms\n' % 
                                (datetime.now().replace(microsecond=0),
                                stats['rtt']['avg'] / 1000,
                                100.0 * stats['rx']['packets_lost'] / stats['rx']['packets'] if stats['rx']['packets'] else 0,
                                stats['rx']['jitter']['avg'] / 1000,
                                stats['tx']['jitter']['avg'] / 1000))
                sleep(10)

    def stop(self):
        self.stopped = True


class CancelThread(Thread):
    def __init__(self, application):
        Thread.__init__(self)
        self.setDaemon(True)
        self.application = application
        self.stopped = False

    def run(self):
        while not self.stopped:
            self.application.end_session_if_needed()
            sleep(1)

    def stop(self):
        self.stopped = True


class SIPAudioApplication(SIPApplication):

    def __init__(self):
        self.account = None
        self.options = None
        self.target = None
        
        self.active_session = None
        self.answer_timers = {}
        self.hangup_timers = {}
        self.started_sessions = []
        self.incoming_sessions = []
        self.outgoing_session = None
        self.neighbours = {}
        self.registration_succeeded = False
        self.success = False
        
        # self.input =  None
        # self.output = None
        self.ip_address_monitor = IPAddressMonitor()
        self.logger = None
        self.rtp_statistics = None

        self.alert_tone_generator = None
        self.voice_tone_generator = None
        self.wave_inbound_ringtone = None
        self.wave_outbound_ringtone = None
        self.tone_ringtone = None
        self.hold_tone = None

        self.ignore_local_hold = False
        self.ignore_local_unhold = False

        self.batch_mode = False
        self.stop_call_thread = None
        self.session_spool_dir = None

        self.EndCall_flag = True

    def _write(self, message):
        if isinstance(message, unicode):
            message = message.encode(sys.getfilesystemencoding())

        with open('debug.txt', "a+") as f:
			f.write('---_write func---\n')

        sys.stdout.write(message)
        sys.stdout.flush()

    def start(self, target, options):
        notification_center = NotificationCenter()
        '''
        with open('debug.txt', "a+") as f:
			f.write("start_func\n")
        '''

        if options.daemonize:
            process.daemonize()
        
        self.options = options
        self.target = target
        self.batch_mode = options.batch_mode
        self.enable_video = options.enable_video
        #self.input = InputThread() if not self.batch_mode else None
        #self.output = EventQueue(self._write)
        self.logger = Logger(sip_to_stdout=options.trace_sip, pjsip_to_stdout=options.trace_pjsip, notifications_to_stdout=options.trace_notifications)
        
        notification_center.add_observer(self, sender=self)
        #notification_center.add_observer(self, sender=self.input)
        notification_center.add_observer(self, name='SIPSessionNewIncoming')
        notification_center.add_observer(self, name='RTPStreamDidChangeRTPParameters')
        notification_center.add_observer(self, name='RTPStreamICENegotiationDidSucceed')
        notification_center.add_observer(self, name='RTPStreamICENegotiationDidFail')

        # if self.input:
        #    self.input.start()
        #self.output.start()

        log.level.current = log.level.WARNING # get rid of twisted messages

        Account.register_extension(AccountExtension)
        # BonjourAccount.register_extension(AccountExtension)
        SIPSimpleSettings.register_extension(SIPSimpleSettingsExtension)
        
        # self.config_directory = options.config_directory or config_directory
        self.config_directory = options.config_directory or account_config
        
        try:
            # self.output.put("Using config directory: %s\n" % self.config_directory)
            # SIPApplication.start(self, FileStorage(self.config_directory))
            SIPApplication.start(self, FileStorage(account_config))
            with open('debug.txt', "a+") as f:
			    f.write("Using account_config: %s\n" % account_config)
        except ConfigurationError, e:
            # self.output.put("Failed to load sipclient's configuration: %s\n" % str(e))
            # self.output.put("If an old configuration file is in place, delete it or move it and recreate the configuration using the sip_settings script.\n")
            # self.output.stop()
            with open('debug.txt', "a+") as f:
				f.write("Failed to load sipclient's configuration: %s\n" % str(e))

        if options.spool_dir:
            self.spool_dir = options.spool_dir
        else:
            # self.spool_dir = "%s/spool/sesssions" % self.config_directory
            self.spool_dir = "%s/spool/sesssions" % account_config
        
        try:
            makedirs(self.spool_dir)
        except Exception as e:
            log.error('Failed to create spool directory at {directory}: {exception!s}'.format(directory=self.spool_dir, exception=e))
        else:
            # self.output.put("Using spool directory %s\n" % self.spool_dir)
            with open('debug.txt', "a+") as f:
				f.write("Using spool directory %s\n" % self.spool_dir)
        
    def print_help(self):
        message  = 'Available control keys:\n'
        message += '  s: toggle SIP trace on the console\n'
        message += '  j: toggle PJSIP trace on the console\n'
        message += '  n: toggle notifications trace on the console\n'
        message += '  p: toggle printing RTP statistics on the console\n'
        message += '  h: hang-up the active session\n'
        message += '  r: toggle audio recording\n'
        message += '  m: mute the microphone\n'
        message += '  i: change audio input device\n'
        message += '  o: change audio output device\n'
        message += '  a: change audio alert device\n'
        message += '  SPACE: hold/unhold\n'
        message += '  Ctrl-d: quit the program\n'
        message += '  ?: display this help message\n'
        # self.output.put('\n'+message+'\n')
        #with open('debug.txt', "a+") as f:
		#	f.write('\n'+message+'\n')

    def _NH_SIPApplicationWillStart(self, notification):
        account_manager = AccountManager()
        notification_center = NotificationCenter()
        settings = SIPSimpleSettings()

        if 'armv7' in platform.platform() and settings.audio.echo_canceller.enabled:
            # self.output.put("Disable echo canceller on ARM architecture\n")
            with open('debug.txt', "a+") as f:
                f.write("Disable echo canceller on ARM architecture\n")
            settings.audio.echo_canceller.enabled = False
            settings.save()

        for account in account_manager.iter_accounts():
            if isinstance(account, Account):
                account.sip.register = False
                account.presence.enabled = False
                account.xcap.enabled = False
                account.message_summary.enabled = False

        if self.options.account is None:
            self.account = account_manager.default_account
        else:
            possible_accounts = [account for account in account_manager.iter_accounts() if self.options.account in account.id and account.enabled]
            if len(possible_accounts) > 1:
                #self.output.put('More than one account exists which matches %s: %s\n' % (self.options.account, ', '.join(sorted(account.id for account in possible_accounts))))
                #self.output.stop()
                self.stop()
                self.end_cancel_thread()
                return
            elif len(possible_accounts) == 0:
                #self.output.put('No enabled account that matches %s was found. Available and enabled accounts: %s\n' % (self.options.account, ', '.join(sorted(account.id for account in account_manager.get_accounts() if account.enabled))))
                #self.output.stop()
                self.stop()
                self.end_cancel_thread()
                return
            else:
                self.account = possible_accounts[0]
        notification_center.add_observer(self, sender=self.account)

        if isinstance(self.account, Account) and self.target is None:
            self.account.sip.register = True
            self.account.presence.enabled = False
            self.account.xcap.enabled = False
            self.account.message_summary.enabled = False
        # self.output.put('Using account %s\n' % self.account.id)
        with open('debug.txt', "a+") as f:
				f.write('Using account %s\n' % self.account.id)
        
        self.logger.start()
        if settings.logs.trace_sip and self.logger._siptrace_filename is not None:
            #self.output.put('Logging SIP trace to file "%s"\n' % self.logger._siptrace_filename)
            with open('debug.txt', "a+") as f:
                f.write('Logging SIP trace to file "%s"\n' % self.logger._siptrace_filename)
        if settings.logs.trace_pjsip and self.logger._pjsiptrace_filename is not None:
            #self.output.put('Logging PJSIP trace to file "%s"\n' % self.logger._pjsiptrace_filename)
            with open('debug.txt', "a+") as f:
                f.write('Logging PJSIP trace to file "%s"\n' % self.logger._pjsiptrace_filename) 
        if settings.logs.trace_notifications and self.logger._notifications_filename is not None:
            # self.output.put('Logging notifications trace to file "%s"\n' % self.logger._notifications_filename)
            with open('debug.txt', "a+") as f:
                f.write('Logging notifications trace to file "%s"\n' % self.logger._notifications_filename) 

        if self.options.disable_sound:
            settings.audio.input_device = None
            settings.audio.output_device = None
            settings.audio.alert_device = None

        if self.options.enable_default_devices:
            settings.audio.input_device = 'system_default'
            settings.audio.output_device = 'system_default'
            settings.audio.alert_device = 'system_default'

    def _NH_SIPApplicationDidStart(self, notification):
        engine = Engine()
        settings = SIPSimpleSettings()

        engine.trace_sip = self.logger.sip_to_stdout or settings.logs.trace_sip
        engine.log_level = settings.logs.pjsip_level if (self.logger.pjsip_to_stdout or settings.logs.trace_pjsip) else 0
        
        self.ip_address_monitor.start()

        # self.output.put('Available audio input devices: %s\n' % ', '.join(['None', 'system_default'] + sorted(engine.input_devices)))
        # self.output.put('Available audio output devices: %s\n' % ', '.join(['None', 'system_default'] + sorted(engine.output_devices)))
        
        if engine.video_devices:
            with open('debug.txt', "a+") as f:
			    f.write('video_devices is enable\n')
            # self.output.put('Available cameras: %s\n' % ', '.join(sorted(engine.video_devices)))
        else:
            if self.enable_video:
                # self.output.put('No camera present, video is disabled')
                self.enable_video = False
                with open('debug.txt', "a+") as f:
			        f.write('No camera present, video is disabled\n')
        '''
        if self.voice_audio_mixer.input_device == 'system_default':
            self.output.put('Using audio input device: %s (system default device)\n' % self.voice_audio_mixer.real_input_device)
        else:
            self.output.put('Using audio input device: %s\n' % self.voice_audio_mixer.input_device)
        if self.voice_audio_mixer.output_device == 'system_default':
            self.output.put('Using audio output device: %s (system default device)\n' % self.voice_audio_mixer.real_output_device)
        else:
            self.output.put('Using audio output device: %s\n' % self.voice_audio_mixer.output_device)
        if self.alert_audio_mixer.output_device == 'system_default':
            self.output.put('Using audio alert device: %s (system default device)\n' % self.alert_audio_mixer.real_output_device)
        else:
            self.output.put('Using audio alert device: %s\n' % self.alert_audio_mixer.output_device)
        '''

        if not self.batch_mode:
            self.print_help()

        inbound_ringtone = self.account.sounds.audio_inbound.sound_file if self.account.sounds.audio_inbound is not None else None
        outbound_ringtone = settings.sounds.audio_outbound
        if inbound_ringtone:
            self.wave_inbound_ringtone = WavePlayer(self.alert_audio_mixer, inbound_ringtone.path.normalized, volume=inbound_ringtone.volume, loop_count=0, pause_time=2)
            self.alert_audio_bridge.add(self.wave_inbound_ringtone)
        if outbound_ringtone:
            self.wave_outbound_ringtone = WavePlayer(self.voice_audio_mixer, outbound_ringtone.path.normalized, volume=outbound_ringtone.volume, loop_count=0, pause_time=2)
            self.voice_audio_bridge.add(self.wave_outbound_ringtone)
        self.tone_ringtone = WavePlayer(self.voice_audio_mixer, ResourcePath('sounds/ring_tone.wav').normalized, loop_count=0, pause_time=6)
        self.voice_audio_bridge.add(self.tone_ringtone)
        self.hold_tone = WavePlayer(self.voice_audio_mixer, ResourcePath('sounds/hold_tone.wav').normalized, loop_count=0, pause_time=30, volume=50)
        self.voice_audio_bridge.add(self.hold_tone)

        if self.target is not None:
            if isinstance(self.account, BonjourAccount) and '@' not in self.target:
                # self.output.put('Bonjour mode requires a host in the destination address\n')
                self.stop()
                self.end_cancel_thread()
                with open('debug.txt', "a+") as f:
			        f.write('Bonjour mode requires a host in the destination address\n')
                return
            if '@' not in self.target:
                self.target = '%s@%s' % (self.target, self.account.id.domain)
            if not self.target.startswith('sip:') and not self.target.startswith('sips:'):
                self.target = 'sip:' + self.target
            try:
                self.target = SIPURI.parse(self.target)
            except SIPCoreError:
                #self.output.put('Illegal SIP URI: %s\n' % self.target)
                self.stop()
                with open('debug.txt', "a+") as f:
			        f.write('Illegal SIP URI: %s\n' % self.target)
            else:
                if '.' not in self.target.host and not isinstance(self.account, BonjourAccount):
                    self.target.host = '%s.%s' % (self.target.host, self.account.id.domain)
                lookup = DNSLookup()
                notification_center = NotificationCenter()
                settings = SIPSimpleSettings()
                notification_center.add_observer(self, sender=lookup)
                if isinstance(self.account, Account) and self.account.sip.outbound_proxy is not None:
                    uri = SIPURI(host=self.account.sip.outbound_proxy.host, port=self.account.sip.outbound_proxy.port, parameters={'transport': self.account.sip.outbound_proxy.transport})
                elif isinstance(self.account, Account) and self.account.sip.always_use_my_proxy:
                    uri = SIPURI(host=self.account.id.domain)
                else:
                    uri = self.target

                self.session_spool_dir = self.spool_dir + "/" + (self.options.external_id or str(uuid.uuid1()))

                lookup.lookup_sip_proxy(uri, settings.sip.transport_list)

                try:
                    makedirs(self.session_spool_dir)
                except Exception as e:
                    log.error('Failed to create session spool directory at {directory}: {exception!s}'.format(directory=self.session_spool_dir, exception=e))
                else:    
                    if self.stop_call_thread is None:
                        self.stop_call_thread = CancelThread(self)
                        self.stop_call_thread.start()
                    # self.output.put("To stop the call: touch %s/stop\n" % self.session_spool_dir)
                    with open('debug.txt', "a+") as f:
			            f.write("To stop the call: touch %s/stop\n" % self.session_spool_dir)

    def _NH_SIPApplicationWillEnd(self, notification):
        if isinstance(self.account, Account):
            self.account.sip.register = False
        self.ip_address_monitor.stop()

    def _NH_SIPApplicationDidEnd(self, notification):
        if self.input:
            self.input.stop()
        self.output.stop()
        self.output.join()

    def _NH_SIPEngineDetectedNATType(self, notification):
        SIPApplication._NH_SIPEngineDetectedNATType(self, notification)
        if notification.data.succeeded:
            #self.output.put('Detected NAT type: %s\n' % notification.data.nat_type)
            with open('debug.txt', "a+") as f:
                f.write('Detected NAT type: %s\n' % notification.data.nat_type)

    def _NH_SIPApplicationGotInput(self, notification):
        engine = Engine()
        notification_center = NotificationCenter()
        settings = SIPSimpleSettings()
        with open('debug.txt', "a+") as f:
            f.write('GotInput_func\n')
        if notification.data.input == '\x04':
            if self.active_session is not None:
                #self.output.put('Ending audio session...\n')
                with open('debug.txt', "a+") as f:
                    f.write('Ending audio session...\n')
                self.active_session.end()
            elif self.outgoing_session is not None:
                #self.output.put('Cancelling audio session...\n')
                with open('debug.txt', "a+") as f:
                    f.write('Cancelling audio session...\n')
                self.outgoing_session.end()
            else:
                self.stop()
                self.end_cancel_thread()
        elif notification.data.input == '?':
            self.print_help()
        elif notification.data.input in ('y', 'n') and self.incoming_sessions:
            accepted_types = ['video', 'audio'] if self.enable_video else ['audio']
            session = self.incoming_sessions.pop(0)
            if notification.data.input == 'y':
                session.accept([stream for stream in session.proposed_streams if stream.type in accepted_types])
            else:
                session.reject()
        elif notification.data.input == 'm':
            self.voice_audio_mixer.muted = not self.voice_audio_mixer.muted
            # self.output.put('The microphone is now %s\n' % ('muted' if self.voice_audio_mixer.muted else 'unmuted'))
            with open('debug.txt', "a+") as f:
                f.write('The microphone is now %s\n' % ('muted' if self.voice_audio_mixer.muted else 'unmuted'))
        elif notification.data.input == 'i':
            input_devices = [None, u'system_default'] + sorted(engine.input_devices)
            if self.voice_audio_mixer.input_device in input_devices:
                old_input_device = self.voice_audio_mixer.input_device
            else:
                old_input_device = None
            tail_length = settings.audio.echo_canceller.tail_length if settings.audio.echo_canceller.enabled else 0
            new_input_device = input_devices[(input_devices.index(old_input_device)+1) % len(input_devices)]
            try:
                self.voice_audio_mixer.set_sound_devices(new_input_device, self.voice_audio_mixer.output_device, tail_length)
            except SIPCoreError, e:
                # self.output.put('Failed to set input device to %s: %s\n' % (new_input_device, str(e)))
                with open('debug.txt', "a+") as f:
                    f.write('Failed to set input device to %s: %s\n' % (new_input_device, str(e)))
            else:
                if new_input_device == u'system_default':
                    # self.output.put('Audio input device changed to %s (system default device)\n' % self.voice_audio_mixer.real_input_device)
                    with open('debug.txt', "a+") as f:
                        f.write('Audio input device changed to %s (system default device)\n' % self.voice_audio_mixer.real_input_device)
                else:
                    # self.output.put('Audio input device changed to %s\n' % new_input_device)
                    with open('debug.txt', "a+") as f:
                        f.write('Audio input device changed to %s\n' % new_input_device)
        elif notification.data.input == 'o':
            output_devices = [None, u'system_default'] + sorted(engine.output_devices)
            if self.voice_audio_mixer.output_device in output_devices:
                old_output_device = self.voice_audio_mixer.output_device
            else:
                old_output_device = None
            tail_length = settings.audio.echo_canceller.tail_length if settings.audio.echo_canceller.enabled else 0
            new_output_device = output_devices[(output_devices.index(old_output_device)+1) % len(output_devices)]
            try:
                self.voice_audio_mixer.set_sound_devices(self.voice_audio_mixer.input_device, new_output_device, tail_length)
            except SIPCoreError, e:
                #self.output.put('Failed to set output device to %s: %s\n' % (new_output_device, str(e)))
                with open('debug.txt', "a+") as f:
                    f.write('Failed to set output device to %s: %s\n' % (new_output_device, str(e)))
            else:
                if new_output_device == u'system_default':
                    #self.output.put('Audio output device changed to %s (system default device)\n' % self.voice_audio_mixer.real_output_device)
                    pass
                else:
                    #self.output.put('Audio output device changed to %s\n' % new_output_device)
                    pass
        elif notification.data.input == 'a':
            output_devices = [None, u'system_default'] + sorted(engine.output_devices)
            if self.alert_audio_mixer.output_device in output_devices:
                old_output_device = self.alert_audio_mixer.output_device
            else:
                old_output_device = None
            tail_length = settings.audio.echo_canceller.tail_length if settings.audio.echo_canceller.enabled else 0
            new_output_device = output_devices[(output_devices.index(old_output_device)+1) % len(output_devices)]
            try:
                self.alert_audio_mixer.set_sound_devices(self.alert_audio_mixer.input_device, new_output_device, tail_length)
            except SIPCoreError, e:
                #self.output.put('Failed to set alert device to %s: %s\n' % (new_output_device, str(e)))
                pass
            else:
                if new_output_device == u'system_default':
                    #self.output.put('Audio alert device changed to %s (system default device)\n' % self.alert_audio_mixer.real_output_device)
                    pass
                else:
                    #self.output.put('Audio alert device changed to %s\n' % new_output_device)
                    pass
        elif notification.data.input == 'h':
            if self.active_session is not None:
                #self.output.put('Ending audio session...\n')
                with open('debug.txt', "a+") as f:
                    f.write('Ending audio session...\n')
                self.active_session.end()
            elif self.outgoing_session is not None:
                #self.output.put('Cancelling audio session...\n')
                with open('debug.txt', "a+") as f:
                    f.write('Cancelling audio session...\n')
                self.outgoing_session.end()
        elif notification.data.input == ' ':
            if self.active_session is not None:
                if self.active_session.on_hold:
                    self.active_session.unhold()
                else:
                    self.active_session.hold()
        elif notification.data.input in ('0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '*', '#', 'A', 'B', 'C', 'D'):
            if self.active_session is not None:
                try:
                    audio_stream = self.active_session.streams[0]
                except IndexError:
                    pass
                else:
                    digit = notification.data.input
                    filename = 'sounds/dtmf_%s_tone.wav' % {'*': 'star', '#': 'pound'}.get(digit, digit)
                    wave_player = WavePlayer(self.voice_audio_mixer, ResourcePath(filename).normalized)
                    notification_center.add_observer(self, sender=wave_player)
                    audio_stream.send_dtmf(digit)
                    if self.active_session.account.rtp.inband_dtmf:
                        audio_stream.bridge.add(wave_player)
                    self.voice_audio_bridge.add(wave_player)
                    wave_player.start()
        elif notification.data.input in ('\x1b[A', '\x1b[D') and len(self.started_sessions) > 0: # UP and LEFT
            if self.active_session is None:
                self.active_session = self.started_sessions[0]
                self.active_session.unhold()
                self.ignore_local_unhold = True
            elif len(self.started_sessions) > 1:
                self.active_session.hold()
                self.active_session = self.started_sessions[self.started_sessions.index(self.active_session)-1]
                self.active_session.unhold()
                self.ignore_local_unhold = True
            else:
                return
            identity = str(self.active_session.remote_identity.uri)
            if self.active_session.remote_identity.display_name:
                identity = '"%s" <%s>' % (self.active_session.remote_identity.display_name, identity)
            #self.output.put('Active audio session: "%s" (%d/%d)\n' % (identity, self.started_sessions.index(self.active_session)+1, len(self.started_sessions)))
        elif notification.data.input in ('\x1b[B', '\x1b[C') and len(self.started_sessions) > 0: # DOWN and RIGHT
            if self.active_session is None:
                self.active_session = self.started_sessions[0]
                self.active_session.unhold()
                self.ignore_local_unhold = True
            elif len(self.started_sessions) > 1:
                self.active_session.hold()
                self.active_session = self.started_sessions[(self.started_sessions.index(self.active_session)+1) % len(self.started_sessions)]
                self.active_session.unhold()
                self.ignore_local_unhold = True
            else:
                return
            identity = str(self.active_session.remote_identity.uri)
            if self.active_session.remote_identity.display_name:
                identity = '"%s" <%s>' % (self.active_session.remote_identity.display_name, identity)
            #self.output.put('Active audio session: "%s" (%d/%d)\n' % (identity, self.started_sessions.index(self.active_session)+1, len(self.started_sessions)))
        elif notification.data.input == 'r':
            if self.active_session is None or not self.active_session.streams:
                return
            session = self.active_session
            audio_stream = self.active_session.streams[0]
            if audio_stream.recorder is not None:
                audio_stream.stop_recording()
            else:
                direction = session.direction
                remote = "%s@%s" % (session.remote_identity.uri.user, session.remote_identity.uri.host)
                filename = "%s-%s-%s.wav" % (datetime.now().strftime("%Y%m%d-%H%M%S"), remote, direction)
                path = os.path.join(settings.audio.directory.normalized, session.account.id)
                audio_stream.start_recording(os.path.join(path, filename))
        elif notification.data.input == 'p':
            if self.rtp_statistics is None:
                self.rtp_statistics = RTPStatisticsThread(self)
                self.rtp_statistics.start()
                #self.output.put('Output of RTP statistics on console is now activated\n')
                with open('debug.txt', "a+") as f:
                    f.write('Output of RTP statistics on console is now activated\n')
            else:
                self.rtp_statistics.stop()
                self.rtp_statistics = None
                #self.output.put('Output of RTP statistics on console is now dectivated\n')
                with open('debug.txt', "a+") as f:
                    f.write('Output of RTP statistics on console is now dectivated\n')
        elif notification.data.input == 'j':
            self.logger.pjsip_to_stdout = not self.logger.pjsip_to_stdout
            engine.log_level = settings.logs.pjsip_level if (self.logger.pjsip_to_stdout or settings.logs.trace_pjsip) else 0
            #self.output.put('PJSIP tracing to console is now %s\n' % ('activated' if self.logger.pjsip_to_stdout else 'deactivated'))
            with open('debug.txt', "a+") as f:
                f.write('PJSIP tracing to console is now %s\n' % ('activated' if self.logger.pjsip_to_stdout else 'deactivated'))
        elif notification.data.input == 'n':
            self.logger.notifications_to_stdout = not self.logger.notifications_to_stdout
            #self.output.put('Notification tracing to console is now %s.\n' % ('activated' if self.logger.notifications_to_stdout else 'deactivated'))
            with open('debug.txt', "a+") as f:
                f.write('Notification tracing to console is now %s.\n' % ('activated' if self.logger.notifications_to_stdout else 'deactivated'))
        elif notification.data.input == 's':
            self.logger.sip_to_stdout = not self.logger.sip_to_stdout
            engine.trace_sip = self.logger.sip_to_stdout or settings.logs.trace_sip
            #self.output.put('SIP tracing to console is now %s\n' % ('activated' if self.logger.sip_to_stdout else 'deactivated'))
            with open('debug.txt', "a+") as f:
                f.write('SIP tracing to console is now %s\n' % ('activated' if self.logger.sip_to_stdout else 'deactivated'))

    def _NH_SIPEngineGotException(self, notification):
        #self.output.put('An exception occured within the SIP core:\n%s\n' % notification.data.traceback)
        with open('debug.txt', "a+") as f:
            f.write('An exception occured within the SIP core:\n%s\n' % notification.data.traceback)

    def _NH_SIPAccountRegistrationDidSucceed(self, notification):
        if self.registration_succeeded:
            return
        contact_header = notification.data.contact_header
        contact_header_list = notification.data.contact_header_list
        expires = notification.data.expires
        registrar = notification.data.registrar
        message = '%s Registered contact "%s" for sip:%s at %s:%d;transport=%s (expires in %d seconds).\n' % (datetime.now().replace(microsecond=0), contact_header.uri, self.account.id, registrar.address, registrar.port, registrar.transport, expires)
        if len(contact_header_list) > 1:
            message += 'Other registered contacts:\n%s\n' % '\n'.join(['  %s (expires in %s seconds)' % (str(other_contact_header.uri), other_contact_header.expires) for other_contact_header in contact_header_list if other_contact_header.uri != notification.data.contact_header.uri])
        # self.output.put(message)
        with open('debug.txt', "a+") as f:
			f.write(message)
        
        self.registration_succeeded = True

    def _NH_SIPAccountRegistrationDidFail(self, notification):
        #self.output.put('%s Failed to register contact for sip:%s: %s (retrying in %.2f seconds)\n' % (datetime.now().replace(microsecond=0), self.account.id, notification.data.error, notification.data.retry_after))
        with open('debug.txt', "a+") as f:
            f.write('%s Failed to register contact for sip:%s: %s (retrying in %.2f seconds)\n' % (datetime.now().replace(microsecond=0), self.account.id, notification.data.error, notification.data.retry_after))
        self.registration_succeeded = False

    def _NH_SIPAccountRegistrationDidEnd(self, notification):
        #self.output.put('%s Registration ended.\n' % datetime.now().replace(microsecond=0))
        with open('debug.txt', "a+") as f:
            f.write('%s Registration ended.\n' % datetime.now().replace(microsecond=0))

    def _NH_BonjourAccountRegistrationDidSucceed(self, notification):
        #self.output.put('%s Registered Bonjour contact "%s"\n' % (datetime.now().replace(microsecond=0), notification.data.name))
        pass

    def _NH_BonjourAccountRegistrationDidFail(self, notification):
        #self.output.put('%s Failed to register Bonjour contact: %s\n' % (datetime.now().replace(microsecond=0), notification.data.reason))
        pass

    def _NH_BonjourAccountRegistrationDidEnd(self, notification):
        #self.output.put('%s Registration ended.\n' % datetime.now().replace(microsecond=0))
        pass

    def _NH_BonjourAccountDidAddNeighbour(self, notification):
        neighbour, record = notification.data.neighbour, notification.data.record
        now = datetime.now().replace(microsecond=0)
        #self.output.put('%s Discovered Bonjour neighbour: "%s (%s)" <%s>\n' % (now, record.name, record.host, record.uri))
        self.neighbours[neighbour] = BonjourNeighbour(neighbour, record.uri, record.name, record.host)

    def _NH_BonjourAccountDidUpdateNeighbour(self, notification):
        neighbour, record = notification.data.neighbour, notification.data.record
        now = datetime.now().replace(microsecond=0)
        try:
            bonjour_neighbour = self.neighbours[neighbour]
        except KeyError:
            #self.output.put('%s Discovered Bonjour neighbour: "%s (%s)" <%s>\n' % (now, record.name, record.host, record.uri))
            self.neighbours[neighbour] = BonjourNeighbour(neighbour, record.uri, record.name, record.host)
        else:
            #self.output.put('%s Updated Bonjour neighbour: "%s (%s)" <%s>\n' % (now, record.name, record.host, record.uri))
            bonjour_neighbour.display_name = record.name
            bonjour_neighbour.host = record.host
            bonjour_neighbour.uri = record.uri

    def _NH_BonjourAccountDidRemoveNeighbour(self, notification):
        neighbour = notification.data.neighbour
        now = datetime.now().replace(microsecond=0)
        try:
            bonjour_neighbour = self.neighbours.pop(neighbour)
        except KeyError:
            pass
        else:
            self.output.put('%s Bonjour neighbour left: "%s (%s)" <%s>\n' % (now, bonjour_neighbour.display_name, bonjour_neighbour.host, bonjour_neighbour.uri))

    def _NH_DNSLookupDidSucceed(self, notification):
        notification_center = NotificationCenter()
        
        result_text = ', '.join(('%s:%s (%s)' % (result.address, result.port, result.transport.upper()) for result in notification.data.result))
        #self.output.put(u"\nDNS lookup for %s succeeded: %s\n" % (self.target.host, result_text))
        with open('debug.txt', "a+") as f:
            f.write(u"\nDNS lookup for %s succeeded: %s\n" % (self.target.host, result_text))

        if self.end_session_if_needed():
            self.stop()
            self.end_cancel_thread()
        
        self.outgoing_session = session = Session(self.account)
        notification_center.add_observer(self, sender=session)
        streams = [MediaStreamRegistry.AudioStream(), MediaStreamRegistry.VideoStream()] if self.enable_video else [MediaStreamRegistry.AudioStream()]
        session.connect(ToHeader(self.target), routes=notification.data.result, streams=streams)

    def _NH_DNSLookupDidFail(self, notification):
        #self.output.put('DNS lookup failed: %s\n' % notification.data.error)
        self.stop()
        self.end_cancel_thread()

    def auto_answer_allowed(self, uri):
       if not self.options.auto_answer_uris:
           #self.output.put('Auto answer allowed for %s\n' % uri)
            with open('debug.txt', "a+") as f:
                f.write('Auto answer allowed for %s\n' % uri)
            return True

       uri = uri.split(":")[1]
       auto_answer_uris = self.options.auto_answer_uris.split(",")

       if uri in auto_answer_uris:
           #self.output.put('Auto answer allowed for %s\n' % uri)
           with open('debug.txt', "a+") as f:
                f.write('Auto answer allowed for %s\n' % uri)
           return True

       #self.output.put('Auto answer denied for %s\n' % uri)
       with open('debug.txt', "a+") as f:
            f.write('Auto answer allowed for %s\n' % uri)
       return False

    def _NH_SIPSessionNewIncoming(self, notification):
        session = notification.sender
        for stream in notification.data.streams:
            if stream.type == 'audio':
                break
        else:
            session.reject(415)
            return

        self.session_spool_dir = self.spool_dir + "/" + str(uuid.uuid1())

        try:
            makedirs(self.session_spool_dir)
        except Exception as e:
            log.error('Failed to create session spool directory at {directory}: {exception!s}'.format(directory=self.session_spool_dir, exception=e))
        else:    
            if self.stop_call_thread is None:
                self.stop_call_thread = CancelThread(self)
                self.stop_call_thread.start()
            #self.output.put("To stop the call: touch %s/stop\n" % self.session_spool_dir)
            with open('debug.txt', "a+") as f:
                f.write("To stop the call: touch %s/stop\n" % self.session_spool_dir)

        notification_center = NotificationCenter()
        notification_center.add_observer(self, sender=session)
        accepted_types = ['video', 'audio'] if self.enable_video else ['audio']

        if self.options.auto_answer_interval is not None and self.auto_answer_allowed(str(session.remote_identity.uri)):
            if self.options.auto_answer_interval == 0:
                session.accept([stream for stream in session.proposed_streams if stream.type in accepted_types])
                return
            else:
                def auto_answer():
                    self.incoming_sessions.remove(session)
                    session.accept([stream for stream in session.proposed_streams if stream.type in accepted_types])
                timer = reactor.callLater(self.options.auto_answer_interval, auto_answer)
                self.answer_timers[id(session)] = timer
        session.send_ring_indication()
        self.incoming_sessions.append(session)
        if len(self.incoming_sessions) == 1:
            self._print_new_session()
            if not self.started_sessions:
                if self.wave_inbound_ringtone:
                    self.wave_inbound_ringtone.start()
            else:
                self.tone_ringtone.start()

    def _NH_SIPSessionNewOutgoing(self, notification):
        session = notification.sender
        local_identity = str(session.local_identity.uri)
        if session.local_identity.display_name:
            local_identity = '"%s" <%s>' % (session.local_identity.display_name, local_identity)
        remote_identity = str(session.remote_identity.uri)
        if session.remote_identity.display_name:
            remote_identity = '"%s" <%s>' % (session.remote_identity.display_name, remote_identity)
        #self.output.put("Initiating SIP %s session from '%s' to '%s' via %s...\n" % ('video' if self.enable_video else 'audio', local_identity, remote_identity, session.route))
        with open('debug.txt', "a+") as f:
            f.write("Initiating SIP %s session from '%s' to '%s' via %s...\n" % ('video' if self.enable_video else 'audio', local_identity, remote_identity, session.route))


    def _NH_SIPSessionGotRingIndication(self, notification):

        if self.wave_outbound_ringtone:
            self.wave_outbound_ringtone.start()

    def _NH_SIPSessionDidFail(self, notification):
        session = notification.sender
        if session.direction == 'incoming' and session in self.incoming_sessions:
            if self.wave_inbound_ringtone:
                self.wave_inbound_ringtone.stop()
            self.tone_ringtone.stop()
        elif session.direction == 'outgoing':
            if self.wave_outbound_ringtone:
                self.wave_outbound_ringtone.stop()

        if notification.data.failure_reason == 'Call completed elsewhere' or notification.data.code == 487:
            #self.output.put('Session cancelled\n')
            with open('debug.txt', "a+") as f:
                f.write('Session cancelled\n')
            if session is self.outgoing_session:
                self.stop()
                self.end_cancel_thread()
            if session in self.incoming_sessions:
                self.incoming_sessions.remove(session)
        elif notification.data.failure_reason == 'user request':
            #self.output.put('Session rejected by user (%d %s)\n' % (notification.data.code, notification.data.reason))
            with open('debug.txt', "a+") as f:
                f.write('Session rejected by user (%d %s)\n' % (notification.data.code, notification.data.reason))
            if notification.sender is self.outgoing_session:
                self.stop()
                self.end_cancel_thread()
        else:
            #self.output.put('Session failed: %s\n' % notification.data.failure_reason)
            with open('debug.txt', "a+") as f:
                f.write('Session failed: %s\n' % notification.data.failure_reason)
            if session is self.outgoing_session:
               self.stop()
               self.end_cancel_thread()
        
        if id(session) in self.answer_timers:
            timer = self.answer_timers[id(session)]
            if timer.active():
                timer.cancel()
            del self.answer_timers[id(session)]
        if self.incoming_sessions:
            self._print_new_session()
        elif session.direction == 'incoming':
            if self.wave_inbound_ringtone:
                self.wave_inbound_ringtone.stop()
            self.tone_ringtone.stop()

        self.success = False

    def _NH_SIPSessionWillStart(self, notification):

        session = notification.sender
        if session.direction == 'incoming':
            if self.wave_inbound_ringtone:
                self.wave_inbound_ringtone.stop()
            if not self.incoming_sessions:
                self.tone_ringtone.stop()
        else:
            if self.wave_outbound_ringtone:
                self.wave_outbound_ringtone.stop()
        if id(session) in self.answer_timers:
            timer = self.answer_timers[id(session)]
            if timer.active():
                timer.cancel()
            del self.answer_timers[id(session)]

    def rec_timer(self):
        ############################################
        # 雙數編號: 用sipsimple的recorder去側錄 # .._0.wav, .._2.wav
        # 單數編號: 用pyaudio的recorder去側錄/pyaudio_recorder.py # .._1.wav, .._3.wav
        ############################################
        session = self.active_session
        audio_stream = self.active_session.streams[0]
        label = 0 #用來編號音檔用
        userName = session.remote_identity.uri.user #device10
        filename = userName + "_" + str(label) + ".wav"

        while True:
            ## 雙數編號
            if (label % 2) == 0:
                if audio_stream.recorder is not None:
                    time.sleep(5)
                    audio_stream.stop_recording()
                    with open('debug.txt', "a+") as f:
                        f.write("[%s] (timer thread) stop recording\n" % time.strftime("%m/%d %H:%M:%S", time.localtime()))
                    msg_list.buffer_audio.append("/home/YiChun/aiottalk_v4_0313/aiottalk_v4/aiottalk_audio/" + filename)
                    label = label + 1
                elif self.EndCall_flag is not True:
                    direction = session.direction
                    filename = userName + "_" + str(label) + ".wav" #device10_1
                    dir_record = "/home/YiChun/aiottalk_v4_0313/aiottalk_v4"
                    path = os.path.join(dir_record, "aiottalk_audio")
                    audio_stream.start_recording(os.path.join(path, filename))
                    with open('debug.txt', "a+") as f:
                        #f.write("---[timer thread] start recording---\n")
                        f.write("[%s] (timer thread) start recording\n" % time.strftime("%m/%d %H:%M:%S", time.localtime()))
                else: #end call
                    with open('debug.txt', "a+") as f:
                        #f.write("---[timer thread] EndCall_flag is true---\n")
                        f.write("[%s] (timer thread) EndCall_flag is true\n" % time.strftime("%m/%d %H:%M:%S", time.localtime()))
                    break
            ## 單數編號
            if (label % 2) == 1:
                if self.EndCall_flag is not True:
                    rec = Recorder(channels=2)
                    dir_record = "/home/YiChun/aiottalk_v4_0313/aiottalk_v4/aiottalk_audio/"
                    filename = dir_record + userName + "_" + str(label) + ".wav" #device10_1
                    with rec.open(filename, 'wb') as recfile:
                        recfile.start_recording()
                        with open('debug.txt', "a+") as f:
                            f.write("[%s] (timer thread) start recording: pyaudio\n" % time.strftime("%m/%d %H:%M:%S", time.localtime()))
                        time.sleep(5.0)
                        recfile.stop_recording()
                        with open('debug.txt', "a+") as f:
                            f.write("[%s] (timer thread) stop recording: pyaudio\n" % time.strftime("%m/%d %H:%M:%S", time.localtime()))
                    msg_list.buffer_audio.append(filename)
                    label = label + 1
                else: #end call
                    with open('debug.txt', "a+") as f:
                        #f.write("---[timer thread] EndCall_flag is true---\n")
                        f.write("[%s] (timer thread) EndCall_flag is true\n" % time.strftime("%m/%d %H:%M:%S", time.localtime()))
                    break


    def _NH_SIPSessionDidStart(self, notification):
        notification_center = NotificationCenter()
        session = notification.sender
        #self.output.put('Session started with %d streams' % len(notification.data.streams))
        with open('debug.txt', "a+") as f:
            #f.write('Session started with %d streams\n' % len(notification.data.streams))
            f.write("[%s] Session started with %d streams\n" % (time.strftime("%m/%d %H:%M:%S", time.localtime()), len(notification.data.streams)))
        
        if session.remote_user_agent is not None:
            #self.output.put('Remote SIP User Agent is "%s"\n' % session.remote_user_agent)
            with open('debug.txt', "a+") as f:
                f.write('Remote SIP User Agent is "%s"\n' % session.remote_user_agent)

        audio_stream = notification.data.streams[0]
        #self.output.put('Audio stream established using "%s" codec at %sHz\n' % (audio_stream.codec, audio_stream.sample_rate))
        with open('debug.txt', "a+") as f:
            f.write('Audio stream established using "%s" codec at %sHz\n' % (audio_stream.codec, audio_stream.sample_rate))

        if audio_stream.ice_active:
            #self.output.put('Audio RTP endpoints %s:%d (ICE type %s) <-> %s:%d (ICE type %s)\n' % (audio_stream.local_rtp_address,audio_stream.local_rtp_port,audio_stream.local_rtp_candidate.type.lower(),audio_stream.remote_rtp_address,audio_stream.remote_rtp_port,audio_stream.remote_rtp_candidate.type.lower()))

            with open('debug.txt', "a+") as f:
		        f.write('Audio RTP endpoints %s:%d (ICE type %s) <-> %s:%d (ICE type %s)\n' % (audio_stream.local_rtp_address,audio_stream.local_rtp_port,audio_stream.local_rtp_candidate.type.lower(),audio_stream.remote_rtp_address,audio_stream.remote_rtp_port,audio_stream.remote_rtp_candidate.type.lower()))
        else:
            #self.output.put('Audio RTP endpoints %s:%d <-> %s:%d\n' % (audio_stream.local_rtp_address, audio_stream.local_rtp_port, audio_stream.remote_rtp_address, audio_stream.remote_rtp_port))
            with open('debug.txt', "a+") as f:
				f.write('Audio RTP endpoints %s:%d <-> %s:%d\n' % (audio_stream.local_rtp_address, audio_stream.local_rtp_port, audio_stream.remote_rtp_address, audio_stream.remote_rtp_port))
        if audio_stream.encryption.active:
            #self.output.put('RTP audio stream is encrypted using %s (%s)\n' % (audio_stream.encryption.type, audio_stream.encryption.cipher))
            pass

        try:
            video_stream = notification.data.streams[1]
        except IndexError:
            video_stream = None
        else:
            pass
            '''
            self.output.put('Video stream established using "%s" codec at %sHz\n' % (video_stream.codec, video_stream.sample_rate))
            if video_stream.ice_active:
                self.output.put('Video RTP endpoints %s:%d (ICE type %s) <-> %s:%d (ICE type %s)\n' % (video_stream.local_rtp_address,
                                                                                                       video_stream.local_rtp_port,
                                                                                                       video_stream.local_rtp_candidate.type.lower(),
                                                                                                       video_stream.remote_rtp_address,
                                                                                                       video_stream.remote_rtp_port,
                                                                                                       video_stream.remote_rtp_candidate.type.lower()))
            else:
                self.output.put('Video RTP endpoints %s:%d <-> %s:%d\n' % (video_stream.local_rtp_address, video_stream.local_rtp_port, video_stream.remote_rtp_address, video_stream.remote_rtp_port))
            if video_stream.encryption.active:
                self.output.put('RTP video stream is encrypted using %s (%s)\n' % (video_stream.encryption.type, video_stream.encryption.cipher))
            '''
        self.started_sessions.append(session)
        if self.active_session is not None:
            self.active_session.hold()
        self.active_session = session
        if len(self.started_sessions) > 1:
            message = 'Connected sessions:\n'
            for session in self.started_sessions:
                identity = str(session.remote_identity.uri)
                if session.remote_identity.display_name:
                    identity = '"%s" <%s>' % (session.remote_identity.display_name, identity)
                message += '  Session %s (%d/%d) - %s\n' % (identity, self.started_sessions.index(session)+1, len(self.started_sessions), 'active' if session is self.active_session else 'on hold')
            message += 'Press arrow keys to switch the active session\n'
            #self.output.put(message)
            with open('debug.txt', "a+") as f:
				f.write(message)

        if self.incoming_sessions:
            self.tone_ringtone.start()
            self._print_new_session()

        for stream in notification.data.streams:
            notification_center.add_observer(self, sender=stream)

        if self.options.auto_hangup_interval is not None:
            if self.options.auto_hangup_interval == 0:
                session.end()
            else:
                timer = reactor.callLater(self.options.auto_hangup_interval, session.end)
                self.hangup_timers[id(session)] = timer

        ## recorder的部分在session開始後就start
        ######################################
        settings = SIPSimpleSettings()

        if self.active_session is None or not self.active_session.streams:
            return
        session = self.active_session
        audio_stream = self.active_session.streams[0]

        direction = session.direction
        #remote = "%s@%s" % (session.remote_identity.uri.user, session.remote_identity.uri.host)
        #filename = "%s-%s-%s.wav" % (datetime.now().strftime("%Y%m%d-%H%M%S"), remote, direction)
        userName = session.remote_identity.uri.user #device10
        filename = userName + "_0.wav"  #device10_0
        
        '''
        # /home/tony/.sipclient/history
        with open('debug.txt', "a+") as f:
			f.write(settings.audio.directory.normalized)
        
        # aiottalk@xxx.xxx.77.72
        with open('debug.txt', "a+") as f:    
            f.write(session.account.id)

        # 20210104-163033-device10@xxx.xxx.77.73-incoming.wav
        with open('debug.txt', "a+") as f:
            f.write(filename)
        '''
        
        dir_record = "/home/YiChun/aiottalk_v4_0313/aiottalk_v4"
        #path = os.path.join(settings.audio.directory.normalized, session.account.id)
        #path = os.path.join(dir_record, session.account.id)
        path = os.path.join(dir_record, "aiottalk_audio")
        audio_stream.start_recording(os.path.join(path, filename))
        with open('debug.txt', "a+") as f:
			#f.write("---start recording---\n")
            f.write("[%s] (First) start recording\n" % time.strftime("%m/%d %H:%M:%S", time.localtime()))

        self.EndCall_flag = False
        ######################################

        ## recorder start後啟動timer
        ######################################
        rec_timer_thread=threading.Thread(target = self.rec_timer)
        rec_timer_thread.daemon = True
        rec_timer_thread.start()
        ######################################

    def _NH_SIPSessionWillEnd(self, notification):
        notification_center = NotificationCenter()

        self.EndCall_flag = True
        with open('debug.txt', "a+") as f:
            f.write("[%s] (SIPSessionWillEnd) self.EndCall_flag is True\n" % time.strftime("%m/%d %H:%M:%S", time.localtime()))

        session = notification.sender
        if id(session) in self.hangup_timers:
            timer = self.hangup_timers[id(session)]
            if timer.active():
                timer.cancel()
            del self.hangup_timers[id(session)]

        hangup_tone = WavePlayer(self.voice_audio_mixer, ResourcePath('sounds/hangup_tone.wav').normalized)
        notification_center.add_observer(self, sender=hangup_tone)
        self.voice_audio_bridge.add(hangup_tone)
        hangup_tone.start()

    def end_session_if_needed(self):
        if not self.session_spool_dir:
            return False

        stop_call_file = self.session_spool_dir + "/stop"

        if stop_call_file and os.path.exists(stop_call_file):
            if self.active_session is not None:
                #self.output.put('Ending audio session...\n')
                self.active_session.end()
            elif self.outgoing_session is not None:
                self.outgoing_session.end()
            elif self.incoming_sessions:
                session = self.incoming_sessions.pop(0)
                session.reject()
            return True

        return False

    def end_cancel_thread(self):
        if self.stop_call_thread is not None:
            self.stop_call_thread.stop()
            self.stop_call_thread = None

        if self.session_spool_dir:
            try:
                shutil.rmtree(self.session_spool_dir)
            except OSError:
                pass

        self.session_spool_dir = None
        
    def _NH_SIPSessionDidEnd(self, notification):
        self.end_cancel_thread()

        # self.EndCall_flag = True

        session = notification.sender
        if session is not self.active_session:
            identity = str(session.remote_identity.uri)
            if session.remote_identity.display_name:
                identity = '"%s" <%s>' % (session.remote_identity.display_name, identity)
        else:
            identity = '\b'
        if notification.data.end_reason == 'user request':
            #self.output.put('Session %s ended by %s party\n' % (identity, notification.data.originator))
            with open('debug.txt', "a+") as f:
				f.write('Session %s ended by %s party\n' % (identity, notification.data.originator))
        else:
            #self.output.put('Session %s ended due to error: %s\n' % (identity, notification.data.end_reason))
            with open('debug.txt', "a+") as f:
				f.write('Session %s ended due to error: %s\n' % (identity, notification.data.end_reason))
        duration = session.end_time - session.start_time
        seconds = duration.seconds if duration.microseconds < 500000 else duration.seconds+1
        minutes, seconds = seconds / 60, seconds % 60
        hours, minutes = minutes / 60, minutes % 60
        hours += duration.days*24
        if not minutes and not hours:
            duration_text = '%d seconds' % seconds
        elif not hours:
            duration_text = '%02d:%02d' % (minutes, seconds)
        else:
            duration_text = '%02d:%02d:%02d' % (hours, minutes, seconds)
        #self.output.put('Session duration was %s\n' % duration_text)
        with open('debug.txt', "a+") as f:
				f.write('Session duration was %s\n' % duration_text)
        
        self.started_sessions.remove(session)
        if session is self.active_session:
            if self.started_sessions:
                self.active_session = self.started_sessions[0]
                self.active_session.unhold()
                self.ignore_local_unhold = True
                identity = str(self.active_session.remote_identity.uri)
                if self.active_session.remote_identity.display_name:
                    identity = '"%s" <%s>' % (self.active_session.remote_identity.display_name, identity)
                #self.output.put('Active audio session: "%s" (%d/%d)\n' % (identity, self.started_sessions.index(self.active_session)+1, len(self.started_sessions)))
                with open('debug.txt', "a+") as f:
				    f.write('Active audio session: "%s" (%d/%d)\n' % (identity, self.started_sessions.index(self.active_session)+1, len(self.started_sessions)))
            else:
                self.active_session = None

        if session is self.outgoing_session:
            self.stop()
            self.end_cancel_thread()
            
        on_hold_streams = [stream for stream in chain(*(session.streams for session in self.started_sessions)) if stream.on_hold]
        if not on_hold_streams and self.hold_tone.is_active:
            self.hold_tone.stop()

        self.success = True


    def _NH_SIPSessionDidChangeHoldState(self, notification):
        session = notification.sender
        if notification.data.on_hold:
            if notification.data.originator == 'remote':
                if session is self.active_session:
                    #self.output.put('Remote party has put the audio session on hold\n')
                    with open('debug.txt', "a+") as f:
			            f.write('Remote party has put the audio session on hold\n')
                else:
                    identity = str(session.remote_identity.uri)
                    if session.remote_identity.display_name:
                        identity = '"%s" <%s>' % (session.remote_identity.display_name, identity)
                    #self.output.put('%s has put the audio session on hold\n' % identity)
                    with open('debug.txt', "a+") as f:
			            f.write('%s has put the audio session on hold\n' % identity)
            elif not self.ignore_local_hold:
                if session is self.active_session:
                    #self.output.put('Session is put on hold\n')
                    with open('debug.txt', "a+") as f:
			            f.write('Session is put on hold\n')
                else:
                    identity = str(session.remote_identity.uri)
                    if session.remote_identity.display_name:
                        identity = '"%s" <%s>' % (session.remote_identity.display_name, identity)
                    #self.output.put('Session %s is put on hold\n' % identity)
                    with open('debug.txt', "a+") as f:
			            f.write('Session %s is put on hold\n' % identity)
            else:
                self.ignore_local_hold = False
        else:
            if notification.data.originator == 'remote':
                if session is self.active_session:
                    #self.output.put('Remote party has taken the audio session out of hold\n')
                    with open('debug.txt', "a+") as f:
			            f.write('Remote party has taken the audio session out of hold\n')
                else:
                    identity = str(session.remote_identity.uri)
                    if session.remote_identity.display_name:
                        identity = '"%s" <%s>' % (session.remote_identity.display_name, identity)
                    #self.output.put('%s has taken the audio session out of hold\n' % identity)
                    with open('debug.txt', "a+") as f:
			            f.write('%s has taken the audio session out of hold\n' % identity) 
            elif not self.ignore_local_unhold:
                if session is self.active_session:
                    #self.output.put('Session is taken out of hold\n')
                    with open('debug.txt', "a+") as f:
			            f.write('Session is taken out of hold\n')
                else:
                    identity = str(session.remote_identity.uri)
                    if session.remote_identity.display_name:
                        identity = '"%s" <%s>' % (session.remote_identity.display_name, identity)
                    #self.output.put('Session %s is taken out of hold\n' % identity)
                    with open('debug.txt', "a+") as f:
			            f.write('Session %s is taken out of hold\n' % identity)
            else:
                self.ignore_local_unhold = False

    def _NH_SIPSessionNewProposal(self, notification):
        if notification.data.originator == 'remote':
            session = notification.sender
            accepted_types = ['video', 'audio'] if self.enable_video else ['audio']
            audio_streams = [stream for stream in notification.data.proposed_streams if stream.type in accepted_types]
            if audio_streams:
                session.accept_proposal(audio_streams)
            else:
                session.reject_proposal(488)

    def _NH_AudioStreamGotDTMF(self, notification):
        notification_center = NotificationCenter()
        digit = notification.data.digit
        filename = 'sounds/dtmf_%s_tone.wav' % {'*': 'star', '#': 'pound'}.get(digit, digit)
        wave_player = WavePlayer(self.voice_audio_mixer, ResourcePath(filename).normalized)
        notification_center.add_observer(self, sender=wave_player)
        self.voice_audio_bridge.add(wave_player)
        wave_player.start()

    def _NH_RTPStreamDidChangeHoldState(self, notification):
        if notification.data.on_hold:
            if not self.hold_tone.is_active:
                self.hold_tone.start()
        else:
            on_hold_streams = [stream for stream in chain(*(session.streams for session in self.started_sessions)) if stream is not notification.sender and stream.on_hold]
            if not on_hold_streams and self.hold_tone.is_active:
                self.hold_tone.stop()

    def _NH_RTPStreamDidChangeRTPParameters(self, notification):
        stream = notification.sender
        #self.output.put('Audio RTP parameters changed:\n')
        #self.output.put('Audio stream using "%s" codec at %sHz\n' % (stream.codec, stream.sample_rate))
        #self.output.put('Audio RTP endpoints %s:%d <-> %s:%d\n' % (stream.local_rtp_address, stream.local_rtp_port, stream.remote_rtp_address, stream.remote_rtp_port))
        with open('debug.txt', "a+") as f:
			f.write('Audio RTP parameters changed:\n')
            #f.write('Audio stream using "%s" codec at %sHz\n' % (stream.codec, stream.sample_rate))
            #f.write('Audio RTP endpoints %s:%d <-> %s:%d\n' % (stream.local_rtp_address, stream.local_rtp_port, stream.remote_rtp_address, stream.remote_rtp_port))
        if stream.encryption.active:
            pass
            #self.output.put('RTP audio stream is encrypted using %s (%s)\n' % (stream.encryption.type, stream.encryption.cipher))

    def _NH_AudioStreamDidStartRecordingAudio(self, notification):
        #self.output.put('Recording audio to %s\n' % notification.data.filename)
        with open('debug.txt', "a+") as f:
			f.write('Recording audio to %s\n' % notification.data.filename)

    def _NH_AudioStreamDidStopRecordingAudio(self, notification):
        #self.output.put('Stopped recording audio to %s\n' % notification.data.filename)
        with open('debug.txt', "a+") as f:
			f.write('Stopped recording audio to %s\n' % notification.data.filename)

    def _NH_WavePlayerDidEnd(self, notification):
        notification_center = NotificationCenter()
        notification_center.remove_observer(self, sender=notification.sender)

    def _NH_WavePlayerDidFail(self, notification):
        notification_center = NotificationCenter()
        notification_center.remove_observer(self, sender=notification.sender)
        #self.output.put('Failed to play %s: %s' % (notification.sender.filename, notification.data.error))
        with open('debug.txt', "a+") as f:
			f.write('Failed to play %s: %s' % (notification.sender.filename, notification.data.error))

    def _NH_DefaultAudioDeviceDidChange(self, notification):
        SIPApplication._NH_DefaultAudioDeviceDidChange(self, notification)
        '''
        if notification.data.changed_input and self.voice_audio_mixer.input_device=='system_default':
            self.output.put('Switched default input device to: %s\n' % self.voice_audio_mixer.real_input_device)
        if notification.data.changed_output and self.voice_audio_mixer.output_device=='system_default':
            self.output.put('Switched default output device to: %s\n' % self.voice_audio_mixer.real_output_device)
        if notification.data.changed_output and self.alert_audio_mixer.output_device=='system_default':
            self.output.put('Switched alert device to: %s\n' % self.alert_audio_mixer.real_output_device)
        '''

    def _NH_AudioDevicesDidChange(self, notification):
        old_devices = set(notification.data.old_devices)
        new_devices = set(notification.data.new_devices)
        added_devices = new_devices - old_devices
        removed_devices = old_devices - new_devices
        changed_input_device = self.voice_audio_mixer.real_input_device in removed_devices
        changed_output_device = self.voice_audio_mixer.real_output_device in removed_devices
        changed_alert_device = self.alert_audio_mixer.real_output_device in removed_devices

        SIPApplication._NH_AudioDevicesDidChange(self, notification)

        '''
        if added_devices:
            self.output.put('Added audio device(s): %s\n' % ', '.join(sorted(added_devices)))
        if removed_devices:
            self.output.put('Removed audio device(s): %s\n' % ', '.join(sorted(removed_devices)))
        if changed_input_device:
            self.output.put('Audio input device has been switched to: %s\n' % self.voice_audio_mixer.real_input_device)
        if changed_output_device:
            self.output.put('Audio output device has been switched to: %s\n' % self.voice_audio_mixer.real_output_device)
        if changed_alert_device:
            self.output.put('Audio alert device has been switched to: %s\n' % self.alert_audio_mixer.real_output_device)

        self.output.put('Available audio input devices: %s\n' % ', '.join(['None', 'system_default'] + sorted(self.engine.input_devices)))
        self.output.put('Available audio output devices: %s\n' % ', '.join(['None', 'system_default'] + sorted(self.engine.output_devices)))
        '''

    def _NH_RTPStreamICENegotiationDidSucceed(self, notification):
        #self.output.put("ICE negotiation succeeded in %s\n" % notification.data.duration)
        with open('debug.txt', "a+") as f:
			f.write("ICE negotiation succeeded in %s\n" % notification.data.duration)

    def _NH_RTPStreamICENegotiationDidFail(self, notification):
        #self.output.put("ICE negotiation failed: %s\n" % notification.data.reason)
        with open('debug.txt', "a+") as f:
			f.write("ICE negotiation failed: %s\n" % notification.data.reason)

    def _print_new_session(self):
        session = self.incoming_sessions[0]
        identity = str(session.remote_identity.uri)
        if session.remote_identity.display_name:
            identity = '"%s" <%s>' % (session.remote_identity.display_name, identity)

        video_streams = [stream for stream in session.proposed_streams if stream.type in ['video']]
        media_type = 'video' if video_streams else 'audio'
        #self.output.put("Incoming %s session from '%s', do you want to accept? (y/n)\n" % (media_type, identity))
        with open('debug.txt', "a+") as f:
			f.write("Incoming %s session from '%s', do you want to accept? (y/n)\n" % (media_type, identity))

def parse_handle_call_option(option, opt_str, value, parser, name):
    try:
        value = parser.rargs[0]
    except IndexError:
        value = 0
    else:
        if value == '' or value[0] == '-':
            value = 0
        else:
            try:
                value = int(value)
            except ValueError:
                value = 0
            else:
                del parser.rargs[0]
    setattr(parser.values, name, value)

'''
if __name__ == '__main__':
    description = 'This script can sit idle waiting for an incoming audio session, or initiate an outgoing audio session to a SIP address. The program will close the session and quit when Ctrl+D is pressed.'
    usage = '%prog [options] [user@domain]'
    parser = OptionParser(usage=usage, description=description)
    parser.print_usage = parser.print_help
    parser.add_option('-a', '--account', type='string', dest='account', help='The account name to use for any outgoing traffic. If not supplied, the default account will be used.', metavar='NAME')
    parser.add_option('-c', '--config-directory', type='string', dest='config_directory', help='The configuration directory to use. This overrides the default location.')
    parser.add_option('-s', '--trace-sip', action='store_true', dest='trace_sip', default=False, help='Dump the raw contents of incoming and outgoing SIP messages.')
    parser.add_option('-j', '--trace-pjsip', action='store_true', dest='trace_pjsip', default=False, help='Print PJSIP logging output.')
    parser.add_option('-n', '--trace-notifications', action='store_true', dest='trace_notifications', default=False, help='Print all notifications (disabled by default).')
    parser.add_option('-S', '--disable-sound', action='store_true', dest='disable_sound', default=False, help='Disables initializing the sound card.')
    parser.set_default('auto_answer_interval', None)
    parser.add_option('--auto-answer', action='callback', callback=parse_handle_call_option, callback_args=('auto_answer_interval',), help='Interval after which to answer an incoming session (disabled by default). If the option is specified but the interval is not, it defaults to 0 (accept the session as soon as it starts ringing).', metavar='[INTERVAL]')
    parser.add_option('-u', '--auto-answer-uris', type='string', dest='auto_answer_uris', default="", help='Optional list of SIP URIs for which auto-answer is allowed')
    parser.add_option('-i', '--external-id', type='string', dest='external_id', help='id used for call control from external application')
    parser.add_option('-v', '--spool-dir', type='string', dest='spool_dir', default=None, help='Spool dir for call control from external applications, default is /var/spool/sipclients/sessions')
    parser.add_option('-t', '--enable-default-devices',  action='store_true', dest='enable_default_devices', help='Use default audio devices')
    parser.add_option('-V', '--enable-video',  action='store_true', dest='enable_video', default=False, help='Enable video if camera is available')
    parser.set_default('auto_hangup_interval', None)
    parser.add_option('--auto-hangup', action='callback', callback=parse_handle_call_option, callback_args=('auto_hangup_interval',), help='Interval after which to hang up an established session (disabled by default). If the option is specified but the interval is not, it defaults to 0 (hangup the session as soon as it connects).', metavar='[INTERVAL]')
    parser.add_option('-b', '--batch', action='store_true', dest='batch_mode', default=False, help='Run the program in batch mode: reading input from the console is disabled and the option --auto-answer is implied. This is particularly useful when running this script in a non-interactive environment.')
    parser.add_option('-d', '--daemonize', action='store_true', dest='daemonize', default=False, help='Enable running this program as a deamon.')
    options, args = parser.parse_args()

    target = args[0] if args and not options.auto_answer_uris else None

    application = SIPAudioApplication()
    application.start(target, options)
    
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    application.output.join()
    sleep(0.1)

    sys.exit(0 if application.success else 1)
'''
