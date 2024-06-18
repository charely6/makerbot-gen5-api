#!/usr/bin/python
#
# Copyright 2015 Jeff Rebeiro (jeff@rebeiro.net), Oli Schacher (oli@wgwh.ch)
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 3.0 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library.
#

"""Makerbot Gen 5 API."""

import sys
import json
import socket
import time
import urllib
import urllib2
import ctypes
import struct
import png
import os
import thread


try:
    from cStringIO import StringIO
except:
    from StringIO import StringIO


class Error(Exception):

    """Error."""


class AuthenticationError(Error):

    """Authentication timed out."""


class AuthenticationTimeout(Error):

    """Authentication timed out."""


class InvalidContextError(Error):

    """Invalid context."""


class MakerBotError(Error):

    """MakerBot Error."""


class NotAuthenticated(Error):

    """Access to privileged method call denied."""


class UnexpectedJSONResponse(Error):
    # Here's what the JSON should look like (When a process is not running):
    #
    # https://jsonblob.com/55bfee62e4b0f6d7e5be5aca

    """Unexpected JSON Response."""


class Toolhead(object):

    def __init__(self):
        self.tool_id = None
        self.filament_presence = None
        self.preheating = None
        self.index = None
        self.tool_present = None
        self.current_temperature = None
        self.target_temperature = None

    def __str__(self):
        return "<Toolhead %s id=%s filament_present=%s preheating=%s current_temp=%s target_temp=%s" % (self.index, self.tool_id, self.filament_presence, self.preheating, self.current_temperature, self.target_temperature)

    def __repr__(self):
        return str(self)


class Config(object):

    """ A simple config file that contains info about bots that have been connected to.

    """

    def __init__(self):
        self.configExists = None
        self.fname = 'config.json'
        self.emptyConfig = {'bots': {}}
        self.data = None

    def load(self):
        """Loads a makerbotapi json config. If no config.json exists, this will create one.

        """
        if os.path.isfile(self.fname):
            # File exists, load it.
            print 'found config'
            with open(self.fname) as json_data_file:
                try:
                    self.data = json.load(json_data_file)
                    print 'Loaded config'
                except ValueError, e:
                    print 'Not a valid JSON config file!'
        else:
            print 'No config.json found. Creating empty config'
            with open(self.fname, 'w') as outfile:
                try:
                    json.dump(self.emptyConfig, outfile)
                    self.data = self.emptyConfig
                    print 'Created config'
                except ValueError, e:
                    print 'Could not create config'

    def save(self):
        """Saves a makerbotapi json config. If no config.json exists, it will create one.
        This method completely overwrites the old config.json, so make sure to run config.load()
        before this if you want your old data saved.

        """
        with open(self.fname, 'w') as outfile:
            try:
                json.dump(self.data, outfile)
                print 'Saved config'
            except ValueError, e:
                print 'Could not save config'

    def getBotInfo(self, botSerial):
        """Allows you to see some basic info about the bot

        Args:
            botSerial: Serial number of the bot you want to get info about

        Returns:
            A dict if the serial number was found, otherwise will return None.
        """

        if botSerial in self.data['bots']:
            return self.data['bots'][botSerial]
        else:
            return None

    def addBot(self, botData):
        """Adds a bot to the config file. botData is a tuple in the form of ('<ipaddress>','<machine name>','<serial>')
        If the bot's serial number is already in the config, it will update the name/ip if they have changed.
        We also add two more keys -- 'save auth' and 'auth code'. These are set to false and None, respectively.

        """
        ip = botData[0]
        name = botData[1]
        serial = botData[2]
        infodict = {"machine name": name, "ip": ip,
                    "save auth": False, "auth code": None}
        # We use the serial number as the dict key, and store the bot name and
        # ip under that.

        if serial not in self.data['bots']:
            self.data['bots'][serial] = infodict
        else:
            self.data['bots'][serial]['machine name'] = name
            self.data['bots'][serial]['ip'] = ip

    def setAuthCodeSavePermission(self, botSerial, bool):
        """ Sets whether or not we are allowed to save an auth code.

        Args:
            botSerial: Serial number of the bot you want to save a code to
            bool: Boolean stating whether or not we are allowed to save an auth code.

        Returns:
            True if it sucessfully changes the save state. False if it couldn't find the serial
        """

        if botSerial in self.data['bots']:
            self.data['bots'][botSerial]['save auth'] = bool
            return True
        else:
            return False

    def saveAuthCode(self, botSerial, authCode):
        """ Saves an authentication code to the config.

        Args:
            botSerial: Serial number of the bot you want to save a code to
            authCode: Authentication code to be saved

        Returns:
            True if the code was succesfully saved. False if we don't have permission to save the code, or if the serial
            wasn't found.
        """

        if botSerial in self.data['bots']:
            if self.data['bots'][botSerial]['save auth'] == True:
                self.data['bots'][botSerial]['auth code'] = authCode
                return True
            else:
                return False
        else:
            return False


def closeSockets(sockets):
    """Closes the sockets that communicate to the Gen5

        Args: sockets: A list of broadcast and answers sockets: [broadcastsocket, answersocket]

    """

    sockets[0].shutdown(socket.SHUT_RDWR)
    sockets[1].shutdown(socket.SHUT_RDWR)

    sockets[0].close()
    sockets[1].close()


def createSockets():
    """Create the sockets that communicate to the Gen5.

        Returns: A list of sockets -- [broadcastsocket, answersocket]
    """
    bcaddr = '255.255.255.255'
    target_port = 12307
    listen_port = 12308
    source_port = 12309

    broadcastsocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    broadcastsocket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    broadcastsocket.bind(('', source_port))

    answersocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    discover_request = '{"command": "broadcast"}'
    answersocket.bind(('', listen_port))
    answersocket.setblocking(0)

    sockets = [broadcastsocket, answersocket]
    return sockets


def discover(sockets, knownBotIps=None, sleep=1):
    """Discover Makerbot Gen5 in the network

        Args:
            sockets: A list of a broadcast socket and an answer socket, in that order.
            knownBotIps: A list of known bot ips, so we don't duplicate ips in our result.
            sleep: How long this function should sleep after checking for a response.
                Users can override this, but the default value is 1 second.

        Returns:
          a list of tuples in the form ('<ipaddress>','<machine name>','<serial>')
    """
    if knownBotIps == None:
        knownBotIps = []

    bcaddr = '255.255.255.255'
    target_port = 12307

    broadcastsocket = sockets[0]
    answersocket = sockets[1]

    broadcast_dict = {"command": "broadcast"}
    discover_request = json.dumps(broadcast_dict)

    answers = []

    broadcastsocket.sendto(discover_request, (bcaddr, target_port))
    time.sleep(sleep)
    try:
        data, fromaddr = answersocket.recvfrom(1024)
        ip = fromaddr[0]
        if ip not in knownBotIps:
            infodic = json.loads(data)
            machine_name = infodic['machine_name']
            serial = infodic['iserial']
            answers.append((fromaddr[0], machine_name, serial),)
    except socket.error:
        '''no data yet'''
    return answers


class BotState(object):

    """Current Bot status data object"""
    STEP_RUNNING = 'running'
    # TODO: find out other step states

    STATE_IDLE = 'idle'
    # TODO: find out other states

    def __init__(self):
        self.step = None
        self.toolheads = []
        self.preheat_percent = None
        self.current_process = None

    def get_tool_head_count(self):
        return len(self.toolheads)

    def __str__(self):
        return '<Bostate toolheads=%s>' % (self.toolheads)


class CurrentBotProcess(object):

    def __init__(self):
        self.username = None
        self.name = None
        self.cancellable = None
        self.temperature_settings = []
        self.tool_index = None
        self.step = None
        self.error = None
        self.cancelled = None
        self.id = None
        self.methods = []
        self.progress = None


class Makerbot(object):

    """MakerBot."""

    def __init__(self, ip, auth_code=None, auto_connect=True):
        self.auth_code = auth_code
        self.auth_timeout = 120
        self.client_id = 'MakerWare'
        self.client_secret = 'python-makerbotapi'
        self.fcgi_retry_interval = 5
        self.host = ip
        self.jsonrpc_port = 9999

        self.builder = None
        self.commit = None
        self.firmware_version = None
        self.iserial = None
        self.machine_name = None
        self.machine_type = None
        self.vid = None
        self.pid = None
        self.bot_type = None

        self.default_params = {'username': 'conveyor',
                               'host_version': '1.0'}
        self.request_id = -1

        self.debug_jsonrpc = False
        self.debug_fcgi = False

        self.rpc_unsolicited_messages = []
        self.rpc_id_responses = {}
        # TODO: implement consumers to remove obsolete solicited/unsolicited
        # messages

        self.rpc_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if auto_connect:
            self._connect_json_rpc()
            thread.start_new_thread(self._rpc_reader_thread, ())
            self.do_handshake()

    def _debug_print(self, protocol, direction, content):
        # TODO(gryphius): Convert this to use logging.debug once we implement
        # logging module support
        sys.stderr.write("(%s) %s: %s\n" % (protocol, direction, content))

    def _connect_json_rpc(self):
        """Create a socket connection to the MakerBot JSON RPC interface."""
        self.rpc_socket.connect((self.host, self.jsonrpc_port),)
        self.jsonrpc_connected = True

    def _disconnect_json_rpc(self):
        """Disconnect from the MakerBot JSON RPC interface."""
        pass

    def _generate_json_rpc(self, method, params, id):
        """Generate a JSON RPC payload.

        Args:
          method: RPC Method to call
          params: dict containing key/value pairs for the RPC method
          id: ID of this request. Must be sequential in order to retrieve the
              correct output from the bot.

        Returns:
          A JSON RPC formatted string.
        """
        if params == "":
            jsonrpc = {'id' : id, 'jsonrpc': '2.0', 'method': method}
        else:
            jsonrpc = {'id': id,
                   'jsonrpc': '2.0',
                   'method': method,
                   'params': params}
        # TODO(n-i-x): Do some error checking here
        return json.dumps(jsonrpc)

    def _get_request_id(self):
        """Increment the request id counter."""
        self.request_id += 1
        return self.request_id

    def _send_fcgi(self, path, query_args):
        """Send an FCGI request to the MakerBot FCGI interface."""
        encoded_args = urllib.urlencode(query_args)

        url = 'http://%s/%s?%s' % (self.host, path, encoded_args)

        if self.debug_fcgi:
            self._debug_print('FCGI', 'REQUEST', url)

        response = urllib2.urlopen(url)
        if self.debug_fcgi:
            content = response.read()
            self._debug_print('FCGI', 'RESPONSE', content)
            result = json.loads(content)
        else:
            result = json.load(response)

        return result

    def _send_rpc(self, jsonrpc):
        """Send an RPC to the MakerBot JSON RPC interface.

        Args:
          jsonrpc: A JSON RPC request generated by _generate_json_rpc()
        """
        if self.debug_jsonrpc:
            self._debug_print('JSONRPC', 'REQUEST', jsonrpc)

        self.rpc_socket.sendall(jsonrpc)

    def _wait_for_rpc_response(self, requestid, timeout=3):
        too_late = time.time() + timeout
        while time.time() < too_late:
            if requestid in self.rpc_id_responses:
                return self.rpc_id_responses.pop(requestid)
        return None

    def _rpc_reader_thread(self):
        buffer = ''
        while True:
            response = self.rpc_socket.recv(4096)
            buffer += response
            message, rest = self._rpc_get_next_message(buffer)
            while message != None:
                self._handle_response(message)
                buffer = rest
                message, rest = self._rpc_get_next_message(buffer)
            buffer = rest

    def _rpc_get_next_message(self, buffer):
        """get the first rpc message from the stream.
        Returns a tuple (first message, rest of the buffer)"""
        if len(buffer) == 0:
            return None, buffer
        parenindex = 0
        assert buffer.startswith('{'), 'invalid buffer state %s' % buffer
        pos = 0
        for char in buffer:
            pos += 1
            if char == '{':
                parenindex += 1
            if char == '}':
                parenindex -= 1
                if parenindex == 0:
                    message = buffer[0:pos]
                    return message, buffer[pos:]
        return None, buffer

    def _handle_response(self, response):
        if self.debug_jsonrpc:
            self._debug_print('JSONRPC', 'RESPONSE', response)
        dic = json.loads(response)
        if 'id' in dic:
            response_id = dic['id']
            self.rpc_id_responses[response_id] = dic
        else:
            self.rpc_unsolicited_messages.append(dic)

    def authenticate_fcgi(self):
        """Authenticate to the MakerBot FCGI interface."""
        query_args = {'response_type': 'code',
                      'client_id': self.client_id,
                      'client_secret': self.client_secret}
        response = self._send_fcgi('auth', query_args)

        answer_code = response['answer_code']

        query_args = {'response_type': 'answer',
                      'client_id': self.client_id,
                      'client_secret': self.client_secret,
                      'answer_code': answer_code}
        start_time = time.time()
        while True:
            response = self._send_fcgi('auth', query_args)

            if response.get('answer') == 'accepted':
                self.auth_code = response.get('code')
                break

            if response.get('answer') == 'rejected':
                error_message = "Pairing mode is already active for this printer. " \
                                "Press a button on printer to disable pairing mode."
                raise AuthenticationError(error_message)

            if time.time() - start_time >= self.auth_timeout:
                raise AuthenticationTimeout

            time.sleep(self.fcgi_retry_interval)

    def authenticate_json_rpc(self):
        """Authenticate to the MakerBot JSON RPC interface."""
        response = self.rpc_request_response(
            'authenticate', {'access_token': self.get_access_token(context='jsonrpc')})
        self.jsonrpc_authenticated = True

    def do_handshake(self):
        """Perform handshake with MakerBot over JSON RPC."""
        response = self.rpc_request_response('handshake', self.default_params)
        if 'result' in response and len(response.get('result')):
            self.builder = response['result'].get('builder')
            self.commit = response['result'].get('commit')
            self.firmware_version = response['result'].get('firmware_version')
            self.iserial = response['result'].get('iserial')
            self.machine_name = response['result'].get('machine_name')
            self.machine_type = response['result'].get('machine_type')
            self.vid = response['result'].get('vid')
            self.pid = response['result'].get('pid')
            self.bot_type = response['result'].get('bot_type')

    def get_access_token(self, context):
        """Get an OAuth access token from the MakerBot FCGI interface.

        Args:
          context: Context of the token. Valid contexts are 'camera', 'jsonrpc', 'put'.

        Returns:
          A string containing the access token for the specified context.
        """
        valid_contexts = ['jsonrpc', 'put', 'camera']

        if context not in valid_contexts:
            raise InvalidContextError

        query_args = {'response_type': 'token',
                      'client_id': self.client_id,
                      'client_secret': self.client_secret,
                      'auth_code': self.auth_code,
                      'context': context}
        response = self._send_fcgi('auth', query_args)

        if response.get('status') == 'success':
            return response.get('access_token')
        else:
            raise AuthenticationError(response.get('message'))

    def _get_raw_camera_image_data(self):
        """Request the current camera data

        Returns:
          A tuple total_blob_size, image_width, image_height, pixel_format, latest_cached_image
        """
        access_token = self.get_access_token('camera')
        url = 'http://%s/camera?token=%s' % (self.host, access_token)
        data = urllib2.urlopen(url).read()
        return struct.unpack('!IIII{0}s'.format(len(data) - ctypes.sizeof(ctypes.c_uint32 * 4)), data)

    def rpc_request_response(self, method, params):
        request_id = self._get_request_id()
        jsonrpc = self._generate_json_rpc(
            method, params, request_id)
        self._send_rpc(jsonrpc)
        response = self._wait_for_rpc_response(request_id)
        if 'error' in response:
            err = response['error']
            code = err['code']
            message = err['message']
            # 'method not found' means the current connection is not
            # authenticated
            if code == -32601:
                raise NotAuthenticated(message)
            else:
                raise MakerBotError(
                    'RPC Error code=%s message=%s' % (code, message))
        return response

    def get_system_information(self):
        """Get system information from MakerBot over JSON RPC.

        Returns:
          A BotState object
        """
        response = self.rpc_request_response(
            'get_system_information', '')
        bot_state = BotState()

        # Uncommment this line to see the raw JSON the bot is sending
        # print json.dumps(response)

        if not response['result']:
            raise UnexpectedJSONResponse(response)
        if 'machine_name' not in response['result']:
            raise UnexpectedJSONResponse(response)
        json_machine_status = response['result']['machine_name']

        for attr in ['step', 'extruder_temp', 'state', 'preheat_percent']:
            if attr in json_machine_status:
                setattr(bot_state, attr, json_machine_status[attr])

        # for now we just support one toolhead (are there any gen5 with
        # multiple heads anyway?)
        toolhead = Toolhead()
        json_toolhead_status = response['result']['toolheads']['extruder'][0]
        #json_toolhead_status = json_machine_status['toolhead_0_status']
        for attr in ['tool_id',
                     'filament_presence',
                     'preheating',
                     'index',
                     'tool_present',
                     'current_temperature',
                     'target_temperature']:
            if attr in json_toolhead_status:
                setattr(toolhead, attr, json_toolhead_status[attr])

        bot_state.toolheads.append(toolhead)

        # Check to see if there's a process happening.
        if response['result']['current_process']:
            # If the machine is doing something (loading filament, etc.), this
            # will not be None.
            current_bot_process = CurrentBotProcess()
            json_current_process = response['result']['current_process']
            for attr in ['username',
                         'name',
                         'cancellable',
                         'temperature_settings',
                         'tool_index',
                         'step',
                         'complete',
                         'error',
                         'cancelled',
                         'reason',
                         'id',
                         'methods',
                         'progress']:
                if attr in json_current_process:
                    setattr(
                        current_bot_process, attr, json_current_process[attr])
        else:
            current_bot_process = None

        bot_state.current_process = current_bot_process

        return bot_state

    def disable_check_build_plate(self):
        """Disable build_plate_Check on MakerBot over JSON RPC.

        Returns:
          A BotState object
        """
        response = self.rpc_request_response(
            'disable_check_build_plate', '')
        return response

    def _rgb_clamp(self, x):
        """Clamp an RGB value between 0 and 255.

        Args:
            x: Value to clamp

        Returns:
          The clamped value
        """
        if x < 0:
            return 0
        elif x > 255:
            return 255
        else:
            return x

    def _rgb_rows_to_png(self, rgb_rows, width, height, output_file):
        """Save RGB rows as returned by self._yuv_to_rgb_rows() as PNG.

        Args:
            rgb_rows: RGB rows as returned by self._yuv_to_rgb_rows()
            output_file: PNG file to save
        """
        f = open(output_file, 'wb')
        png_file = png.Writer(width, height)
        png_file.write(f, rgb_rows)
        f.close()

    def save_camera_png(self, output_file):
        """Save an image from the MakerBot camera in PNG format.

        Args:
            output_file: PNG file to save.
        """
        _, width, height, _, yuv_image = self._get_raw_camera_image_data()
        rgb_rows = self._yuv_to_rgb_rows(StringIO(yuv_image), width, height)
        self._rgb_rows_to_png(rgb_rows, width, height, output_file)

    def get_camera_png(self):
        """Get image from the MakerBot camera in PNG format.
        """
        _, width, height, _, yuv_image = self._get_raw_camera_image_data()
        rgb_rows = self._yuv_to_rgb_rows(StringIO(yuv_image), width, height)
        png_file = png.Writer(width, height)
        output = StringIO()
        png_file.write(output, rgb_rows)
        contents = output.getvalue()
        output.close()
        return contents

    def _yuv_to_rgb_rows(self, yuv_image, width, height):
        """Convert YUYV422 to RGB pixels.

        Args:
            yuv_image: A file-like object containing YUYV422 image data
            width: Width in pixels
            height: Height in pixels

        Returns:
          A list of lists containing RGB pixel values.
        """
        rgb_rows = []
        for row in range(0, height):
            rgb_row = []
            for column in range(0, width / 2):
                # http://en.wikipedia.org/wiki/YUV#Y.27UV422_to_RGB888_conversion
                # Modified for MakerBot YUYV format
                y1 = ord(yuv_image.read(1))
                u = ord(yuv_image.read(1))
                y2 = ord(yuv_image.read(1))
                v = ord(yuv_image.read(1))

                # http://www.lems.brown.edu/vision/vxl_doc/html/core/vidl_vil1/html/vidl__vil1__yuv__2__rgb_8h.html
                R = 1.164 * (y1 - 16) + 1.596 * (v - 128)
                G = 1.164 * (y1 - 16) - 0.813 * (v - 128) - 0.391 * (u - 128)
                B = 1.164 * (y1 - 16) + 2.018 * (u - 128)
                rgb_row.append(self._rgb_clamp(int(R)))
                rgb_row.append(self._rgb_clamp(int(G)))
                rgb_row.append(self._rgb_clamp(int(B)))

                R = 1.164 * (y2 - 16) + 1.596 * (v - 128)
                G = 1.164 * (y2 - 16) - 0.813 * (v - 128) - 0.391 * (u - 128)
                B = 1.164 * (y2 - 16) + 2.018 * (u - 128)
                rgb_row.append(self._rgb_clamp(int(R)))
                rgb_row.append(self._rgb_clamp(int(G)))
                rgb_row.append(self._rgb_clamp(int(B)))
            rgb_rows.append(rgb_row)
        return rgb_rows
