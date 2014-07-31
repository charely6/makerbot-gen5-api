#!/usr/bin/python
#
# Copyright Jeff Rebeiro (jeff@rebeiro.net)

"""Makerbot Gen 5 API."""

import json
import socket
import urllib2


class Error(Exception):

    """Error."""


class AuthenticationTimeout(Error):

    """Authentication timed out."""


class MakerBotError(Error):
    """MakerBot Error."""


class NotAuthenticated(Error):

    """Access to privileged method call denied."""


class UnexpectedJSONResponse(Error):
    """Unexpected JSON Response."""


class Toolhead(object):

    def __init__(self):
        self.filament_fan_running = None
        self.filament_presence = None
        self.extrusion_percent = None
        self.filament_jam = None

        self.current_temperature = None
        self.preheating = None
        self.target_temperature = None


class BotState(object):

    """Current Bot status data object"""
    STEP_RUNNING = 'running'
    # TODO: find out other step states

    STATE_IDLE = 'idle'
    # TODO: find out other states

    def __init__(self):
        self.step = None
        # TODO: find out how this differs from current_temperatore
        self.extruder_temp = None
        self.toolheads = []
        self.preheat_percent = None
        self.state = None

    def GetToolHeadCount(self):
        return len(self.toolheads)


class Makerbot(object):

    """MakerBot."""

    def __init__(self, ip, auth_code=None, auto_connect=True):
        self.auth_code = auth_code
        self.client_id = 'MakerWare'
        self.client_secret = 'python-makerbotapi'
        self.host = ip
        self.jsonrpc_port = 9999

        self.builder = None
        self.commit = None
        self.firmware_version = None
        self.iserial = None
        self.machine_name = None
        self.machine_type = None
        self.vid = None

        self.default_params = {'username': 'conveyor',
                               'host_version': '1.0'}
        self.request_id = -1

        self.rpc_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        if auto_connect:
            self.__ConnectJSONRPC()

    def __ConnectJSONRPC(self):
        """Create a socket connection to the MakerBot JSON RPC interface."""
        self.rpc_socket.connect((self.host, self.jsonrpc_port),)
        self.jsonrpc_connected = True

    def __DisconnectJSONRPC(self):
        """Disconnect from the MakerBot JSON RPC interface."""
        pass

    def __GenerateJSONRPC(self, method, params, id):
        """Generate a JSON RPC payload.

        Args:
          method: RPC Method to call
          params: dict containing key/value pairs for the RPC method
          id: ID of this request. Must be sequential in order to retrieve the
              correct output from the bot.

        Returns:
          A JSON RPC formatted string.
        """
        jsonrpc = {'id': id,
                   'jsonrpc': '2.0',
                   'method': method,
                   'params': params}
        # TODO(n-i-x): Do some error checking here
        return json.dumps(jsonrpc)

    def __GetRequestID(self):
        """Increment the request id counter."""
            self.request_id += 1
            return self.request_id

    def __RPCSend(self, jsonrpc):
        """Send an RPC to the MakerBot JSON RPC interface.

        Args:
          jsonrpc: A JSON RPC request generated by __GenerateJSONRPC()

        Returns:
          A JSON decoded response
        """
        self.rpc_socket.sendall(jsonrpc)
        response = self.rpc_socket.recv(1024)
        return json.loads(response)

    def AuthenticateJSONRPC(self):
        """Authenticate to the MakerBot JSON RPC interface."""
        pass

    def DoHandshake(self):
        """Perform handshake with MakerBot over JSON RPC."""
        method = 'handshake'
        request_id = self.__GetRequestID()
        jsonrpc = self.__GenerateJSONRPC(
            method, self.default_params, request_id)
        response = self.__RPCSend(jsonrpc)
        if 'result' in response and len(response.get('result')):
            self.builder = response['result'].get('builder')
            self.commit = response['result'].get('commit')
            self.firmware_version = response['result'].get('firmware_version')
            self.iserial = response['result'].get('iserial')
            self.machine_name = response['result'].get('machine_name')
            self.machine_type = response['result'].get('machine_type')
            self.vid = response['result'].get('vid')

    def GetSystemInformation(self):
        """Get system information from MakerBot over JSON RPC.

        Returns:
          A BotState object
        """
        request_id = self.__GetRequestID()
        method = 'get_system_information'
        jsonrpc = self.__GenerateJSONRPC(
            method, self.default_params, request_id)
        response = self.__RPCSend(jsonrpc)
        if 'error' in response:
            err = response['error']
            code = err['code']
            message = err['message']
            # 'method not found' means the current connection is not
            # authenticated
            if code == -32601:
                raise NotAuthenticated(message)
            else:
                raise MakerBotError('RPC Error code=%s message=%s' % (code, message))

        botstate = BotState()
        if 'result' not in response:
            raise UnexpectedJSONResponse(response)
        if 'machine' not in response['result']:
            raise UnexpectedJSONResponse(response)
        json_machine_status = response['result']['machine']

        for attr in ['step', 'extruder_temp', 'state', 'preheat_percent']:
            if attr in json_machine_status:
                setattr(botstate, attr, json_machine_status[attr])

        # for now we just support one toolhead (are there any gen5 with
        # multiple heads anyway?)
        toolhead = Toolhead()
        json_toolhead_status = json_machine_status['toolhead_0_status']
        for attr in ['filament_fan_running', 'filament_presence', 'extrusion_percent', 'filament_jam']:
            if attr in json_toolhead_status:
                setattr(toolhead, attr, json_toolhead_status[attr])

        json_heating_status = json_machine_status['toolhead_0_heating_status']
        for attr in ['current_temperature', 'preheating', 'target_temperature']:
            if attr in json_heating_status:
                setattr(toolhead, attr, json_heating_status[attr])
        botstate.toolheads.append(toolhead)

        return botstate
