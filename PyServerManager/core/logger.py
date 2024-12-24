import logging
import threading
from datetime import datetime

try:
    from tqdm import tqdm
except ModuleNotFoundError:
    tqdm = None

# Define the custom log level
CUSTOM_DEBUG = 5
logging.addLevelName(CUSTOM_DEBUG, "CUSTOM_DEBUG")


def custom_debug(self, message, *args, **kwargs):
    """
    @param self: logger instance
    @param message: log message
    """
    if self.isEnabledFor(CUSTOM_DEBUG):
        self._log(CUSTOM_DEBUG, message, args, **kwargs)


def dict_to_string(dict_):
    """
    @param dict_: dictionary to format
    @return: formatted string representation of the dictionary
    """
    return '\n' + '\n'.join([f'\t{k}: {v}' for k, v in dict_.items()])


# Injecting custom_debug into Logger class
logging.Logger.custom_debug = custom_debug


class ColorfulFormatter(logging.Formatter):
    format_dict = {
        logging.DEBUG: "\033[94m",  # Blue
        logging.INFO: "\033[92m",  # Green
        logging.WARNING: "\033[93m",  # Yellow
        logging.ERROR: "\033[91m",  # Red
        logging.CRITICAL: "\033[1;31m",  # Bold red
        CUSTOM_DEBUG: "\033[95m",  # Purple
    }

    def format(self, record):
        """
        @param record: logging record
        @return: formatted record message with color
        """
        color_format = self.format_dict.get(record.levelno)
        if color_format:
            record.levelname = f"{color_format}{record.levelname}\033[0m"
            record.msg = f"{color_format}{record.msg}\033[0m"
        return super().format(record)


class SingletonLogger(logging.Logger):
    """
    @brief A singleton logger with custom formatting, custom debug level,
           and built-in progress display.
    """
    _instances = {}
    _lock = threading.Lock()

    # Presets for logging formatters
    FORMAT_PRESETS = {
        "detailed": {
            "format": "%(levelname)s [%(asctime)s - %(name)s:%(module)s:%(lineno)s - %(funcName)s()] || %(message)s",
            "datefmt": "%d-%b-%y %H:%M:%S"
        },
        "simple": {
            "format": "%(levelname)s [%(filename)s:%(lineno)s - %(funcName)s()] %(message)s",
            "datefmt": "%H:%M:%S"
        },
        "filename_only": {
            "format": "%(levelname)s [%(filename)s:%(lineno)d] %(message)s",
            "datefmt": "%H:%M:%S"
        }
    }

    @classmethod
    def get_instance(cls, name='PyServerManager', preset='detailed'):
        """
        @param name: logger name
        @param preset: preset name for formatting
        @return: singleton logger instance
        """
        if name not in cls._instances:
            with cls._lock:
                if name not in cls._instances:
                    logging.setLoggerClass(cls)  # Set the custom logger class
                    logger = logging.getLogger(name)
                    logger.setLevel('DEBUG')
                    ch = logging.StreamHandler()
                    ch.setLevel('DEBUG')
                    logger.propagate = False
                    preset_config = cls.FORMAT_PRESETS.get(preset, cls.FORMAT_PRESETS["detailed"])
                    formatter = ColorfulFormatter(
                        preset_config["format"],
                        datefmt=preset_config["datefmt"]
                    )
                    ch.setFormatter(formatter)
                    logger.addHandler(ch)
                    cls._instances[name] = logger
        return cls._instances[name]

    def progress(self, iterable, desc="Processing", level=logging.INFO, **kwargs):
        """
        @param iterable: iterable to loop over
        @param desc: description text for the progress bar
        @param level: log level
        @return: yields items from iterable with progress display
        """
        bar_color = ColorfulFormatter.format_dict.get(level, "\033[0m")  # Default to no color

        # Always log start and completion of the process
        start_msg = f"{desc} started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        self.log(level, start_msg)

        if tqdm is not None:
            # Use tqdm if available
            with tqdm(iterable, desc=f"{bar_color}{desc}\033[0m", **kwargs) as pbar:
                for item in pbar:
                    yield item
        else:
            # If tqdm not available, fallback to a simple log at intervals
            total = len(iterable) if hasattr(iterable, "__len__") else None
            count = 0
            for item in iterable:
                yield item
                count += 1
                if total and count % max(1, total // 10) == 0:
                    self.log(level, f"{desc}: {count}/{total} completed.")

        complete_msg = f"{desc} completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        self.log(level, complete_msg)

    def log_dict(self, level, dict_, prefix="Dictionary contents:"):
        """
        @param level: log level
        @param dict_: dictionary to log
        @param prefix: optional prefix message
        """
        self.log(level, f"{prefix}{dict_to_string(dict_)}")


logger = SingletonLogger.get_instance(preset="detailed")
logger_level = {
    'critical': 50,
    'error': 40,
    'warning': 30,
    'info': 20,
    'debug': 10,
    'custom_debug': 5,
    'notset': 0
}
setattr(logger, 'logger_level', logger_level)

# Example usage
if __name__ == "__main__":
    import time

    test_dict = {"key1": "value1", "key2": "value2"}
    logger.log_dict(logging.INFO, test_dict, "Here is a dict:")

    for _ in logger.progress(range(20), desc="Example Progress"):
        time.sleep(.1)
