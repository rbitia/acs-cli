"""

Create and manage instances of Azure Container Service. The service
configuration is defined in the `cluster.ini` file (or the file
specified in `--config-file`.

Usage:
  service <command> [help] [options]
  service execOnMaster <command>

Commands:
  create                create an Azure Container Service
  delete                delete an Azure Container Service
  scale                 Scale the agent cluster up
  show                  display the current service configuration
  connect               open an SSH tunnel to the management interface
  disconnect            close the current SSH tunnel
  execOnMaster          execute a command on the lead master

Options:
  --agents=<number>            number of agents (currently scale only scale up is supported)
  --quiet                      don't ask the user for input
Examples:

Make the number of agents in the primary pool 5
  acs service scale --agents=5

Help:
  For help using the oms command please open an issue at 
  https://github.com/rgardler/acs-scripts

"""
from .base import Base

from docopt import docopt
from inspect import getmembers, ismethod
import json
import os
from sshtunnel import SSHTunnelForwarder
import subprocess
import sys  
from tempfile import mkstemp
import signal
import time
from time import sleep
import urllib.request
from shutil import move
from os import remove, close

class Service(Base):

  def run(self):
    args = docopt(__doc__, argv=self.options)
    # self.log.debug("Service args")
    # self.log.debug(args)
    self.args = args
    
    command = self.args["<command>"]
    result = None

    if self.args["execOnMaster"]:
      print(self.execOnMaster(command))
      return

    methods = getmembers(self, predicate = ismethod)
    for name, method in methods:
      if name == command:
        result = method()
        if result is None:
          result = command + " returned no results"
    if result:
      print(result)
    else:
      print("Unknown command: '" + command + "'")
      self.help()
   	  
  def help(self):
    print(__doc__)

  def exists(self):
    """ Tests whether the management endpoint is accessible, if it is we assume the service exists """
    exists = Base._hostnameResolves(self, Base.getManagementEndpoint(self))
    return exists

  def create(self):
    if self.exists():
      msg = "It appears that the cluster already exists:\n" + self.show()
      self.log.debug(msg)
      return msg

    self.log.debug("Creating ACS Deployment")
    self.log.debug(json.dumps(self.config.getACSParams()))

    Base.createResourceGroup(self)
    
    self._deploy(self.config.get('ACS', 'dnsPrefix'))
    
    if self.exists():
      if self.config.get('ACS', 'orchestratorType') == 'DCOS':
        self.install_dcos_cli()
        
      return self.show()

  def install_dcos_cli(self):
    self.log.info("Installing DCOS CLI")

    self.connect()
    
    cmd = "pip install virtualenv"
    os.system(cmd)

    cmd = "wget https://raw.githubusercontent.com/mesosphere/dcos-cli/master/bin/install/install-optout-dcos-cli.sh -O install-optout-dcos-cli.sh"
    os.system(cmd)

    cmd = "chmod +x install-optout-dcos-cli.sh"
    os.system(cmd)

    cmd = "./install-optout-dcos-cli.sh . http://localhost --add-path yes"
    os.system(cmd)

    self.log.info("DCOS installed. If you want to use the DC/OS command line directly then execute `. /src/bin/env-setup`")

    
  def _deploy(self, deploymentName):
    command = "azure group deployment create"
    command = command + " " + self.config.get('Group', 'name')
    command = command + " " + deploymentName
    command = command + " --template-uri " + self.config.get('Template', 'templateUrl')
    command = command + " -p '" + json.dumps(self.config.getACSParams()) + "'"
    os.system(command)

  def delete(self, quiet = False):
    self.log.debug("Deleting ACS Deployment")
    self.log.debug(json.dumps(self.config.getACSParams()))
    
    dns = self.config.get("ACS", "dnsPrefix")
    group = self.config.get("Group", "name")
    if not quiet and not self.args["--quiet"]:
      responded = False
      while not responded:
        resp = input("Do you really want to delete the ACS cluster '" + dns + "' in resource group '" + group + "' ('y' or 'yes' to confirm, 'n' or 'no' to abort)?\n")
        if resp == "y" or resp == "yes":
          responded = True
        elif resp == "n" or resp == "no":
          self.log.debug("Aborting delete at users request")
          return "Delete aborted"
        
    command = "azure acs delete"
    command = command + " " + group
    command = command + " containerservice-" + self.config.get('ACS', 'dnsPrefix')
    os.system(command)
    
    # FIXME: we shouldn't need to do the group delete, but currently container delete is not a deep delete
    print("'azure acs delete 'does not currently delete resources created within the container service. You can delete all resources by also deleting the associated resource group, however, be aware this will delete everything in the resource group.")
    command = "azure group delete " 
    if quiet or self.args["--quiet"]:
      command = command + " --quiet "
    command = command + self.config.get('Group', 'name')
    os.system(command)

  def scale(self):
    if not self.exists():
      return "It appears that the cluster does not exists (try running `acs service createo`)"

    desired_agents = self.args["--agents"]

    fh, abs_path = mkstemp()
    with open(abs_path,'w') as new_file:
      with open(self.config.filename) as old_file:
        for line in old_file:
          if line.startswith("agentCount:"):
            new_file.write("agentCount: " + str(desired_agents) + "\n")
          else:
            new_file.write(line)
    close(fh)
    try:
      remove(self.config.filename + ".bak")
    except OSError:
      pass
    move(self.config.filename, self.config.filename + ".bak")
    move(abs_path, self.config.filename)

    self._deploy("scale")
    
    return "Scaled to " + str(desired_agents)

  def show(self):
    """
    Output the configuration of this cluster in json format.
    """
    config = self.getClusterSetup()
    return json.dumps(config, sort_keys=True,
                      indent=4, separators=(',', ': '))

  def openTunnel(self):
    """DEPRECATED: use connect() instead"""
    self.connect()
    self.log.warning("Service.openTunnel() is deprecated. Please use Service.connect instead.")
  
  def connect(self):
    """Open an SSH tunnel to the management endpoint, if one doesn't
    already exist. The PID for the tunnel is written to
    `~/.acs/ssh.pid`.  If a tunnel already exiss then a new one will
    not be created instead PID for the existing tunnel will be
    returned.

    This method attempts to block until we have an active connection
    to the master endpoint.

    """

    pidpath = os.path.expanduser("~/.acs/ssh.pid")
    if os.path.isfile(pidpath):
      pidfile = open(pidpath)
      pid = pidfile.read()
      pidfile.close()

      # check the process exists
      # 'kill(pid, 0)' does not kill the process, it just throws an `OSError` if the PID does not exist
      try:
        os.kill(int(pid), 0)
        return "A tunnel already exists using PID " + str(pid)
      except OSError:
        # seems the old tunnel has gone away
        self.log.info("A PIDFile exists, but the process does not seem to be present. Removing the PIDFile and opening a new tunnel.")
        os.remove(pidpath)
    
    try:
      pid = os.fork()
      if pid > 0:
        # Exit parent process
        pidfile = open(pidpath, 'w')
        pidfile.write(str(pid))
        pidfile.close()
        # TODO: is this still needed??
        time.sleep(0.5)

        # wait until we can connect to the master endpoint
        isConnected = False
        attempts = 0
        while not isConnected and attempts < 50:
          req = urllib.request.Request("http://localhost")
          try:
            with urllib.request.urlopen(req) as response:
              html = response.read()
              isConnected = True
          except urllib.error.URLError as e:
            isConnected = False
            attempts = attempts + 1
            self.log.debug("SSH tunnel not established, waiting for 1/10th of a second")
            time.sleep(0.1)

        if attempts < 50:
          msg = "Connection opened (PID " + str(pid) + ")"
        else:
          raise RuntimeError("Unable to open an SSH tunnel to the management endpoint.")
          
        return msg
    except OSError as e:
      msg = "Unable to create forked proces for the SSH Tunnel: " + str(e)
      self.log.error(msg)
      raise RuntimeError(msg)

    # Decouple from the parent environment
    os.chdir("/")
    os.setsid()
    os.umask(0)

    with SSHTunnelForwarder(
      (self.getManagementEndpoint(), 2200),
      remote_bind_address = ('localhost', 80),
      local_bind_address = ('', 80),
      ssh_username = self.config.get('ACS', 'username'),
      ssh_pkey = os.path.expanduser(self.config.get('SSH', "privatekey"))
    ) as server:
      while True:
        sleep(10)

  def closeTunnel(self):
    """DEPRECATED: use disconnect() instead"""
    self.disconnect()
    self.log.warningxo("Service.closeTunnel() is deprecated. Please use Service.disconnect instead.")
  
  def disconnect(self):
    """
    Close the SSH tunnel to the management endpoint with the supplied pid
    """

    pidpath = os.path.expanduser("~/.acs/ssh.pid")
    if os.path.isfile(pidpath):
      pidfile = open(pidpath)
      pid = pidfile.read()
      pidfile.close()

      # check the process exists
      # 'kill(pid, 0)' does not kill the process, it just throws an `OSError` if the PID does not exist
      try:
        os.kill(int(pid), 0)
      except OSError:
        # seems the old tunnel has gone away
        self.log.debug("A PIDFile exists, but the process does not seem to be present. Removing the PIDFile.")
        os.remove(pidpath)
    else:
      raise RuntimeWarning("No SSH PID file, therefore assuming there is no active tunnel to close.")

    self.log.info("Attempting to kill the SSH tunnel, process: " + pid)
    try:
      os.kill(int(pid), signal.SIGTERM)
      time.sleep(1.0)
      os.remove(pidpath)
      return "Disconnected"
    except OSError as err:
      self.log.exception(err)
      raise RuntimeError("Unable to killthe SSH Tunnel process: " + str(err))
    
  def execOnMaster(self, command):
    """
    Execute the supplied sommand on the lead master.
    """
    return self.executeOnMaster(command)
        
  def marathonCommand(self, command, method = 'GET', data = None):
    self.connect()
    curl = 'curl -s -X ' + method 
    if data != None:
      curl = curl + " -d \"" + data + "\" -H \"Content-type:application/json\""
    cmd = curl + ' localhost/marathon/v2/' + command 
    self.log.debug('Command to execute: ' + cmd)
    result = self.shell_execute(cmd)
    self.disconnect()
    return result
