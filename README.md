# ESXi On-Box Upgrade Script (README)

This README describes the purpose, usage, and workflow of the **esxi_onbox_upgrade_v4.py** script. It is intended for **NFV (Network Functions Virtualization) environments** where ESXi hosts reside at remote or satellite locations and cannot leverage vMotion or centralized vCenter features to migrate running workloads elsewhere during upgrade.

## Overview

- **What This Script Does**  
  1. **Locates & Verifies the Upgrade ZIP** on the ESXi host’s local datastore.  
  2. **Checks for Registered VMs** on that host.  
  3. **Attempts to Gracefully Shutdown VMs** if VMware Tools is installed/running, otherwise forces a power-off.  
  4. **Enables Auto-Start** on each VM that was running, to ensure they power back up automatically after reboot.  
  5. **Places the Host in Maintenance Mode** (MM is required for an in-place ESXi upgrade).  
  6. **Performs the ESXi Upgrade** using `esxcli software profile update`.  
  7. **Verifies the Upgrade Output** to confirm success and check whether a reboot is required.  
  8. **Either Reboots on Success** (host then reboots, and VMs auto-start) **OR**  
     - If the upgrade failed, **Exits Maintenance Mode** and re-powers the VMs so that management-plane connectivity is restored.

- **Why This Approach?**  
  - In NFV setups, the ESXi host often runs firewall or SD-WAN appliances. Once you shut them down, you lose the remote management connection. Hence the script **must run locally on the ESXi shell** to survive the disconnection.  
  - Because vMotion is not available, you **must** power off all VMs to enter Maintenance Mode for an ESXi upgrade. This script does that automatically.  
  - After the host reboots (or if the upgrade fails), the script ensures that VMs come back up, restoring network and management-plane connectivity.

## Script Logic Breakdown

1. **Script Startup & Logging**  
   - **Recommended usage**:  
     ```
     python3 esxi_onbox_upgrade_v4.py >> /vmfs/volumes/datastore1/logs/esxi_upgrade.log 2>&1
     ```
     This captures all script output in a file for troubleshooting.

2. **Check for Upgrade ZIP File**  
   - The script declares a hard-coded `UPGRADE_FILENAME` (e.g., `VMware-ESXi-8.0U3-24022510-depot.zip`) and checks if it’s present in the current working directory (`pwd`). If not found, it exits.

3. **Search for VMs & Attempt Graceful Shutdown**  
   - The script calls `vim-cmd vmsvc/getallvms` to get a list of VMIDs.  
   - For each powered-on VM, it tries:
     - **Graceful shutdown** (`vim-cmd vmsvc/power.shutdown <VMID>`) if VMware Tools is detected in a running state.  
     - **Forced power-off** otherwise.

4. **Enable Auto-Start**  
   - Before shutting down each VM, the script configures auto-start entries so that any VMs that were powered on previously will automatically start after host reboot.

5. **Maintenance Mode Check**  
   - The script puts the host into Maintenance Mode using `esxcli system maintenanceMode set --enable true` and polls `esxcli system maintenanceMode get` until it detects `"enabled"` or reaches a timeout (default 45 seconds).  
   - If it **cannot enter MM**, it re-powers any VMs to restore connectivity, then exits.

6. **Perform the Upgrade**  
   - Executes `esxcli software profile update -p <PROFILE> -d '<ZIP_PATH>'`  
   - Stores the output for checking:

     ```
     Message: The update completed successfully, but the system needs to be rebooted for the changes to be effective.
     Reboot Required: true
     ```

7. **Reboot & VM Re-Power**  
   - If the script sees `"The update completed successfully"` **and** `"Reboot Required: true"` in the esxcli output, it:
     1. Exits Maintenance Mode  
     2. Reboots the host  
   - Otherwise, it **exits Maintenance Mode** without rebooting and **re-powers** any VMs that were shut down, letting you diagnose further.

## Notes & Recommendations

- **Run Locally**  
  Because powering down VMs might disable the remote management path, run the script locally via SSH on the ESXi shell.
  
- **Logging**  
  Always capture output using `>> some_log_file 2>&1` so you can review the upgrade’s results later.

- **Graceful Shutdown Limitations**  
  A graceful VM shutdown **requires** that the VM’s Guest OS has VMware Tools installed and running. If Tools is not detected, the script will do a hard power-off.

- **Customizing Timers**  
  You can adjust the `MAINTENANCE_MODE_TIMEOUT` (how long we wait for MM) and `SHUTDOWN_TIMEOUT_PER_VM` (how long we allow graceful shutdown to proceed) at the top of the script.

- **Profile & ZIP File Name**  
  Change the `UPGRADE_FILENAME` and `UPGRADE_PROFILE` variables to match the ESXi version you intend to apply.

## Conclusion

This script is a **simple, robust** approach to **on-box** upgrades in **isolated/remote** ESXi deployments (NFV environments) where:
- There is **no vMotion** or cluster to shift workloads to another host, and  
- Shutting down VMs **loses** remote management, so the upgrade must survive local disconnections.

It ensures that:
1. VMs are automatically brought back online post-upgrade.
2. The host successfully enters Maintenance Mode before the upgrade.
3. A potential upgrade failure does not leave the host & VMs offline.

