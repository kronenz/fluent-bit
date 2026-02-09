#!/usr/bin/env python3
"""
SSH Helper using pexpect for password authentication.
Replaces sshpass for SSH commands.

Usage:
    SSH_HOST=host SSH_USER=user SSH_PASSWORD=pass ssh-helper.py <remote_command>

Environment variables:
    SSH_HOST: Remote host
    SSH_USER: SSH username
    SSH_PASSWORD: SSH password
"""

import sys
import os
import pexpect

def main():
    # Get credentials from environment
    ssh_host = os.environ.get('SSH_HOST')
    ssh_user = os.environ.get('SSH_USER')
    ssh_password = os.environ.get('SSH_PASSWORD')

    if not all([ssh_host, ssh_user, ssh_password]):
        print("ERROR: SSH_HOST, SSH_USER, and SSH_PASSWORD environment variables must be set", file=sys.stderr)
        sys.exit(1)

    if len(sys.argv) < 2:
        print("ERROR: Remote command required", file=sys.stderr)
        sys.exit(1)

    # Join all arguments as the remote command
    remote_command = ' '.join(sys.argv[1:])

    # Build SSH command
    ssh_cmd = f"ssh -o StrictHostKeyChecking=no {ssh_user}@{ssh_host} {remote_command}"

    try:
        # Spawn the SSH process
        child = pexpect.spawn(ssh_cmd, encoding='utf-8', timeout=600)

        # Do NOT set logfile_read here - we collect output after auth

        # Handle password prompt or host key confirmation
        index = child.expect([
            'password:',
            'Are you sure you want to continue connecting',
            pexpect.EOF,
            pexpect.TIMEOUT
        ])

        if index == 0:
            # Password prompt - send password, then stream remaining output
            child.sendline(ssh_password)
            child.logfile_read = sys.stdout
            child.expect(pexpect.EOF)
        elif index == 1:
            # Host key confirmation
            child.sendline('yes')
            child.expect('password:')
            child.sendline(ssh_password)
            child.logfile_read = sys.stdout
            child.expect(pexpect.EOF)
        elif index == 2:
            # EOF - command completed without prompts (key-based auth?)
            # Print whatever was captured before EOF
            if child.before:
                sys.stdout.write(child.before)
        else:
            # Timeout
            print("ERROR: SSH connection timeout", file=sys.stderr)
            child.close()
            sys.exit(1)

        # Close and get exit status
        child.close()
        exit_code = child.exitstatus if child.exitstatus is not None else 0
        sys.exit(exit_code)

    except pexpect.ExceptionPexpect as e:
        print(f"ERROR: SSH failed: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
