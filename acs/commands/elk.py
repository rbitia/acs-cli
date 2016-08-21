"""
Add the
Elk Stack and dockerbeat monitoring solution to the cluster.

Usage:
  elk <command> [help] [options]

Commands:
  install                Install the Elk stack and Dockerbeat monitoring agent on all ACS agents

Options:

Help:
  For help using the oms command please open an issue at 
  https://github.com/rgardler/acs-scripts

"""

from docopt import docopt
from inspect import getmembers, ismethod
from json import dumps
from .lb import Lb
from .base import Base
from .app import App
from .service import Service
class Elk(Base):

  def run(self):
      args = docopt(__doc__, argv=self.options)
      # print("Global args")
      # print(args)
      self.args = args

      command = self.args["<command>"]
      result = None
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

  def install(self):
      """Deploy elk stack as a container and configure dockerbeat on all ACS agents

      """
      #create a tunnel 
      service = Service(self.config, self.options)
      service.create()
      service.connect()    
    

      #deploy elk stack with Marathon
           
      args = self.args
      self.log.debug("`demo elk stack` args before adding app-config:\n" + str(args))
      args["--app-config"] = "config/demo/web/elkstack.json"
        
      app = App(self.config, self.options)
      app.args = args
      app.deploy()
        
      # open ports in azure
      
      lb = Lb(self.config, None)
      lb.args = {"--port": 5601}
      lb.open()
      lb.args = {"--port": 9200}
      lb.open()
      # marathon load balancer
      self.shell_execute("dcos package install marathon-lb --yes")
     
      ips = Base.getAgentIPs(self)
      for ip in ips:
        self.log.debug("Installing Dockerbeat on: " + ip)
        
        result = ""

        #cmd = "sudo touch /etc/dockerbeat.yml\n"
        #result = self.executeOnAgent(cmd, ip)

        cmd = "sudo curl -L --create-dirs -o ~/acs/dockerbeat/dockerbeat https://extensions.blob.core.windows.net/mindaro/dockerbeat\n"
        result = self.executeOnAgent(cmd, ip)
	
        cmd = "sudo chmod 744 ~/acs/dockerbeat/dockerbeat\n"
        result = self.executeOnAgent(cmd, ip)
        #cmd = "sudo chmod 744 ~/acs/dockerbeat/dockerbeat"
        #result = self.executeOnAgent(cmd, ip)
	
        # cmd = "sudo chmod 744 /etc/systemd/system/dockerbeat.service"
        #result = self.executeOnAgent(cmd, ip)

        #cmd = "sudo mkdir /etc/dockerbeat"
        #result = self.executeOnAgent(cmd, ip)

        cmd = "echo Configuring dockerbeat\n"
        result = self.executeOnAgent(cmd, ip)
        cmd = "sudo mkdir -p /etc/systemd/system"
        self.executeOnAgent(cmd, ip)
       
        result = self.executeOnAgent(cmd, ip)
        # cmd = "sudo cp ~/dockerbeat.service /etc/systemd/system/dockerbeat.service\n"
        # result = self.executeOnAgent(cmd, ip)
        cmd = "sudo mkdir -p /etc/dockerbeat\n"
        result = self.executeOnAgent(cmd, ip)
        cmd = "sudo touch /etc/dockerbeat/dockerbeat.yml\n"
        result = self.executeOnAgent(cmd, ip)

        cmd = """sudo cat << EOT > ~/dockerbeat.yml
input:
 period: 10 
 socket: unix:///var/run/docker.sock
tls:
 enable: false
output:
 logstash:
  hosts: ["elkstack.marathon.mesos:5044"]
  worker: 1
 shipper:
 logging:
  to_syslog: false
  to_files: true
  files:
    path: /var/log/dockerbeat
    name: dockerbeat
    rotateeverybytes: 10485760 # = 10MB
    level: info
EOT\n"""
        result = self.executeOnAgent(cmd, ip)
        cmd = "sudo cp ~/dockerbeat.yml /etc/dockerbeat/dockerbeat.yml"
        self.executeOnAgent(cmd, ip)     
        #cmd = "exit"
        #result = self.executeOnAgent(cmd, ip)
        pid = Base.executeInBackgroundOnAgent(self, "sudo /home/azureuser/acs/dockerbeat/dockerbeat -c /etc/dockerbeat/dockerbeat.yml", ip)
        #cmd = "sudo /home/azureuser/acs/dockerbeat/dockerbeat -c /etc/dockerbeat/dockerbeat.yml &\n"
        result = self.executeOnAgent(cmd, ip)
	#Kill the other sudo process
        pidNum = str(pid)
        cmd = "sudo kill -9 " + pidNum
        result = self.executeOnAgent(cmd, ip)
	 
	



  def help(self):
    print(__doc__)

