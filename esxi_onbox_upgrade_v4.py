#!/usr/bin/env python3
"""
Script will perform automated ESXi upgrade
Author: Daryl Allen / Revised

- Removed all f-strings to be Python 3.5 compatible
- Parameterize the ESXi depot filename & profile name
- Add error checking
- Attempt graceful VM shutdown if VMware Tools is running
- Confirm the host actually enters Maintenance Mode
- Check upgrade output for success before reboot
- If upgrade fails, re-power VMs to restore connectivity
"""

import os
import sys
from time import sleep
from pprint import pprint

# ----------------------------
#    CONFIGURATION SECTION
# ----------------------------
UPGRADE_FILENAME = "VMware-ESXi-8.0U3-24022510-depot.zip"
UPGRADE_PROFILE = "ESXi-8.0U3-24022510-standard"
MAINTENANCE_MODE_TIMEOUT = 45  # seconds
SHUTDOWN_TIMEOUT_PER_VM = 10   # seconds to wait for graceful shutdown to succeed

def sendcommand_onbox(command):
    """
    Send a CLI command from Python to the ESXi shell.
    Returns all output as a string.
    """
    return os.popen(command).read()

def check_vmware_tools_status(vmid):
    """
    Check the VMware Tools status for a VM by ID.
    We'll parse output of 'vim-cmd vmsvc/get.guest <vmid>'
    Look for a line: toolsStatus = "XXXX"
    Returns one of: 'toolsOk', 'toolsOld', 'toolsNotInstalled', 'toolsNotRunning', etc.
    If we cannot find it, returns None.
    """
    cmd = "vim-cmd vmsvc/get.guest " + vmid
    output = sendcommand_onbox(cmd)
    # Example line: toolsStatus = "toolsOk",
    for line in output.splitlines():
        if "toolsStatus" in line:
            # e.g. toolsStatus = "toolsOk",
            status_str = line.split("=")[1].replace('"', '').replace(',', '').strip()
            return status_str
    return None

def poweroffvm_onbox(vmid):
    """
    Immediately forces a power-off of the VM with 'vim-cmd vmsvc/power.off <vmid>'
    """
    cmd = "vim-cmd vmsvc/power.off " + vmid
    resp = sendcommand_onbox(cmd)
    print("Forced power-off VM {0}. Output:\n{1}".format(vmid, resp))
    return resp

def graceful_shutdown_onbox(vmid):
    """
    Attempt a graceful shutdown of the VM by ID (requires VMware Tools).
    We'll attempt 'vim-cmd vmsvc/power.shutdown <vmid>' and then wait a bit.
    """
    print("Attempting graceful shutdown of VM " + vmid)
    cmd = "vim-cmd vmsvc/power.shutdown " + vmid
    resp = sendcommand_onbox(cmd)
    if resp.strip():
        print("Power.shutdown response: " + resp)

    # Wait a little to confirm power-off
    for _ in range(SHUTDOWN_TIMEOUT_PER_VM):
        ps = getvmpowerstate_onbox(vmid)
        if ps != "poweredOn":
            print("VM " + vmid + " is now off (or shutting down).")
            return True
        sleep(1)
    return False

def shutdownvm_onbox(vmid):
    """
    Decide whether to gracefully shut down or force power off.
    If VMware tools is in a usable state, attempt graceful. Otherwise force.
    """
    status = check_vmware_tools_status(vmid)
    if status and status.lower() in ("toolsok", "toolsold"):
        # Attempt graceful shutdown
        ok = graceful_shutdown_onbox(vmid)
        if not ok:
            print("Graceful shutdown timed out for VM " + vmid + ", forcing power-off.")
            poweroffvm_onbox(vmid)
    else:
        # Tools not installed/running, force power-off
        poweroffvm_onbox(vmid)

def getvmpowerstate_onbox(vm):
    """
    Return "poweredOn" or "poweredOff" from `vim-cmd vmsvc/get.summary <vmid>`
    """
    cmd = "vim-cmd vmsvc/get.summary " + vm
    resp = sendcommand_onbox(cmd)
    for line in resp.split('\n'):
        if "powerState" in line:
            return line.split('=')[1].replace('"', '').replace(',', '').strip()
    return "unknown"

def getvms_onbox():
    """
    Returns dictionary of { <vmid>: <vmid> } for each VM. (Simplified from original.)
    """
    print("Parsing VMs...")
    resp = sendcommand_onbox("vim-cmd vmsvc/getallvms | tail -n+2 | awk '{print $1}'")
    print("Response is:\n" + resp)

    if not resp.strip():
        return {}

    vms = {}
    for line in resp.strip().split('\n'):
        vmid = line.strip()
        if vmid.isdigit():
            vms[vmid] = vmid
    return vms

def maintenancemode_onbox(enable):
    """
    If enable=True, attempt to place host in MM. Otherwise exit MM.
    Also perform a check if the operation succeeded.
    """
    if enable:
        print("Attempting to put host in Maintenance Mode...")
        sendcommand_onbox("esxcli system maintenanceMode set --enable true")
        # Wait up to X seconds for the host to be in maintenance mode
        for i in range(MAINTENANCE_MODE_TIMEOUT):
            mm_status = sendcommand_onbox("esxcli system maintenanceMode get").strip()
            if mm_status.lower() == "enabled":
                print("Host is now in Maintenance Mode.")
                return True
            sleep(1)
        print("ERROR: Timed out after {0}s waiting for Maintenance Mode.".format(MAINTENANCE_MODE_TIMEOUT))
        return False
    else:
        print("Exiting Maintenance Mode...")
        sendcommand_onbox("esxcli system maintenanceMode set --enable false")
        # Check after a moment if truly disabled
        for _ in range(5):
            mm_status = sendcommand_onbox("esxcli system maintenanceMode get").strip()
            if mm_status.lower() == "disabled":
                print("Host is out of Maintenance Mode.")
                return True
            sleep(1)
        print("WARNING: Host did not report 'disabled' after exiting Maintenance Mode.")
        return False

def upgradehost_onbox(full_path_to_zip):
    """
    Send the upgrade command to host. Return the text output for success/failure parsing.
    Use the globally configured UPGRADE_PROFILE name.
    """
    print("Sending upgrade command to host:")
    cmd = "esxcli software profile update -p {0} -d '{1}'".format(UPGRADE_PROFILE, full_path_to_zip)
    print("Command: " + cmd)
    resp = sendcommand_onbox(cmd)
    print(resp)
    return resp

def reboothost_onbox():
    print("Attempting to reboot the host! Please wait!")
    sendcommand_onbox("reboot now")
    # We lose the shell here effectively
    return 0

def poweron_onbox(vm):
    cmd = "vim-cmd vmsvc/power.on " + vm
    resp = sendcommand_onbox(cmd)
    print("I've powered on VM {0}. Output:\n{1}".format(vm, resp))

def main():
    print("===== ESXi On-Box Upgrade Script =====")
    print("Upgrade Filename: " + UPGRADE_FILENAME)
    print("Upgrade Profile:  " + UPGRADE_PROFILE)

    # 1) Identify current working directory
    remotepath = sendcommand_onbox("pwd").strip()
    print("Current working directory: '" + remotepath + "/'")

    # 2) Check if the upgrade file is present
    print("Searching for file: " + UPGRADE_FILENAME)
    directory_contents = sendcommand_onbox("ls -l '" + remotepath + "'")
    if UPGRADE_FILENAME not in directory_contents:
        print("Did NOT find file {0} in directory '{1}'. Cancelling upgrade.".format(UPGRADE_FILENAME, remotepath))
        sys.exit(1)
    print("Found file " + UPGRADE_FILENAME + " in directory '" + remotepath + "'. Proceeding...")

    # Full path
    full_path_to_zip = remotepath + "/" + UPGRADE_FILENAME
    print("Full path for upgrade file is: " + full_path_to_zip)

    # 3) Enable SSH and auto-start
    sendcommand_onbox("vim-cmd hostsvc/enable_ssh")
    sendcommand_onbox("vim-cmd hostsvc/autostartmanager/enable_autostart 1")

    # 4) Gather VMs
    print("Getting list of VMs!")
    vms = getvms_onbox()
    print("Completed getting list of VMs!")
    sleep(1)

    # 5) For each VM that is powered on, set auto-start and then power it down
    if not vms:
        print("No VMs found on this host. Skipping VM power down.")
    else:
        auto_vm_power_on_sequence = 1
        for vmid in vms:
            power_state = getvmpowerstate_onbox(vmid)
            if power_state == "poweredOn":
                # Configure for auto-start
                cmd_auto_start = ("vim-cmd hostsvc/autostartmanager/update_autostartentry {0} "
                                  "\"PowerOn\" \"15\" \"{1}\" "
                                  "\"systemDefault\" \"systemDefault\" \"systemDefault\""
                                 ).format(vmid, auto_vm_power_on_sequence)
                print("Configuring VM {0} for auto-start:\n{1}".format(vmid, cmd_auto_start))
                sendcommand_onbox(cmd_auto_start)

                # Attempt graceful shutdown
                shutdownvm_onbox(vmid)
                auto_vm_power_on_sequence += 1

    # 6) Put the host in Maintenance Mode
    mm_ok = maintenancemode_onbox(True)
    if not mm_ok:
        # Could not enter MM. Re-power on VMs to restore connectivity
        print("ERROR entering MM. Re-powering VMs to restore potential connectivity.")
        for vmid in vms:
            power_state = getvmpowerstate_onbox(vmid)
            if power_state == "poweredOff":
                poweron_onbox(vmid)
        sys.exit(2)

    # 7) Perform the upgrade
    print("Upgrading host. After upgrade, we will verify success/failure.")
    upgrade_resp = upgradehost_onbox(full_path_to_zip)

    # 8) Check if the upgrade completed successfully
    if ("The update completed successfully" in upgrade_resp and
        "Reboot Required: true" in upgrade_resp):
        print("Upgrade appears successful. Exiting MM & rebooting.")
        # Bring host out of MM
        maintenancemode_onbox(False)

        # 9) Reboot
        reboothost_onbox()
        print("Complete! The host is now rebooting.")
    else:
        print("WARNING: Upgrade output did NOT indicate success. We will exit Maintenance Mode and re-power VMs.")
        # Bring host out of MM anyway
        maintenancemode_onbox(False)
        # Re-power the VMs that were forcibly shut down (or gracefully shut down).
        for vmid in vms:
            power_state = getvmpowerstate_onbox(vmid)
            if power_state == "poweredOff":
                poweron_onbox(vmid)
        print("No reboot performed. Please investigate the upgrade logs.")
        sys.exit(3)

if __name__ == "__main__":
    main()
