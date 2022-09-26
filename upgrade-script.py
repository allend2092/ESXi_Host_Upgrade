'''
Script will perform automated ESXi upgrade
Author: Daryl Allen

This script is meant to run on an ESXi host

'''

from pprint import pprint
from time import sleep
import sys
import os


vms_template = '''
Vmid            Name                                              File                                             Guest OS          Version {{ignore}}                                Annotation
{{vmid}}   {{name}}                [EL_MGMT_VSAN] {{file}}               {{guestos}}       vmx-{{version}}
'''


def getvms(host):
    print("Parsing VMs...")
    resp = host.send_command("vim-cmd vmsvc/getallvms | tail -n+2 | awk '{print $1\":\"$2}'")
    print("Response is: " + resp)

    if resp == '':
        vms = ''
        return vms

    else:
        vms = {}
        for i in resp.split('\n'):
            host = i.split(':')[1]
            vmid = i.split(':')[0]
            try:
                int(vmid)
                vms[host] = vmid
            except:
                pass
    return vms

def getvms_onbox():
    print("Parsing VMs...")
    resp = os.popen("vim-cmd vmsvc/getallvms | tail -n+2 | awk '{print $1\":\"$2}'").read()
    print("Response is: " + resp)

    if resp == '':
        vms = ''
        return vms

    else:
        vms = {}
        for i in resp.split('\n'):
            host = i.split(':')[0]
            vmid = i.split(':')[0]
            try:
                int(vmid)
                vms[host] = vmid
            except:
                pass
    return vms

def poweroffvm_onbox(vm):
    # unlike function shutdownvm(), this will power off VMs regardless of having VMware tools installed
    resp = os.popen('vim-cmd vmsvc/power.off ' + vm).read()
    print('Powered down VM ' + vm)
    return resp

def getvmpowerstate_onbox(vm):
    resp = os.popen("vim-cmd vmsvc/get.summary " + vm).read()
    for i in resp.split('\n'):
        if "powerState" in i:
            return str(i.split("=")[1]).replace('"', '').replace(',', '').strip()

def upgradehost_onbox(path):
    print("sending upgrade command to host.")
    print("esxcli software profile update -p ESXi-7.0U2c-18426014-standard -d '" + path + "'")
    resp = os.popen("esxcli software profile update -p ESXi-7.0U2c-18426014-standard -d '" + path + "'").read()
    print(resp)

def maintenancemode_onbox(state):
    if state:
        print("Attempting to put host in MM. If it takes more than 45 seconds, I'm exiting program with an error.")
        resp = os.popen("esxcli system maintenanceMode set --enable true").read()
        print(resp)
    else:
        resp = os.popen("esxcli system maintenanceMode set --enable false").read()
    print(resp)

def reboothost_onbox():
    print("Attempting to reboot the host! Please wait!")
    resp = os.popen("reboot now").read()
    print(resp)
    return 0

def poweron_onbox(vm):
    resp = os.popen("vim-cmd vmsvc/power.on " + vm).read()
    print("I've powered on VM " + vm)
    print(resp)

def sendcommand_onbox(command):
    resp = os.popen(command).read()
    return resp

if __name__ == "__main__":

    # Remove check for command line arguments as it makes the code less prone to human mistyping parameters

    # There should be no need to login to ESXi host since script is already on the host datastore

    # Script will find out what directory its in
    remotepath = sendcommand_onbox('pwd')

    # Output given back with nextline character, we are removing it here
    remotepath = remotepath.rstrip()

    # Adding quotation marks to the directory path since the full path can have spaces sometimes
    remotepath = "'" + remotepath + "/'"
    print('Current working directory: ' + remotepath)

    # What is the name of the file being used for upgrade? Hard coded file name.
    file_name = 'VMware-ESXi-7.0U2c-18426014-depot.zip'
    print('Searching for file: ' + file_name)

    # List out the contents of the directory and collect the results in a variable
    directory_contents = sendcommand_onbox("ls -l " + remotepath)

    # Check if the upgrade file is on the host datastore and in the correct directory. If not, exit script.
    if file_name in directory_contents:
        print('Found file ' + file_name + ' in directory ' + remotepath)
        print('proceeding with host upgrade.')
    else:
        print('Did not find file ' + file_name + ' in directory ' + remotepath)
        print('Cancelling the host upgrade.')
        exit(0)

    # Removing the quotation marks from this string that were previously added so this string can be concatenated
    remotepath = remotepath.rstrip("'")
    remotepath = remotepath.strip("'")

    # set file path to be used for upgrade
    remotepath = remotepath + file_name
    print("Full path for upgrade file is: " + remotepath)

    # make sure we enable SSH to turn on with the host reboot
    sendcommand_onbox('vim-cmd hostsvc/enable_ssh')

    # enable VM auto start feature
    sendcommand_onbox('vim-cmd hostsvc/autostartmanager/enable_autostart 1')

    print("Getting list of VMs!")
    vms = getvms_onbox()

    print("Completed getting list of VMs!")
    sleep(1)

    # Getting the powerstate of the VMs and putting it into dictionary
    powerstate = {}
    if vms == '':
        print("There are no VMs on this host. Skipping to the next step of the upgrade.")
    else:
        for i in vms:
            powerstate[vms[i]] = getvmpowerstate_onbox(vms[i])
        for i in powerstate:
            print(powerstate[i] + "\n")

        print("Dumping powerstate table just in case something goes wrong later....")
        pprint(powerstate)

    sleep(1)

    # Configure VMs for auto power on and power off the VMs
    if vms == '':
        print('There are no VMs on this host, skipping VM power down.')
    else:
        print("")
        # I've created this variable as a substitute for index variable in the for loop.
        # index variable in the for loop is thrown off by ESXi hosts with powered off VMs
        auto_vm_power_on_sequence = 1
        # powerstate dict must use separate index+1 or iteration will not be in ascending order.
        for index, i in enumerate(powerstate.keys()):
            if powerstate[i] == "poweredOn":
                # Configure VM for auto-start
                print('vim-cmd hostsvc/autostartmanager/update_autostartentry ' + vms[i] + ' "PowerOn" "15" "'
                      + str(auto_vm_power_on_sequence) + '" "systemDefault" "systemDefault" "systemDefault"')
                sendcommand_onbox('vim-cmd hostsvc/autostartmanager/update_autostartentry ' + vms[i] +
                                  ' "PowerOn" "15" "' + str(auto_vm_power_on_sequence) +
                                  '" "systemDefault" "systemDefault" "systemDefault"')

                # Powering off the VM, skipping shutdown since the script runs on esxi and severs user connection
                print("Shutting down ID: " + i + "\n")
                shutdown_response = poweroffvm_onbox(i)
                auto_vm_power_on_sequence += 1
                print(shutdown_response)

    sleep(1)

    print("Trying to put the host in MM.")
    maintenancemode_onbox(True)
    print("Host in MM successful.")
    sleep(1)

    print("Upgrading host. After upgrade, will bring host out of MM and reboot the host!")
    upgradehost_onbox(remotepath)

    # Bringing host out of MM:
    print("Upgrade complete. Bringing host out of MM.")
    maintenancemode_onbox(False)

    # Rebooting the host and disconnecting the SSH session.
    print("Rebooting Host")
    reboothost_onbox()

    print("Complete!")

# See PyCharm help at https://www.jetbrains.com/help/pycharm/
