import datetime as dt
import logging
import sys
import os


def get_logger(model_path: str, suffix: str = ""):
    """
    Construct logger and store

    :param model_path: str, path for logger output
    :param name_suffix: str, path for logger output
    :return logger object
    """
    if suffix == "":
        now_string = f'{dt.datetime.now().strftime("%d_%m_%Y_%H_%M_%S")}'
        logger_fname = f'{model_path}_{now_string}.log'
    else:
        logger_fname = f'{model_path}_{suffix}.log'

    # create formatter
    log_format = '%(message)s'
    # log_format = '%(asctime)s %(levelname)s %(module)s - %(funcName)s: %(message)s'
    stream_formatter = logging.Formatter(log_format)

    # create file formatter
    file_formatter = logging.Formatter(log_format, datefmt='%Y-%m-%d %H:%M:%S')

    # create logger
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)

    # fix for erroneous logger duplication
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()

    # create file handler which logs even debug messages
    file_handler = logging.FileHandler(filename=logger_fname)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # create console handler with a higher log level
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(stream_formatter)
    logger.addHandler(console_handler)

    return logger
