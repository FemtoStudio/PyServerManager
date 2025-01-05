# task_executor.py
import argparse
import ast
import base64
import json
import sys
from pathlib import Path

from PyServerManager.core.logger import logger, dict_to_string


# The TaskExecutor class is the base class for all executors.
# It sets up the argument parser and processes the arguments.
class TaskExecutor:
    OUTPUT_PREFIX = '##BEGIN_ENCODED_OUTPUT##'
    OUTPUT_SUFFIX = '##END_ENCODED_OUTPUT##'

    # The constructor method for the BaseExecutor class.
    # It initializes the argument parser and processes the arguments.
    def __init__(self, *args, **kwargs):
        self.args = None
        self.args_dict = {}
        self.parser = argparse.ArgumentParser(description=self.__class__.__name__)
        self.logger = logger
        if not kwargs.get('skip_setup_parser', False):
            self.setup_parser()
            self.processes_parser()

    # This property method returns the frame range.
    @property
    def frame_range(self):
        return self.args_dict.get('frame_range', (1001, 1001))

    # This static method returns the frame range.
    @staticmethod
    def frame_range_type(frame_range):
        if isinstance(frame_range, str):
            return ast.literal_eval(frame_range) or (1001, 1001)
        else:
            return frame_range

    def send_output(self, output_dict):
        """
        Encodes the output_dict and prints it to stdout with known prefix and suffix.
        """
        encoded_output = base64.b64encode(json.dumps(output_dict).encode('utf-8')).decode('utf-8')
        print(f'{self.OUTPUT_PREFIX}{encoded_output}{self.OUTPUT_SUFFIX}')

    # This method removes an argument from the argument parser.
    def remove_argument(self, arg_name):
        """
        Removes an argument from the argparse.ArgumentParser instance.

        Args:
            arg_name: The name of the argument to remove. Automatically adds '--' prefix if not present.
        """
        # Ensure the argument name starts with '--'
        if not arg_name.startswith('--'):
            arg_name = '--' + arg_name

        # Remove the argument from _actions list
        self.parser._actions = [action for action in self.parser._actions if action.dest != arg_name.lstrip('-')]

        # Remove the argument from _option_string_actions dictionary
        if arg_name in self.parser._option_string_actions:
            del self.parser._option_string_actions[arg_name]

    # This method sets up the argument parser.
    def setup_parser(self):
        """
        This method sets up the argument parser.
        It adds arguments for the cache directory, output path, input path, frame range, logger level, and data.
        """
        self.parser.add_argument('--encoded-args', help='Base64 encoded JSON arguments')

    # This method processes the arguments.
    def processes_parser(self):
        """
        This method processes the arguments.
        It parses the arguments and stores them in a dictionary.
        """
        self.args = self.parser.parse_args()
        if self.args.encoded_args:
            decoded_args = base64.b64decode(self.args.encoded_args).decode('utf-8')
            self.args_dict = json.loads(decoded_args)
        else:
            self.args_dict = {}
        # <-- Destroy the parser so it won't get pickled
        del self.parser

    def run(self):
        """
        This method is intended to be updated by the user to handle the data processing logic.
        The user should implement the actual data processing logic here.

        In this current implementation, it reads the image, logs the arguments and the input, and prints a message indicating that the run is complete.

        Returns:
            The result of the data processing.
        """
        print(f'{"*" * 50} Running {self.__class__.__name__} {"*" * 50}')
        self.logger.info(f"Pars args {dict_to_string(self.args_dict)}\n")
        print(f'{"*" * 55} Done {"*" * 55}')
        self.send_output({'status': 'success', 'message': 'Run complete.'})

    @staticmethod
    def get_relative_pacakge(file_path: str, index: int = 2):

        # Path of the current script
        script_path = Path(file_path).resolve()
        # Root directory of your project (you might need to adjust this path)
        root_dir = script_path.parents[index]  # Adjust the index depending on your structure

        # Add the project root directory to sys.path if not already included
        if str(root_dir) not in sys.path:
            sys.path.insert(0, str(root_dir))

        # Calculate the package name by finding the relative path from root to the script's directory
        relative_package_path = script_path.parent.relative_to(root_dir).as_posix().replace('/', '.')
        return relative_package_path



# This is the main entry point of the script.
# It creates a BaseExecutor object and sets the logger level.
if __name__ == '__main__':
    # Create a BaseExecutor object.
    executor = TaskExecutor()
    try:
        # Try to get the logger level from the arguments.
        lvl = int(executor.args_dict.get('logger_level'))
    except TypeError:
        # If the logger level is not specified in the arguments, set it to 20.
        lvl = 20
    # Set the logger level.
    executor.logger.setLevel(lvl)
    executor.run()
