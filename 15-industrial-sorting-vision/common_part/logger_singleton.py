import logging
import logging.handlers
import threading


class SingletonMeta(type):
    _instances = {}
    _lock = threading.Lock()

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            with cls._lock:
                if cls not in cls._instances:   # double-checked locking
                    cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]

class Logger(metaclass=SingletonMeta):
    def __init__(self, log_file='app.log', log_level=logging.INFO):
        self.logger = logging.getLogger('screening_logger')
        if self.logger.handlers:
            return
        self.logger.setLevel(log_level)
        self.logger.propagate = False

        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

        fh = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=10_000_000, backupCount=5, encoding='utf-8')
        fh.setFormatter(formatter)

        ch = logging.StreamHandler()
        ch.setFormatter(formatter)

        self.logger.addHandler(fh)
        self.logger.addHandler(ch)

    def get_logger(self):
        return self.logger