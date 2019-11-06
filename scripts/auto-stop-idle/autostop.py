#     Copyright 2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#     Licensed under the Apache License, Version 2.0 (the "License").
#     You may not use this file except in compliance with the License.
#     A copy of the License is located at
#
#         https://aws.amazon.com/apache-2-0/
#
#     or in the "license" file accompanying this file. This file is distributed
#     on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either
#     express or implied. See the License for the specific language governing
#     permissions and limitations under the License.

import os
import requests
from datetime import datetime
import getopt, sys
import urllib3
import boto3
import json

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Usage
usageInfo = """Usage:
This scripts checks if a notebook is idle for X seconds if it does, it'll stop the notebook:
python autostop.py --time <time_in_seconds> [--port <jupyter_port>] [--ignore-connections] [--ignore-terminals]
Type "python autostop.py -h" for available options.
"""
# Help info
helpInfo = """-t, --time
    Auto stop time in seconds
-p, --port
    jupyter port
-c --ignore-connections
    Stop notebook once idle, ignore connected users
-u --ignore-terminals
    Ignore terminals
-h, --help
    Help information
"""

# Read in command-line parameters
idle = True
port = '8443'
ignore_connections = False
ignore_terminals = False
try:
    opts, args = getopt.getopt(sys.argv[1:], "ht:p:cu", ["help","time=","port=","ignore-connections","ignore-terminals"])
    if len(opts) == 0:
        raise getopt.GetoptError("No input parameters!")
    for opt, arg in opts:
        if opt in ("-h", "--help"):
            print(helpInfo)
            exit(0)
        if opt in ("-t", "--time"):
            time = int(arg)
        if opt in ("-p", "--port"):
            port = str(arg)
        if opt in ("-c", "--ignore-connections"):
            ignore_connections = True
        if opt in ("-u", "--ignore-terminals"):
            ignore_terminals = True
except getopt.GetoptError:
    print(usageInfo)
    exit(1)

# Missing configuration notification
missingConfiguration = False
if not time:
    print("Missing '-t' or '--time'")
    missingConfiguration = True
if missingConfiguration:
    exit(2)


def is_idle(last_activity):
    last_activity = datetime.strptime(last_activity,"%Y-%m-%dT%H:%M:%S.%fZ")
    if (datetime.now() - last_activity).total_seconds() > time:
        return True
    else:
        return False


def get_notebook_name():
    log_path = '/opt/ml/metadata/resource-metadata.json'
    with open(log_path, 'r') as logs:
        _logs = json.load(logs)
    return _logs['ResourceName']

# use mtime of pseudo terminal slaves under /dev/pts to determine user terminal activity
def get_terminals():
    terminals = {}
    dir = '/dev/pts'
    if os.path.isdir(dir):
        for pts in os.listdir(dir):
            if pts.isdigit():
                mtime = os.path.getmtime(dir + '/' + pts)
                terminals[pts] = datetime.fromtimestamp(mtime).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return terminals

session_count = 0
terminal_count = 0

# This is hitting Jupyter's sessions API: https://github.com/jupyter/jupyter/wiki/Jupyter-Notebook-Server-API#Sessions-API
response = requests.get('https://localhost:'+port+'/api/sessions', verify=False)
data = response.json()
if len(data) > 0:
    for notebook in data:
        # Idleness is defined by Jupyter
        # https://github.com/jupyter/notebook/issues/4634
        session_count += 1
        if notebook['kernel']['execution_state'] == 'idle':
            if not ignore_connections:
                if notebook['kernel']['connections'] == 0:
                    if not is_idle(notebook['kernel']['last_activity']):
                        idle = False
                else:
                    idle = False
            else:
                if not is_idle(notebook['kernel']['last_activity']):
                    idle = False
        else:
            idle = False

if not ignore_terminals:
    terminals = get_terminals()
    terminal_count = len(terminals)
    for pts in terminals:
        if not is_idle(terminals[pts]):
            idle = False

if session_count == 0 and terminal_count == 0:
    client = boto3.client('sagemaker')
    uptime = client.describe_notebook_instance(
        NotebookInstanceName=get_notebook_name()
    )['LastModifiedTime']
    if not is_idle(uptime.strftime("%Y-%m-%dT%H:%M:%S.%fZ")):
        idle = False

if idle:
    client = boto3.client('sagemaker')
    client.stop_notebook_instance(
        NotebookInstanceName=get_notebook_name()
    )

