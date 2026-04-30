import subprocess
import logging
import re

class ShellOutputBuffer:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object('gcode')
        self.results = []

        self.gcode.register_command('EXECUTE_AND_STORE', self.cmd_EXECUTE_AND_STORE,
                                    desc=self.cmd_EXECUTE_AND_STORE_help)

    cmd_EXECUTE_AND_STORE_help = "Run a shell command and store output in memory"

    def cmd_EXECUTE_AND_STORE(self, gcmd):
        cmd_str = gcmd.get('COMMAND')
        if not cmd_str:
            raise gcmd.error("No COMMAND parameter provided")

        # clear previous results.
        self.results = []

        try:
            process = subprocess.Popen(
                cmd_str,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

            stdout, stderr = process.communicate()
            retcode = process.poll()

            if retcode == 0:
                output = stdout.decode().strip()
                self.results.append(output)
                gcmd.respond_info(f"Output stored: {output}")
            else:
                err_msg = stderr.decode().strip()
                gcmd.respond_info(f"Command failed (stored error): {err_msg}")
                self.results.append(f"Error: {err_msg}")

        except Exception as e:
            logging.exception("Shell command execution failed")
            gcmd.respond_info(f"Exception: {e}")
            self.results.append(f"Exception: {e}")

    def get_status(self, eventtime):
        last_output = self.results[-1] if self.results else ''
        data_pattern = re.compile(r"^(\w+)>>>(.*)<<<$")
        match = data_pattern.match(last_output)
        output = match.group(2) if match else last_output
        return {'buffer_size': len(self.results), 'output': output}

def load_config_prefix(config):
    return ShellOutputBuffer(config)
